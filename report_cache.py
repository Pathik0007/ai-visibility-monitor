"""
Short-lived in-memory cache for anonymous visibility-check reports.

Previously /check rendered report.html directly from the POST handler --
refreshing the page re-submitted the form (running the whole check again,
against real paid APIs once configured) and the URL couldn't be bookmarked
or shared. Instead /check computes the report once, stores it here under a
random id, and redirects (303) to GET /check/<id> -- the standard
POST/redirect/GET pattern, so the report page is refresh-safe and shareable.

In-memory and TTL-bound, the same pattern as places.py's lookup cache: fine
for a single process. With more than one Gunicorn worker, a request can
land on a worker that never computed a given report id -- if you need a
shareable link that reliably survives that, swap this for Redis (see the
"Going live" note in README, next to the same caveat for rate limiting).
"""

from __future__ import annotations
import time
import uuid

_TTL_SECONDS = 60 * 60 * 24  # a day is plenty for "hey, check this out"
_MAX_ENTRIES = 500

_store: dict[str, tuple[float, dict]] = {}


def _evict() -> None:
    now = time.time()
    for k in [k for k, (ts, _) in _store.items() if now - ts > _TTL_SECONDS]:
        _store.pop(k, None)
    if len(_store) > _MAX_ENTRIES:
        oldest = sorted(_store.items(), key=lambda kv: kv[1][0])[: len(_store) - _MAX_ENTRIES]
        for k, _ in oldest:
            _store.pop(k, None)


def save(report: dict, **meta) -> str:
    _evict()
    report_id = uuid.uuid4().hex[:16]
    _store[report_id] = (time.time(), {"report": report, **meta})
    return report_id


def get(report_id: str) -> dict | None:
    entry = _store.get(report_id)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _TTL_SECONDS:
        _store.pop(report_id, None)
        return None
    return data
