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
import os
from urllib.parse import urlparse

PROVIDER_TIMEOUT = int(os.environ.get("PROVIDER_TIMEOUT", "45"))  # live web search can take a while


class NotConfiguredError(Exception):
    """Raised when a provider is asked to answer but has no API key set."""


def http_error(resp, provider: str) -> Exception:
    """A short, readable error that includes the provider's own message
    (e.g. "model not found") instead of a bare status code."""
    detail = ""
    try:
        data = resp.json()
        err = data.get("error", data)
        detail = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:
        detail = (resp.text or "")[:200]
    return RuntimeError(f"{provider} API error {resp.status_code}: {(detail or '').strip()[:300]}")


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
