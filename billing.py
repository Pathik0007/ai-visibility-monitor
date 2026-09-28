"""
Stripe subscription billing, gating the "monitor a business" feature.

No STRIPE_SECRET_KEY in .env -> "Subscribe" just flips the user to a demo
subscription immediately (clearly labeled in the UI) so the rest of the app
is fully testable without a real Stripe account. Add real keys to go live.
"""

import os
import stripe
from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

PRICE_ID = os.environ.get("STRIPE_PRICE_ID")
IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production"


def _stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY")) and bool(PRICE_ID)


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
    if not _stripe_configured():
        if _any_real_provider_configured():
            flash("Sign-ups are paused right now while billing is being finished -- please check back soon.")
            return redirect(url_for("dashboard"))
        current_user.subscription_status = "demo"
        db.session.commit()
        msg = "This subscribed you in demo mode -- no charge made."
        if not IS_PRODUCTION:
            msg += " Add STRIPE_SECRET_KEY and STRIPE_PRICE_ID in .env to take real payments."
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
        line_items=[{"price": PRICE_ID, "quantity": 1}],
        success_url=url_for("billing.success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("billing.cancel", _external=True),
    )
    return redirect(session.url, code=303)


@billing_bp.route("/success")
@login_required
def success():
    session_id = request.args.get("session_id")
    if _stripe_configured() and session_id:
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        session = stripe.checkout.Session.retrieve(session_id)
        current_user.subscription_status = "active"
        current_user.stripe_subscription_id = session.subscription
        db.session.commit()
        flash("Subscription active -- you can now add businesses to monitor.")
    return redirect(url_for("dashboard"))


@billing_bp.route("/cancel")
@login_required
def cancel():
    flash("Checkout canceled -- no charge made.")
    return redirect(url_for("dashboard"))


@billing_bp.route("/webhook", methods=["POST"])
def webhook():
    """Real production path: Stripe calls this on subscription lifecycle events.
    Keeps subscription_status in sync even if the user closes the tab after
    paying, or cancels/lapses later. No-ops harmlessly if Stripe isn't configured."""
    if not _stripe_configured():
        return "", 200

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return "", 400

    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    user = None
    if customer_id:
        from models import User
        user = User.query.filter_by(stripe_customer_id=customer_id).first()

    if user:
        if event["type"] in ("customer.subscription.deleted",):
            user.subscription_status = "inactive"
        elif event["type"] in ("customer.subscription.updated", "customer.subscription.created"):
            user.subscription_status = "active" if obj.get("status") == "active" else "inactive"
        db.session.commit()

    return "", 200
