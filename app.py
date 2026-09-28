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
from datetime import date
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

from extensions import csrf, limiter
from models import db, User, Business, CheckRun
from auth import auth_bp
from billing import billing_bp
from alerts import check_business_and_alert, run_weekly_checks
from ai_visibility.pipeline import run_visibility_check
from ai_visibility.providers import ALL_PROVIDERS
from places import search_places
import report_cache

IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production"
DEFAULT_DEV_SECRET = "dev-secret-change-me"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", DEFAULT_DEV_SECRET)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "data.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Render (like most PaaS hosts) terminates TLS at a reverse proxy and talks
# to the app over plain HTTP, adding X-Forwarded-* headers to say what the
# original request actually looked like. Without ProxyFix, Flask believes
# every request is HTTP from the proxy's own internal IP -- so
# request.remote_addr (what the rate limiter keys on) is the same address
# for every visitor, and request.scheme/url_for(_external=True) generate
# http:// links even in production. x_for/x_proto/x_host=1 trusts exactly
# one hop of forwarding headers, matching a single reverse proxy in front.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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


@app.context_processor
def inject_globals():
    return {"is_production": IS_PRODUCTION}


@app.after_request
def set_security_headers(response):
    """Baseline security headers on every response. CSP intentionally allows
    'unsafe-inline' for styles only (the templates use plenty of inline
    style="" attributes -- rewriting all of them was out of scope here) but
    NOT for scripts: every <script> in this app is an external /static/*.js
    file, so script-src stays locked to 'self'."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )
    # Harmless to send over plain HTTP (browsers only act on it once a page
    # has actually loaded over HTTPS) so it's set unconditionally rather
    # than gated on IS_PRODUCTION.
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


# ---------- input validation ----------

MAX_NAME_LEN = 200
MAX_COMPETITORS = 10


class ValidationError(Exception):
    pass


def parse_and_validate_business_fields(form) -> dict:
    business = form.get("business", form.get("name", "")).strip()
    category = form.get("category", "").strip()
    location = form.get("location", "").strip()
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


def _parse_num_queries(form, default: int = 6) -> int:
    """Never let a bad num_queries value 500 the request -- clamp anything
    unparseable back to the default instead of raising."""
    try:
        n = int(form.get("num_queries", default))
    except (TypeError, ValueError):
        n = default
    return min(max(n, 1), 10)


# Pages worth indexing -- kept in one place so robots.txt, sitemap.xml and
# each page's <meta name="robots"> all agree with each other.
_INDEXABLE_PAGES = ["index", "pricing", "faq", "about", "how_it_works", "privacy", "terms"]


# ---------- public landing / anonymous quick check ----------

@app.route("/", methods=["GET"])
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    provider_status = [{"name": p.display_name, "configured": p.is_configured()} for p in ALL_PROVIDERS]
    return render_template("index.html", provider_status=provider_status)


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


_FAQS = [
    {"q": "Is the visibility check really free?",
     "a": "Yes -- running a one-off check needs no account and no payment. Only weekly automatic monitoring of a saved business is a paid subscription."},
    {"q": "Which AI assistants does it check?",
     "a": "ChatGPT, Claude, Perplexity, Gemini and DeepSeek. Any assistant without an API key configured shows clearly-labeled simulated demo answers instead of live ones, so the product is fully testable either way."},
    {"q": "Why might I show up on one assistant but not another?",
     "a": "Each assistant sources its answers differently -- some lean on training data, others on live web search or a specific index like Google's. Your report includes a note on why a specific assistant might be missing you and what tends to help for that one."},
    {"q": "Does a higher score guarantee more customers?",
     "a": "No -- it's a measurement of current AI-assistant behavior, not a guarantee of outcomes. It's the same kind of leading indicator search-ranking or review-count is: worth improving, not a promise."},
    {"q": "Can I share a report with someone else?",
     "a": "Yes -- every check gets its own link that stays valid for 24 hours, so you can send it to a colleague or client without them having to run their own check."},
    {"q": "How is 'mentioned' actually measured?",
     "a": "We check whether your business's name appears as a whole word or phrase in the assistant's answer (not as a false-positive substring of a longer name), and, if the answer is a numbered or bulleted list, note what position it's in."},
]


@app.route("/faq")
def faq():
    return render_template("faq.html", faqs=_FAQS)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


_LEGAL_UPDATED = date(2026, 9, 28).strftime("%B %-d, %Y") if os.name != "nt" else date(2026, 9, 28).strftime("%B %d, %Y")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", updated_date=_LEGAL_UPDATED)


@app.route("/terms")
def terms():
    return render_template("terms.html", updated_date=_LEGAL_UPDATED)


@app.route("/llms.txt")
def llms_txt():
    """A plain-language summary for AI crawlers/assistants that fetch this
    file to understand what a site is and does -- an emerging convention
    (see llmstxt.org), separate from and complementary to robots.txt."""
    body = (
        "# AI Visibility Monitor\n\n"
        "> A tool that checks whether ChatGPT, Claude, Perplexity, Gemini and "
        "DeepSeek recommend a specific local business -- or a competitor -- "
        "when asked for a recommendation, and gives the business a concrete "
        "action plan to improve.\n\n"
        "## What it does\n"
        "- Runs realistic customer questions (e.g. \"best dentist in "
        "Parramatta\") through five major AI assistants.\n"
        "- Reports a visibility score: how often the business is mentioned, "
        "its average position when it's in a ranked list, and which "
        "competitors get named instead.\n"
        "- Produces a tailored action plan based on the business's category "
        "and on how each specific assistant tends to source its answers.\n\n"
        "## Who it's for\n"
        "Local business owners and marketers who want to know whether AI "
        "assistants -- increasingly used instead of a search engine for "
        "\"best X near me\" questions -- actually recommend them.\n\n"
        f"## Try it\n{url_for('index', _external=True)}\n"
    )
    return app.response_class(body, mimetype="text/plain")


@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.svg")


@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Disallow: /check\n"
        "Disallow: /dashboard\n"
        "Disallow: /businesses/\n"
        "Disallow: /login\n"
        "Disallow: /signup\n"
        "Disallow: /billing/\n"
        "Disallow: /api/\n"
        f"Sitemap: {url_for('sitemap_xml', _external=True)}\n"
    )
    return app.response_class(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    urls = "".join(
        f"  <url><loc>{url_for(ep, _external=True)}</loc></url>\n" for ep in _INDEXABLE_PAGES
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}"
        "</urlset>\n"
    )
    return app.response_class(body, mimetype="application/xml")


@app.route("/api/places")
@limiter.limit("30 per minute")
def api_places():
    """Business-name autocomplete, called as-you-type from the form. Always
    returns 200 with a (possibly empty) list -- never a hard error -- so a
    slow/unavailable lookup provider never breaks the underlying text field."""
    query = request.args.get("q", "")
    try:
        results = search_places(query)
    except Exception:
        results = []
    return {"results": results}


@app.route("/check", methods=["POST"])
@limiter.limit("5 per hour")  # each real check can fan out to 5 paid AI APIs -- keep anonymous use bounded
def check():
    try:
        fields = parse_and_validate_business_fields(request.form)
    except ValidationError as e:
        flash(str(e))
        return redirect(url_for("index"))

    num_queries = _parse_num_queries(request.form)

    report = run_visibility_check(
        fields["business"], fields["category"], fields["location"], fields["competitors"],
        num_queries=num_queries,
    )
    # Post/redirect/get: the report lives at its own shareable, refresh-safe
    # URL instead of being rendered straight from this POST handler (which
    # made refreshing the page re-run -- and re-bill -- the whole check).
    report_id = report_cache.save(report, location=fields["location"], category=fields["category"])
    return redirect(url_for("check_report", report_id=report_id), code=303)


@app.route("/check/<report_id>")
def check_report(report_id):
    data = report_cache.get(report_id)
    if data is None:
        flash("That report has expired or couldn't be found -- run a new check below.")
        return redirect(url_for("index"))
    return render_template(
        "report.html", report=data["report"], location=data["location"], category=data["category"],
    )


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


@app.errorhandler(404)
def not_found(e):
    return render_template(
        "error.html", code=404, title="Page not found",
        message="That page doesn't exist -- it may have moved, or the link was mistyped.",
    ), 404


@app.errorhandler(429)
def rate_limit_exceeded(e):
    # Rendered directly (not a redirect) -- a redirect to a 429 status code
    # doesn't work: browsers only follow redirects for 3xx responses, so the
    # visitor previously saw a bare, unstyled "Redirecting..." page instead
    # of an actual error message.
    return render_template(
        "error.html", code=429, title="Slow down a little",
        message="You've hit the limit for this action for now -- please try again in a little while.",
    ), 429


@app.errorhandler(500)
def server_error(e):
    return render_template(
        "error.html", code=500, title="Something went wrong",
        message="An unexpected error happened on our end. Please try again in a moment.",
    ), 500


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
