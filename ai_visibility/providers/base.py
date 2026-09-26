"""
Common interface every AI-assistant provider implements.

Each provider knows how to:
  1. report whether it has a usable API key (`is_configured`)
  2. send one natural-language question and return the raw text answer (`ask`)

If a provider isn't configured, the pipeline falls back to a clearly-labeled
demo answer instead of crashing -- so the whole app is runnable today, and
starts returning real results the moment a key is added to .env.
"""

from __future__ import annotations
import os


class NotConfiguredError(Exception):
    """Raised when a provider is asked to answer but has no API key set."""


class BaseProvider:
    name = "base"
    display_name = "Base"
    env_var = "NONE_API_KEY"

    def api_key(self) -> str | None:
        return os.environ.get(self.env_var, "").strip() or None

    def is_configured(self) -> bool:
        return self.api_key() is not None

    def ask(self, query: str) -> str:
        """Send `query` to the assistant and return its raw text answer.

        Must raise NotConfiguredError if no key is present, and should raise
        a plain Exception with a short, human-readable message on any API
        failure (bad key, rate limit, network) so the pipeline can surface
        it instead of silently failing.
        """
        raise NotImplementedError
