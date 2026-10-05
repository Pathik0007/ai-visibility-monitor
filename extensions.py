"""
Shared Flask extension instances, created unbound here and wired to the app
with .init_app() in app.py. Keeping them in their own module (rather than
inside app.py) lets other modules -- like auth.py's login route -- import
and use them (e.g. to rate-limit) without a circular import on app.py.
"""

import os
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()

# In-memory storage (the default) only tracks limits within a single process.
# The Procfile therefore runs ONE Gunicorn worker with 8 threads (the work is
# I/O-bound: waiting on AI APIs), so every request shares the same counters.
# Before scaling to several workers or instances, set RATELIMIT_STORAGE_URI
# (e.g. a Render Key Value / Redis URL) so limits are shared.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)
