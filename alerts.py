"""
Turns a fresh CheckRun into an email alert when something meaningful changed
versus the previous run -- and does the actual re-checking, on a schedule,
for every monitored business.

No SMTP creds in .env -> alerts are written to alerts_outbox.log instead of
sent, clearly labeled as demo mode, so the whole loop is testable without a
real mail account.
"""

from __future__ import annotations
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

from models import db, Business, CheckRun
from ai_visibility.pipeline import run_visibility_check

SCORE_DROP_THRESHOLD = 15
OUTBOX_PATH = os.path.join(os.path.dirname(__file__), "alerts_outbox.log")


def _smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "ALERT_FROM_EMAIL"))


def detect_meaningful_change(latest: CheckRun, previous: CheckRun | None) -> str | None:
    if previous is None:
        return None

    # Either run may have no score at all if every provider call errored out
    # (outage, bad key) -- never treat that as a real visibility change.
    if previous.visibility_score is None or latest.visibility_score is None:
        return None

    drop = previous.visibility_score - latest.visibility_score
    if drop >= SCORE_DROP_THRESHOLD:
        return (f"Visibility score dropped {drop} points "
                f"({previous.visibility_score}% -> {latest.visibility_score}%).")

    prev_top = previous.report.get("top_competitors") or []
    latest_top = latest.report.get("top_competitors") or []
    prev_leader = prev_top[0][0] if prev_top else None
    latest_leader = latest_top[0][0] if latest_top else None
    if latest_leader and latest_leader != prev_leader:
        return f"{latest_leader} is now the most-recommended competitor (previously {prev_leader or 'none'})."

    return None


def send_alert_email(to_email: str, business: Business, reason: str, latest: CheckRun) -> None:
    subject = f"[AI Visibility] {business.name}: {reason}"
    body = (
        f"Hi,\n\n"
        f"Your weekly AI visibility check for {business.name} ({business.category}, "
        f"{business.location}) found a change worth a look:\n\n"
        f"  {reason}\n\n"
        f"Current visibility score: {latest.visibility_score}%\n"
        f"Full details: log in to your dashboard.\n"
    )

    if not _smtp_configured():
        with open(OUTBOX_PATH, "a") as f:
            f.write(f"--- {datetime.utcnow().isoformat()} [DEMO -- not actually sent, SMTP not configured] ---\n")
            f.write(f"To: {to_email}\nSubject: {subject}\n\n{body}\n\n")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.environ["ALERT_FROM_EMAIL"]
    msg["To"] = to_email

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.send_message(msg)


def check_business_and_alert(business: Business) -> CheckRun:
    """Runs the pipeline once for `business`, stores the result, and emails
    the owner if the change vs. the previous run is meaningful. Used by both
    the manual 'run check now' button and the weekly scheduled job."""
    from plans import plan_for, PLANS
    previous = business.latest_run  # last run *before* this new one
    plan = plan_for(business.owner) or PLANS["starter"]

    from category_match import screen_competitors
    tracked, flags = screen_competitors(business.category, business.competitor_list(), business.competitor_meta_dict())
    from categories import refine_category as _refine
    report = run_visibility_check(
        business.name, _refine(business.name, business.category)[0], business.location, tracked,
        num_queries=plan["questions"],
        extra_queries=business.custom_question_list()[: plan["custom_questions"]],
        profile_benchmark=plan["profile_benchmark"],
    )
    report["competitor_flags"] = flags
    from categories import refine_category
    report["category_note"] = refine_category(business.name, business.category)[1]
    run = CheckRun.from_report(business.id, report)
    db.session.add(run)
    db.session.commit()

    reason = detect_meaningful_change(run, previous)
    if reason:
        send_alert_email(business.owner.email, business, reason, run)

    return run


def is_due(business, now=None) -> bool:
    """Due once the plan's interval has passed since the last check (with a
    few hours' slack so a job that runs a bit early doesn't skip a cycle)."""
    from datetime import timedelta
    from plans import plan_for
    plan = plan_for(business.owner)
    if not plan:
        return False
    last = business.latest_run
    if last is None:
        return True
    now = now or datetime.utcnow()
    return now - last.created_at >= timedelta(days=plan["check_every_days"]) - timedelta(hours=6)


def run_weekly_checks(app) -> None:
    """Scheduled entry point (run it at least every 12 hours): re-checks
    every subscribed business that's due under its plan -- weekly on
    Starter, twice a week on Pro."""
    with app.app_context():
        for business in Business.query.all():
            if is_due(business):
                try:
                    check_business_and_alert(business)
                except Exception as exc:
                    print(f"[scheduler] check failed for business {business.id}: {exc}")
