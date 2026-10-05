"""Scheduled re-checks: run once across processes, respect plan limits,
and one failing business doesn't stop the rest."""

from unittest import mock

import alerts
from locks import exclusive
from models import Business


def _biz(db, user, n):
    for i in range(n):
        db.session.add(Business(user_id=user.id, name=f"Biz {i}", category="cafe", location="Ryde"))
    db.session.commit()


def test_downgraded_user_only_gets_plan_limit_checked(app, db, make_user):
    u = make_user(status="active", plan="starter")
    _biz(db, u, 3)  # left over from Pro
    with mock.patch.object(alerts, "check_business_and_alert") as check:
        alerts.run_weekly_checks(app)
    assert check.call_count == 1


def test_second_runner_skips_while_first_holds_the_lock(app, db, make_user):
    u = make_user(status="active", plan="pro")
    _biz(db, u, 2)
    with mock.patch.object(alerts, "check_business_and_alert") as check:
        with exclusive(db, "scheduled-checks") as got:
            assert got
            alerts.run_weekly_checks(app)  # e.g. the other Gunicorn worker
        assert check.call_count == 0


def test_one_failure_does_not_stop_the_run(app, db, make_user):
    u = make_user(status="active", plan="pro")
    _biz(db, u, 3)
    calls = []

    def flaky(business):
        calls.append(business.id)
        if len(calls) == 1:
            raise RuntimeError("provider outage")
    with mock.patch.object(alerts, "check_business_and_alert", side_effect=flaky):
        alerts.run_weekly_checks(app)
    assert len(calls) == 3


def test_unsubscribed_users_are_not_checked(app, db, make_user):
    _biz(db, make_user(status="inactive"), 1)
    with mock.patch.object(alerts, "check_business_and_alert") as check:
        alerts.run_weekly_checks(app)
    assert check.call_count == 0
