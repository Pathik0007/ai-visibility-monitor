"""Web app: pages, access control, plan limits, health check."""

from unittest import mock

import pytest

from models import Business


def test_public_pages_render(client):
    for path in ("/", "/pricing", "/faq", "/how-it-works", "/website-check", "/privacy", "/terms",
                 "/robots.txt", "/sitemap.xml", "/llms.txt", "/login", "/signup"):
        assert client.get(path).status_code == 200, path


def test_security_headers(client):
    h = client.get("/").headers
    assert "script-src" in h["Content-Security-Policy"] and "'unsafe-inline'" not in h["Content-Security-Policy"].split("script-src")[1].split(";")[0]
    assert h["X-Frame-Options"] and h["X-Content-Type-Options"] == "nosniff"


def test_unknown_page_is_a_styled_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and b"AI Visibility" in r.data


def test_healthz_never_leaks_database_details(client):
    with mock.patch("app.db.session.execute", side_effect=RuntimeError("could not connect to host db.internal user=admin")):
        r = client.get("/healthz")
    assert r.status_code == 503 and b"db.internal" not in r.data and b"admin" not in r.data


def test_signup_duplicate_email(client, make_user):
    make_user("a@b.com")
    r = client.post("/signup", data={"email": "a@b.com", "password": "password123"})
    assert b"already exists" in r.data


def test_users_cannot_see_each_others_businesses(client, make_user, login, db):
    owner = make_user("owner@example.com", status="active")
    make_user("intruder@example.com", status="active")
    b = Business(user_id=owner.id, name="Ryde Dental", category="dentist", location="Ryde")
    db.session.add(b)
    db.session.commit()
    login("intruder@example.com")
    assert client.get(f"/businesses/{b.id}").status_code == 404
    assert client.post(f"/businesses/{b.id}/delete").status_code == 404
    assert client.get(f"/businesses/{b.id}/export.csv").status_code == 404
    assert db.session.get(Business, b.id) is not None


def test_plan_business_limit(client, make_user, login, db):
    make_user(status="active", plan="starter")
    login()
    form = {"name": "Ryde Dental", "category": "dentist", "location": "Ryde, NSW"}
    with mock.patch("app.check_business_and_alert"), mock.patch("places.geocode_location", return_value=None):
        client.post("/businesses/new", data=form)
        client.post("/businesses/new", data={**form, "name": "Second Dental"})
    assert Business.query.count() == 1  # Starter = 1 business


def test_demo_plan_stops_once_real_ai_keys_exist(make_user, monkeypatch):
    from plans import plan_for
    u = make_user(status="demo", plan="pro")
    assert plan_for(u)["key"] == "pro"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-key")
    assert plan_for(u) is None


def test_complimentary_accounts_get_pro(make_user, monkeypatch):
    from plans import plan_for
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-key")
    monkeypatch.setenv("COMPLIMENTARY_EMAILS", "Owner@Example.com, other@x.com")
    assert plan_for(make_user("owner@example.com"))["key"] == "pro"


def test_website_field_too_long_is_a_friendly_error(client):
    r = client.post("/check", data={"business": "A Cafe", "category": "cafe", "location": "Sydney",
                                    "website": "a" * 470 + ".com"})
    assert r.status_code < 500


def test_bad_website_is_a_friendly_error(client):
    r = client.post("/website-check", data={"url": "[::1"})
    assert r.status_code == 200
