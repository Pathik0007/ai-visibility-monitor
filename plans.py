"""
Subscription plans -- one place that defines what each tier gets, used by
billing, the dashboard, the business page, the scheduler and the pricing
page so they can never disagree.

Why Pro is worth $20 more (and costs more to run):
  - Google profile benchmark: live Google Maps rating, review count,
    category, website and weekend hours for you vs the businesses the
    assistants recommend -- this is what turns "you're behind" into "you
    have 86 reviews, they have 1,240". Uses paid Google data per check.
  - Your own questions: up to 5 custom prompts ("best gluten-free fish and
    chips in Ryde") on top of the standard ones.
  - More coverage: 10 questions per check instead of 6, twice-weekly
    re-checks instead of weekly, up to 3 businesses/locations, 10
    tracked competitors.
  - CSV export of every check for reporting.
"""

from __future__ import annotations

PLANS: dict[str, dict] = {
    "starter": {
        "key": "starter", "name": "Starter", "price": 29,
        "businesses": 1, "questions": 6, "custom_questions": 0, "competitors": 5,
        "check_every_days": 7, "cadence": "Weekly",
        "profile_benchmark": False, "csv_export": False,
    },
    "pro": {
        "key": "pro", "name": "Pro", "price": 49,
        "businesses": 3, "questions": 10, "custom_questions": 5, "competitors": 10,
        "check_every_days": 3.5, "cadence": "Twice a week",
        "profile_benchmark": True, "csv_export": True,
    },
}

FREE_CHECK = {"questions_options": [4, 6], "competitors": 5}


def plan_for(user) -> dict | None:
    if not user or not getattr(user, "is_subscribed", False):
        return None
    return PLANS.get(getattr(user, "plan", None) or "starter", PLANS["starter"])


def valid_plan(key: str | None) -> str:
    return key if key in PLANS else "starter"
