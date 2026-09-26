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

# In-memory storage (the default) only tracks limits within a single process
# -- fine for one dev server, but with multiple Gunicorn workers in
# production each worker would count separately, letting real limits slip.
# Set RATELIMIT_STORAGE_URI (e.g. redis://localhost:6379) once you deploy
# with more than one worker process.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)
