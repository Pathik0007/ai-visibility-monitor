"""Stripe: plans activate only after a confirmed payment, webhooks use
Stripe's current state, and Stripe objects (not dicts) are handled."""

from unittest import mock

import pytest
import stripe

from models import User


@pytest.fixture()
def stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_starter")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_pro")


def so(d):  # what the Stripe SDK really returns: a StripeObject, not a dict
    return stripe.StripeObject.construct_from(d, "sk_test_x")


def sub(status="active", price="price_pro", sid="sub_1"):
    return so({"id": sid, "customer": "cus_1", "status": status, "items": {"data": [{"price": {"id": price}}]}})


def test_success_requires_a_paid_checkout(client, make_user, login, stripe_env, db):
    u = make_user(); u.stripe_customer_id = "cus_1"; db.session.commit()
    login()
    unpaid = so({"customer": "cus_1", "mode": "subscription", "status": "open", "payment_status": "unpaid",
                 "subscription": None, "metadata": {"plan": "pro"}})
    with mock.patch("stripe.checkout.Session.retrieve", return_value=unpaid):
        client.get("/billing/success?session_id=cs_test_1")
    assert db.session.get(User, u.id).subscription_status == "inactive"


def test_success_activates_after_payment(client, make_user, login, stripe_env, db):
    u = make_user(); u.stripe_customer_id = "cus_1"; db.session.commit()
    login()
    paid = so({"customer": "cus_1", "mode": "subscription", "status": "complete", "payment_status": "paid",
               "subscription": "sub_1", "metadata": {"plan": "pro"}})
    with mock.patch("stripe.checkout.Session.retrieve", return_value=paid), \
            mock.patch("stripe.Subscription.retrieve", return_value=sub()):
        client.get("/billing/success?session_id=cs_test_1")
    u = db.session.get(User, u.id)
    assert (u.subscription_status, u.plan, u.stripe_subscription_id) == ("active", "pro", "sub_1")


def test_someone_elses_session_is_ignored(client, make_user, login, stripe_env, db):
    u = make_user(); u.stripe_customer_id = "cus_mine"; db.session.commit()
    login()
    paid = so({"customer": "cus_other", "mode": "subscription", "status": "complete", "payment_status": "paid",
               "subscription": "sub_9"})
    with mock.patch("stripe.checkout.Session.retrieve", return_value=paid):
        client.get("/billing/success?session_id=cs_test_1")
    assert db.session.get(User, u.id).subscription_status == "inactive"


def _event(etype, obj):
    return so({"type": etype, "data": {"object": obj}})


def test_webhook_cancels_and_uses_current_state(client, make_user, stripe_env, db):
    u = make_user(status="active", plan="pro"); u.stripe_customer_id = "cus_1"; u.stripe_subscription_id = "sub_1"
    db.session.commit()
    ev = _event("customer.subscription.deleted", {"id": "sub_1", "customer": "cus_1", "status": "canceled"})
    with mock.patch("stripe.Webhook.construct_event", return_value=ev), \
            mock.patch("stripe.Subscription.retrieve", return_value=sub(status="canceled")):
        assert client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "x"}).status_code == 200
    assert db.session.get(User, u.id).subscription_status == "inactive"


def test_webhook_about_an_old_subscription_is_ignored(client, make_user, stripe_env, db):
    u = make_user(status="active", plan="pro"); u.stripe_customer_id = "cus_1"; u.stripe_subscription_id = "sub_new"
    db.session.commit()
    ev = _event("customer.subscription.deleted", {"id": "sub_old", "customer": "cus_1"})
    with mock.patch("stripe.Webhook.construct_event", return_value=ev), mock.patch("stripe.Subscription.retrieve") as r:
        client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
    assert db.session.get(User, u.id).subscription_status == "active" and not r.called


def test_webhook_rejects_bad_signature(client, stripe_env):
    with mock.patch("stripe.Webhook.construct_event", side_effect=ValueError("bad sig")):
        assert client.post("/billing/webhook", data=b"{}").status_code == 400
