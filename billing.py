"""
Stripe subscription billing, gating the "monitor a business" feature.

No STRIPE_SECRET_KEY in .env -> "Subscribe" just flips the user to a demo
subscription immediately (clearly labeled in the UI) so the rest of the app
is fully testable without a real Stripe account. Add real keys to go live.
"""

import os
import stripe
from flask import Blueprint, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from models import db
from extensions import limiter

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production" or bool(os.environ.get("RENDER"))

# One Stripe recurring price per plan (see plans.py).
PRICE_ENV = {"starter": "STRIPE_PRICE_ID", "pro": "STRIPE_PRICE_ID_PRO"}


def _price_id(plan: str) -> str | None:
    return os.environ.get(PRICE_ENV.get(plan, "STRIPE_PRICE_ID"))


def _plan_for_price(price_id: str | None) -> str | None:
    for plan, env in PRICE_ENV.items():
        if price_id and os.environ.get(env) == price_id:
            return plan
    return None


def _plain(obj) -> dict:
    """Stripe >= 13 returns StripeObject instances that are NOT dicts (.get()
    raises AttributeError). Convert once at the boundary and use plain dicts."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    return to_dict() if callable(to_dict) else {}


def _stripe_configured(plan: str = "starter") -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY")) and bool(_price_id(plan))


def _any_real_provider_configured() -> bool:
    """True once at least one paid AI-assistant API key is set. Each
    "monitored business" runs real, metered API calls weekly -- auto-granting
    unlimited free "demo" subscriptions once those keys (and their bills)
    are live would let anyone rack up API cost with no payment ever
    collected. Demo mode is only safe to auto-grant while every provider is
    still in free simulated-answer mode."""
    from ai_visibility.providers import ALL_PROVIDERS
    return any(p.is_configured() for p in ALL_PROVIDERS)


@billing_bp.route("/checkout")
@login_required
def checkout():
    from plans import valid_plan, PLANS
    plan = valid_plan(request.args.get("plan"))

    # Already subscribed through Stripe and switching plans -> Stripe's own
    # billing portal handles proration/upgrades properly.
    if current_user.subscription_status == "active" and current_user.stripe_customer_id and _stripe_configured(plan):
        if (current_user.plan or "starter") == plan:
            flash(f"You're already on {PLANS[plan]['name']}.")
            return redirect(url_for("dashboard"))
        return redirect(url_for("billing.portal"))

    if not _stripe_configured(plan):
        if _any_real_provider_configured():
            flash("Sign-ups are paused right now while billing is being finished -- please check back soon.")
            return redirect(url_for("dashboard"))
        current_user.subscription_status = "demo"
        current_user.plan = plan
        db.session.commit()
        msg = f"You're on {PLANS[plan]['name']} in demo mode -- no charge made."
        if not IS_PRODUCTION:
            msg += f" Add STRIPE_SECRET_KEY and {PRICE_ENV[plan]} in .env to take real payments."
        flash(msg)
        return redirect(url_for("dashboard"))

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email)
        current_user.stripe_customer_id = customer.id
        db.session.commit()

    session = stripe.checkout.Session.create(
        customer=current_user.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": _price_id(plan), "quantity": 1}],
        metadata={"plan": plan},
        subscription_data={"metadata": {"plan": plan}},
        success_url=url_for("billing.success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("billing.cancel", _external=True),
    )
    return redirect(session.url, code=303)


@billing_bp.route("/portal")
@login_required
def portal():
    """Stripe-hosted page to switch plan, update card or cancel."""
    if not (os.environ.get("STRIPE_SECRET_KEY") and current_user.stripe_customer_id):
        flash("Billing management isn't available for this account.")
        return redirect(url_for("dashboard"))
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    session = stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id, return_url=url_for("dashboard", _external=True))
    return redirect(session.url, code=303)


@billing_bp.route("/success")
@login_required
def success():
    """Activates the plan only after Stripe confirms the checkout was paid and
    the subscription is live. The session id comes from the URL, so it must
    never be trusted on its own (an abandoned or replayed checkout session
    would otherwise unlock a paid plan for free). The webhook below is the
    source of truth; this just saves the user waiting for it."""
    from plans import valid_plan
    session_id = (request.args.get("session_id") or "").strip()
    if not (os.environ.get("STRIPE_SECRET_KEY") and session_id.startswith("cs_") and current_user.stripe_customer_id):
        return redirect(url_for("dashboard"))
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    try:
        session = _plain(stripe.checkout.Session.retrieve(session_id))
        if session.get("customer") != current_user.stripe_customer_id or session.get("mode") != "subscription":
            return redirect(url_for("dashboard"))
        if session.get("status") != "complete" or session.get("payment_status") not in ("paid", "no_payment_required"):
            flash("Your payment hasn't gone through yet -- we'll activate your plan as soon as Stripe confirms it.")
            return redirect(url_for("dashboard"))
        sub_id = session.get("subscription")
        sub = _plain(stripe.Subscription.retrieve(sub_id)) if sub_id else {}
    except Exception:
        current_app.logger.exception("Stripe checkout confirmation failed")
        flash("We couldn't confirm your payment just now -- it will activate automatically within a minute.")
        return redirect(url_for("dashboard"))

    if sub.get("status") in ("active", "trialing"):
        current_user.subscription_status = "active"
        current_user.stripe_subscription_id = sub_id
        current_user.plan = _plan_from_subscription(sub) or valid_plan(_plain(session.get("metadata")).get("plan"))
        db.session.commit()
        flash("Subscription active -- you can now add businesses to monitor.")
    return redirect(url_for("dashboard"))


def _plan_from_subscription(sub: dict) -> str | None:
    items = (_plain(sub.get("items")).get("data") or [])
    price = _plain(items[0]).get("price") if items else None
    return _plan_for_price(_plain(price).get("id"))


@billing_bp.route("/cancel")
@login_required
def cancel():
    flash("Checkout canceled -- no charge made.")
    return redirect(url_for("dashboard"))


@billing_bp.route("/webhook", methods=["POST"])
@limiter.exempt  # Stripe sends from a few IPs; never throttle billing events
def webhook():
    """Real production path: Stripe calls this on subscription lifecycle events.
    Keeps subscription_status in sync even if the user closes the tab after
    paying, or cancels/lapses later. No-ops harmlessly if Stripe isn't configured.

    Stripe doesn't guarantee delivery order, so the event body is only used to
    find the subscription; its CURRENT state is re-fetched from Stripe. Events
    about an older subscription never overwrite the user's current one."""
    if not os.environ.get("STRIPE_SECRET_KEY"):
        return "", 200
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return "", 400
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return "", 400

    etype = event["type"]
    if not etype.startswith("customer.subscription."):
        return "", 200
    obj = _plain(event["data"]["object"])
    customer_id, sub_id = obj.get("customer"), obj.get("id")
    if not (customer_id and sub_id):
        return "", 200

    from models import User
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return "", 200
    if user.stripe_subscription_id and user.stripe_subscription_id != sub_id:
        # An event about a different (older) subscription. Only let a NEW
        # live subscription replace the stored one.
        if user.subscription_status == "active" or etype == "customer.subscription.deleted":
            return "", 200

    try:
        sub = _plain(stripe.Subscription.retrieve(sub_id))
    except Exception:
        current_app.logger.exception("Stripe subscription fetch failed")
        return "", 500  # Stripe retries later
    status = sub.get("status") or obj.get("status")
    user.stripe_subscription_id = sub_id
    user.subscription_status = "active" if status in ("active", "trialing") else "inactive"
    plan = _plan_from_subscription(sub)
    if plan:
        user.plan = plan  # plan switches made in the billing portal
    db.session.commit()
    return "", 200
