"""
Storage for anonymous (no-login) visibility-check reports, so a report has
its own shareable, refresh-safe link (GET /check/<id>) instead of only
existing as the response to the POST /check form submit.

Backed by the app's own database (`AnonymousReport` in models.py) rather
than an in-process dict. That matters specifically because a real deployment
runs more than one Gunicorn worker process: an in-memory cache lives inside
one worker's memory, so the POST /check that computes a report can land on
worker A while the redirected GET /check/<id> lands on worker B -- which
never heard of that report id, and shows "report expired" on essentially
every check. The database is shared disk storage on the one instance, so
every worker process sees every saved report.
"""

from __future__ import annotations
import json
import secrets
from datetime import datetime, timedelta

_TTL = timedelta(hours=24)
_MAX_ROWS = 5000  # opportunistic cap so this table can't grow unbounded


def save(report: dict, **meta) -> str:
    from models import db, AnonymousReport
    _evict()
    report_id = secrets.token_hex(8)
    row = AnonymousReport(
        id=report_id,
        category=meta.get("category"),
        location=meta.get("location"),
        report_json=json.dumps(report),
    )
    db.session.add(row)
    db.session.commit()
    return report_id


def get(report_id: str) -> dict | None:
    from models import db, AnonymousReport
    row = db.session.get(AnonymousReport, report_id)
    if row is None:
        return None
    if datetime.utcnow() - row.created_at > _TTL:
        # Bulk delete: a concurrent request may already have removed it.
        db.session.query(AnonymousReport).filter_by(id=report_id).delete(synchronize_session=False)
        db.session.commit()
        return None
    return {
        "report": json.loads(row.report_json),
        "category": row.category,
        "location": row.location,
    }


def _evict() -> None:
    """Best-effort cleanup, run on every save rather than on a separate
    schedule -- cheap enough (indexed column, small rows) and means no extra
    cron/scheduler entry is needed just to keep this table tidy."""
    from models import db, AnonymousReport
    cutoff = datetime.utcnow() - _TTL
    db.session.query(AnonymousReport).filter(AnonymousReport.created_at < cutoff).delete()
    total = db.session.query(AnonymousReport).count()
    if total > _MAX_ROWS:
        overflow = total - _MAX_ROWS
        stale_ids = [
            r.id for r in
            db.session.query(AnonymousReport.id)
            .order_by(AnonymousReport.created_at.asc())
            .limit(overflow)
        ]
        if stale_ids:
            db.session.query(AnonymousReport).filter(AnonymousReport.id.in_(stale_ids)).delete(synchronize_session=False)
    db.session.commit()
