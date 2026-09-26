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

    businesses = db.relationship("Business", backref="owner", cascade="all, delete-orphan")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_subscribed(self) -> bool:
        return self.subscription_status in ("active", "demo")


class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    competitors = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    runs = db.relationship(
        "CheckRun", backref="business",
        cascade="all, delete-orphan",
        order_by="CheckRun.created_at",
    )

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
        return json.loads(self.report_json)

    @staticmethod
    def from_report(business_id: int, report: dict) -> "CheckRun":
        return CheckRun(
            business_id=business_id,
            visibility_score=report["visibility_score"],
            mention_rate=report["mention_rate"],
            avg_position=report["avg_position"],
            report_json=json.dumps(report),
        )
