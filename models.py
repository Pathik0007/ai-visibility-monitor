from __future__ import annotations
import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    # "inactive" | "active" | "demo"  -- "demo" = Stripe not configured, treated as subscribed
    subscription_status = db.Column(db.String(50), default="inactive")
    plan = db.Column(db.String(20), default="starter")  # see plans.py

    businesses = db.relationship("Business", backref="owner", cascade="all, delete-orphan")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_subscribed(self) -> bool:
        """Paid ("active"), complimentary (owner/test accounts listed in
        COMPLIMENTARY_EMAILS), or "demo" -- but demo only while every AI
        provider still runs on free sample answers. Once real (metered) keys
        are live, old demo accounts stop running paid checks."""
        from plans import is_complimentary, demo_subscriptions_allowed
        if self.subscription_status == "active" or is_complimentary(self.email):
            return True
        return self.subscription_status == "demo" and demo_subscriptions_allowed()


class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    competitors = db.Column(db.Text, default="")
    custom_questions = db.Column(db.Text, default="")  # Pro: one question per line
    competitor_meta = db.Column(db.Text, default="{}")  # {competitor name: category}, for mismatch checks
    website = db.Column(db.String(500), default="")  # optional; checked for AI-readiness each run
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    runs = db.relationship(
        "CheckRun", backref="business",
        cascade="all, delete-orphan",
        order_by="CheckRun.created_at",
    )

    def competitor_meta_dict(self) -> dict:
        try:
            data = json.loads(self.competitor_meta or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def custom_question_list(self) -> list[str]:
        return [q.strip() for q in (self.custom_questions or "").splitlines() if q.strip()]

    def competitor_list(self) -> list[str]:
        return [c.strip() for c in (self.competitors or "").split(",") if c.strip()]

    @property
    def latest_run(self):
        return self.runs[-1] if self.runs else None

    @property
    def previous_run(self):
        return self.runs[-2] if len(self.runs) >= 2 else None


class CheckRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("business.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    visibility_score = db.Column(db.Integer)
    mention_rate = db.Column(db.Float)
    avg_position = db.Column(db.Float, nullable=True)
    report_json = db.Column(db.Text)  # full report dict, serialized

    @property
    def report(self) -> dict:
        data = json.loads(self.report_json)
        # Reports saved before the "action plan" feature existed won't have this
        # key. Backfill it from the rest of the stored data (and the parent
        # Business's category, since older reports didn't store category either)
        # instead of crashing the history page or needing a DB migration.
        if "action_plan" not in data:
            from ai_visibility.solutions import build_action_plan
            category = data.get("category") or (self.business.category if self.business else "")
            data["action_plan"] = build_action_plan(
                category=category,
                by_engine=data.get("by_engine", {}),
                mention_rate=data.get("mention_rate") or 0,
                top_competitors=data.get("top_competitors", []),
            )
        if "results_by_query" not in data:
            grouped: dict = {}
            for r in data.get("results", []):
                grouped.setdefault(r["query"], []).append(r)
            data["results_by_query"] = [{"query": q, "answers": answers} for q, answers in grouped.items()]
        return data

    @staticmethod
    def from_report(business_id: int, report: dict) -> "CheckRun":
        return CheckRun(
            business_id=business_id,
            visibility_score=report["visibility_score"],
            mention_rate=report["mention_rate"],
            avg_position=report["avg_position"],
            report_json=json.dumps(report),
        )


class AnonymousReport(db.Model):
    """A finished anonymous (no-login) visibility-check report, stored just
    long enough to make its /check/<id> link shareable and refresh-safe.

    This lives in the same database as everything else -- shared disk
    storage on the one instance -- specifically so it survives running
    behind more than one Gunicorn worker process. An earlier in-memory
    version (report_cache.py) stored these in a plain per-process dict,
    which meant the POST that computed a report and the GET that later
    rendered its link could land on two different worker processes, and the
    second one had never heard of that report id -- showing "report expired"
    on every single check once the app ran with more than one worker."""
    __tablename__ = "anonymous_report"
    id = db.Column(db.String(32), primary_key=True)
    category = db.Column(db.String(255))
    location = db.Column(db.String(255))
    report_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


def add_missing_columns() -> None:
    """Tiny forward-only migration for columns added after a database was
    first created (db.create_all() never alters existing tables). Safe to
    run on every start, on SQLite and Postgres."""
    from sqlalchemy import inspect, text
    wanted = {
        "user": [("plan", "VARCHAR(20) DEFAULT 'starter'")],
        "business": [("custom_questions", "TEXT DEFAULT ''"), ("competitor_meta", "TEXT DEFAULT '{}'"), ("website", "VARCHAR(500) DEFAULT ''")],
    }
    insp = inspect(db.engine)
    pg = db.engine.dialect.name == "postgresql"
    for table, cols in wanted.items():
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols:
            if name not in existing:
                quoted = f'"{table}"'  # "user" is a reserved word in Postgres
                guard = "IF NOT EXISTS " if pg else ""
                db.session.execute(text(f"ALTER TABLE {quoted} ADD COLUMN {guard}{name} {ddl}"))
    db.session.commit()


def init_schema() -> None:
    """create_all + forward migration, serialised across processes: two
    Gunicorn workers booting at once on Postgres would otherwise race on
    CREATE TABLE / ALTER TABLE and crash the deploy."""
    from locks import exclusive
    with exclusive(db, "schema-migration", wait=True):
        db.create_all()
        add_missing_columns()
