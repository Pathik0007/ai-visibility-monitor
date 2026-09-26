"""
AI Visibility Monitor

Public landing page: anonymous one-off check (no login) -- the same demo
flow as before, good for showing people the product.

Logged-in area: save businesses, see history over time, get a weekly
automatic re-check with an email alert when something meaningful changes.
Saving a business requires an active (or demo-mode) subscription.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000
"""

from __future__ import annotations
import os
import atexit
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_required, current_user
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

from extensions import csrf, limiter
from models import db, User, Business, CheckRun
from auth import auth_bp
from billing import billing_bp
from alerts import check_business_and_alert, run_weekly_checks
from ai_visibility.pipeline import run_visibility_check
from ai_visibility.providers import ALL_PROVIDERS

IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production"
DEFAULT_DEV_SECRET = "dev-secret-change-me"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", DEFAULT_DEV_SECRET)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "data.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Secure cookies -- HttpOnly is Flask's default; add SameSite always, and
# require HTTPS-only cookies once actually deployed (FLASK_ENV=production).
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION

if IS_PRODUCTION and app.config["SECRET_KEY"] == DEFAULT_DEV_SECRET:
    raise RuntimeError(
        "FLASK_ENV=production but FLASK_SECRET_KEY is unset (still using the dev "
        "default). Set a real random secret in .env before going live -- e.g. "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
    )

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


csrf.init_app(app)
limiter.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(billing_bp)

# Stripe calls the webhook server-to-server -- it can't carry a session CSRF
# token, and it's already verified via Stripe's own signature check instead.
csrf.exempt(billing_bp)

with app.app_context():
    db.create_all()


# ---------- input validation ----------

MAX_NAME_LEN = 200
MAX_COMPETITORS = 10


class ValidationError(Exception):
    pass


def parse_and_validate_business_fields(form) -> dict:
    business = form.get("business", form.get("name", "")).strip()
    category = form["category"].strip()
    location = form["location"].strip()
    competitors_raw = [c.strip() for c in form.get("competitors", "").split(",") if c.strip()]

    if not business or not category or not location:
        raise ValidationError("Business name, category and location are all required.")
    for field_name, value in [("business name", business), ("category", category), ("location", location)]:
        if len(value) > MAX_NAME_LEN:
            raise ValidationError(f"{field_name} is too long (max {MAX_NAME_LEN} characters).")
    if len(competitors_raw) > MAX_COMPETITORS:
        raise ValidationError(f"Please list at most {MAX_COMPETITORS} competitors.")
    for c in competitors_raw:
        if len(c) > MAX_NAME_LEN:
            raise ValidationError(f"Competitor name too long (max {MAX_NAME_LEN} characters).")

    return {
        "business": business, "category": category,
        "location": location, "competitors": competitors_raw,
    }


# ---------- public landing / anonymous quick check ----------

@app.route("/", methods=["GET"])
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    provider_status = [{"name": p.display_name, "configured": p.is_configured()} for p in ALL_PROVIDERS]
    return render_template("index.html", provider_status=provider_status)


@app.route("/robots.txt")
def robots_txt():
    # Only the landing page is worth indexing -- everything else is either a
    # private account page or a throwaway per-search report page.
    body = (
        "User-agent: *\n"
        "Allow: /$\n"
        "Disallow: /check\n"
        "Disallow: /dashboard\n"
        "Disallow: /businesses/\n"
        "Disallow: /login\n"
        "Disallow: /signup\n"
        f"Sitemap: {url_for('sitemap_xml', _external=True)}\n"
    )
    return app.response_class(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{url_for('index', _external=True)}</loc></url>\n"
        "</urlset>\n"
    )
    return app.response_class(body, mimetype="application/xml")


@app.route("/check", methods=["POST"])
@limiter.limit("5 per hour")  # each real check can fan out to 4 paid AI APIs -- keep anonymous use bounded
def check():
    try:
        fields = parse_and_validate_business_fields(request.form)
    except ValidationError as e:
        flash(str(e))
        return redirect(url_for("index"))

    num_queries = min(max(int(request.form.get("num_queries", 6)), 1), 10)

    report = run_visibility_check(
        fields["business"], fields["category"], fields["location"], fields["competitors"],
        num_queries=num_queries,
    )
    return render_template("report.html", report=report, location=fields["location"], category=fields["category"])


# ---------- logged-in dashboard ----------

@app.route("/dashboard")
@login_required
def dashboard():
    businesses = Business.query.filter_by(user_id=current_user.id).all()
    return render_template("dashboard.html", businesses=businesses)


@app.route("/businesses/new", methods=["POST"])
@login_required
@limiter.limit("10 per hour", key_func=lambda: current_user.get_id())
def add_business():
    if not current_user.is_subscribed:
        flash("Subscribe first to add a business to monitor.")
        return redirect(url_for("dashboard"))

    try:
        fields = parse_and_validate_business_fields(request.form)
    except ValidationError as e:
        flash(str(e))
        return redirect(url_for("dashboard"))

    business = Business(
        user_id=current_user.id,
        name=fields["business"],
        category=fields["category"],
        location=fields["location"],
        competitors=", ".join(fields["competitors"]),
    )
    db.session.add(business)
    db.session.commit()

    check_business_and_alert(business)  # first run -- no "previous" yet, so no alert fires
    return redirect(url_for("business_detail", business_id=business.id))


@app.route("/businesses/<int:business_id>")
@login_required
def business_detail(business_id):
    business = Business.query.filter_by(id=business_id, user_id=current_user.id).first_or_404()
    history = list(reversed(business.runs))  # most recent first
    latest = history[0] if history else None
    previous = history[1] if len(history) > 1 else None
    return render_template("business.html", business=business, history=history, latest=latest, previous=previous)


@app.route("/businesses/<int:business_id>/run", methods=["POST"])
@login_required
@limiter.limit("6 per hour", key_func=lambda: current_user.get_id())
def run_business_now(business_id):
    business = Business.query.filter_by(id=business_id, user_id=current_user.id).first_or_404()
    check_business_and_alert(business)
    flash("Check complete.")
    return redirect(url_for("business_detail", business_id=business.id))


# ---------- misc ----------

@app.route("/healthz")
def healthz():
    """Plain liveness check for uptime monitors / load balancers -- touches
    the DB too so a broken connection shows up as unhealthy, not just a 200."""
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok"}, 200
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}, 503


@app.errorhandler(429)
def rate_limit_exceeded(e):
    flash("You've hit the limit for this action for now -- please try again a bit later.")
    return redirect(request.referrer or url_for("index")), 429


# ---------- weekly scheduler ----------
#
# In-process scheduling only works correctly with exactly one running
# process. It's fine for `python app.py` locally, but a real deployment
# behind Gunicorn typically runs several worker processes -- each would
# start its own copy of this scheduler and every saved business would get
# checked (and its owner emailed) once per worker, not once. So this is ON
# by default for the simple single-process case, and must be turned OFF
# once you run more than one worker; use scheduled_job.py from the host's
# own cron/scheduler feature instead (see README "Going live").

if os.environ.get("ENABLE_INPROCESS_SCHEDULER", "1") == "1":
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_weekly_checks, "interval", weeks=1, args=[app], id="weekly_visibility_check")
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1" and not IS_PRODUCTION
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
