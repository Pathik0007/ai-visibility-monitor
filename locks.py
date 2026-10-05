"""
Cross-process locks, so work that must happen exactly once (schema
migrations at boot, the scheduled re-check run) stays correct when the app
runs as several Gunicorn workers or alongside a separate cron process.

Postgres -> session-level advisory locks (shared by every process using the
same database). SQLite / local dev -> an OS file lock next to the database,
which covers every process on the one machine that can see that file.
"""

from __future__ import annotations

import os
import tempfile
import zlib
from contextlib import contextmanager
import logging

log = logging.getLogger(__name__)

try:  # POSIX only; on Windows dev boxes we simply run unlocked
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


_NAMESPACE = 41_731  # first half of the two-int advisory-lock key: "this app"


def _key(name: str) -> int:
    return zlib.crc32(name.encode()) & 0x7FFFFFFF


@contextmanager
def exclusive(db, name: str, wait: bool = False):
    """Yields True when this process holds the lock `name`, False when another
    process already holds it (only possible with wait=False)."""
    engine = db.engine
    if engine.dialect.name == "postgresql":
        from sqlalchemy import text
        with engine.connect() as conn:
            if wait:
                conn.execute(text("SELECT pg_advisory_lock(:ns, :k)"), {"ns": _NAMESPACE, "k": _key(name)})
                got = True
            else:
                got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:ns, :k)"), {"ns": _NAMESPACE, "k": _key(name)}).scalar())
            conn.commit()
            try:
                yield got
            finally:
                if got:
                    try:  # never let a failed unlock hide the real error
                        conn.execute(text("SELECT pg_advisory_unlock(:ns, :k)"), {"ns": _NAMESPACE, "k": _key(name)})
                        conn.commit()
                    except Exception:
                        log.exception("advisory unlock failed for %s (released when the connection closes)", name)
        return

    if fcntl is None:
        yield True
        return
    path = os.path.join(tempfile.gettempdir(), f"avm-{_key(str(engine.url) + name)}.lock")
    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
        except OSError:
            got = False
        try:
            yield got
        finally:
            if got:
                fcntl.flock(fh, fcntl.LOCK_UN)
