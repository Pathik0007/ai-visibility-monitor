"""
Common interface every AI-assistant provider implements.

Each provider knows how to:
  1. report whether it has a usable API key (`is_configured`)
  2. answer one natural-language question (`ask_full`), returning the text
     plus any web sources it cited -- the sources are what turns a report
     from "you weren't mentioned" into "these are the pages the assistant
     actually read; get onto them".

`context` (optional) describes where the imaginary customer is asking from
-- {"country": "AU", "city": "North Ryde", "region": "New South Wales",
"lat": ..., "lon": ...} -- so assistants with live search localise the way
they would for a real person in that area.

Model IDs are read from env vars with current defaults, because providers
retire models regularly (gemini-2.0-flash was shut down in June 2026;
DeepSeek retired "deepseek-chat") and a hard-coded retired model silently
turns every live answer into an error.
"""

from __future__ import annotations
import logging
import math
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

PROVIDER_TIMEOUT = int(os.environ.get("PROVIDER_TIMEOUT", "45"))  # live web search can take a while
# At most this many requests in flight per provider (per process): a Pro
# check asks 10+ questions at once, and firing them all together trips
# per-minute rate limits on new/low-tier API keys.
PROVIDER_CONCURRENCY = int(os.environ.get("PROVIDER_CONCURRENCY", "6"))
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}
MAX_RETRIES = 2

log = logging.getLogger(__name__)
_semaphores: dict[str, threading.BoundedSemaphore] = {}
_sem_lock = threading.Lock()


def _semaphore(name: str) -> threading.BoundedSemaphore:
    with _sem_lock:
        if name not in _semaphores:
            _semaphores[name] = threading.BoundedSemaphore(PROVIDER_CONCURRENCY)
        return _semaphores[name]


def remaining(context: dict | None) -> float:
    """Seconds left before the whole check's deadline (pipeline sets
    context["deadline"] as a time.monotonic() value)."""
    deadline = (context or {}).get("deadline")
    return PROVIDER_TIMEOUT if deadline is None else deadline - time.monotonic()


class DeadlineExceeded(RuntimeError):
    pass


class NotConfiguredError(Exception):
    """Raised when a provider is asked to answer but has no API key set."""


_FRIENDLY = {
    400: "request rejected", 401: "API key rejected", 403: "API key not allowed",
    404: "model not found -- check the model setting", 429: "rate limited or out of credits",
}
# Provider messages can name your organisation/project or echo part of a key.
_SCRUB_RE = re.compile(r"\b(org|proj|sk|key|acct)[-_][A-Za-z0-9_-]{6,}\b|AIza[0-9A-Za-z_-]{20,}", re.I)


def scrub(text: str) -> str:
    return _SCRUB_RE.sub("[redacted]", text or "")


def http_error(resp, provider: str) -> Exception:
    """A short, readable error for the report (shown publicly, so scrubbed),
    with the provider's full message logged server-side."""
    detail = ""
    try:
        data = resp.json()
        err = data.get("error", data) if isinstance(data, dict) else data
        detail = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:
        detail = (resp.text or "")[:300]
    detail = (detail or "").strip()
    log.warning("%s API error %s: %s", provider, resp.status_code, scrub(detail)[:500])
    friendly = _FRIENDLY.get(resp.status_code) or ("provider outage" if resp.status_code >= 500 else "error")
    shown = scrub(detail)[:160] if resp.status_code in (400, 404) else ""
    return RuntimeError(f"{provider} API {resp.status_code} ({friendly})" + (f": {shown}" if shown else ""))


def post_json(url: str, *, headers: dict, body: dict, provider: str, context: dict | None = None):
    """POST with a per-provider concurrency cap, retries with backoff on
    429/5xx (honouring Retry-After), and every wait bounded by the check's
    overall deadline. Returns the final requests.Response."""
    sem = _semaphore(provider)
    attempt = 0
    while True:
        left = remaining(context)
        if left < 3:
            raise DeadlineExceeded(f"{provider}: no time left before the check's deadline")
        if not sem.acquire(timeout=max(0.1, left - 3)):
            raise DeadlineExceeded(f"{provider}: queued too long (rate-limit protection)")
        try:
            left = remaining(context)
            resp = requests.post(url, headers=headers, json=body,
                                 timeout=(min(10, max(1, left)), max(1, min(PROVIDER_TIMEOUT, left - 1))))
        finally:
            sem.release()
        if resp.status_code not in RETRY_STATUSES or attempt >= MAX_RETRIES:
            return resp
        attempt += 1
        try:
            wait = float(resp.headers.get("retry-after", ""))
            if not math.isfinite(wait):
                raise ValueError
        except ValueError:
            wait = 1.5 * (2 ** (attempt - 1))
        wait = min(max(wait, 0.5), 8)
        if remaining(context) - wait < 8:
            return resp  # not enough time for a meaningful retry
        time.sleep(wait)


def require_answer(text: str, provider: str, why: str = "") -> str:
    """An empty/cut-off answer is a failed call, not "you weren't mentioned"
    -- counting it as a miss would wrongly lower the score."""
    if not (text or "").strip():
        raise RuntimeError(f"{provider} returned no answer" + (f" ({why})" if why else ""))
    return text


def make_source(url: str, title: str = "", domain: str | None = None) -> dict | None:
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return {"url": url, "title": (title or "").strip()[:200], "domain": (domain or host or "").lower()}


def dedupe_sources(sources: list, limit: int = 12) -> list[dict]:
    seen, out = set(), []
    for s in sources:
        if not s or s["url"] in seen:
            continue
        seen.add(s["url"])
        out.append(s)
        if len(out) >= limit:
            break
    return out


class BaseProvider:
    name = "base"
    display_name = "Base"
    env_var = "NONE_API_KEY"
    model_env = "NONE_MODEL"
    default_model = ""
    uses_live_search = False

    def api_key(self) -> str | None:
        return os.environ.get(self.env_var, "").strip() or None

    def model(self) -> str:
        return os.environ.get(self.model_env, "").strip() or self.default_model

    def is_configured(self) -> bool:
        return self.api_key() is not None

    def ask_full(self, query: str, context: dict | None = None) -> dict:
        """Returns {"text": str, "sources": [{"url", "title", "domain"}]}.
        Must raise NotConfiguredError with no key, and a plain Exception with
        a short readable message on any API failure."""
        raise NotImplementedError

    def ask(self, query: str, context: dict | None = None) -> str:
        return self.ask_full(query, context)["text"]
