"""
Standalone entrypoint for the weekly visibility check, meant to be invoked
by the HOST's own scheduler (Render/Railway Cron Job, Heroku Scheduler, a
plain system crontab, a GitHub Actions schedule -- whatever you deploy
with) rather than by an in-process APScheduler.

Why this exists instead of just letting app.py's scheduler handle it: once
you run more than one web worker process (which any real traffic needs),
an in-process scheduler runs once per worker -- so every business gets
checked, and its owner emailed, multiple times over. Running this as one
separate, single-shot job avoids that entirely.

Usage:
    python scheduled_job.py

Set up to run weekly, e.g. a crontab entry:
    0 3 * * 1  cd /path/to/app && /path/to/venv/bin/python scheduled_job.py

If you deploy with ENABLE_INPROCESS_SCHEDULER=1 (the default) and only ever
run a single process, you don't need this at all -- it's the multi-worker
alternative, not an addition on top.
"""

import sys
import os

# This script IS the scheduled run -- never let importing app.py also spin
# up its own in-process scheduler alongside it.
os.environ["ENABLE_INPROCESS_SCHEDULER"] = "0"

from app import app
from alerts import run_weekly_checks

if __name__ == "__main__":
    print("Running scheduled visibility checks for all saved businesses...")
    try:
        run_weekly_checks(app)
        print("Done.")
    except Exception as exc:
        print(f"Scheduled run failed: {exc}", file=sys.stderr)
        sys.exit(1)
