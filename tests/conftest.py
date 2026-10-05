"""Shared fixtures. The app reads its config at import time, so the
environment is set up before anything imports it: a throwaway SQLite file,
no in-process scheduler, no rate limiting, and no real API/Stripe keys (every
external call in the suite is mocked; nothing touches the network)."""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_DB = os.path.join(tempfile.mkdtemp(prefix="avm-tests-"), "test.db")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_DB}",
    ENABLE_INPROCESS_SCHEDULER="0",
    FLASK_SECRET_KEY="test-secret",
    RATELIMIT_ENABLED="0",
)
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY",
           "GOOGLE_PLACES_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID",
           "STRIPE_PRICE_ID_PRO", "SMTP_HOST", "FLASK_ENV", "RENDER", "COMPLIMENTARY_EMAILS"):
    os.environ.pop(_k, None)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from app import app as flask_app
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    from extensions import limiter
    limiter.enabled = False
    return flask_app


@pytest.fixture()
def db(app):
    from models import db as _db
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        yield _db
        _db.session.remove()


@pytest.fixture()
def client(app, db):
    return app.test_client()


@pytest.fixture()
def make_user(db):
    from models import User

    def _make(email="owner@example.com", password="password123", status="inactive", plan="starter"):
        u = User(email=email, subscription_status=status, plan=plan)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u
    return _make


@pytest.fixture()
def login(client):
    def _login(email="owner@example.com", password="password123"):
        return client.post("/login", data={"email": email, "password": password})
    return _login


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never touch the internet: any real HTTP request to a non-local
    host fails like an outage would (the app must cope with that anyway)."""
    import requests
    from urllib.parse import urlparse
    real_send = requests.adapters.HTTPAdapter.send

    def guarded_send(self, request, *args, **kwargs):
        host = urlparse(request.url).hostname or ""
        if host in ("127.0.0.1", "localhost") or host.endswith(".example"):
            return real_send(self, request, *args, **kwargs)
        raise requests.ConnectionError(f"network disabled in tests: {host}")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", guarded_send)
