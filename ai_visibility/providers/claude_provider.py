import requests
from .base import BaseProvider, NotConfiguredError


class ClaudeProvider(BaseProvider):
    name = "claude"
    display_name = "Claude"
    env_var = "ANTHROPIC_API_KEY"

    def ask(self, query: str) -> str:
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": query}],
                # Let Claude search the live web for "best X near me" style
                # questions instead of answering purely from training data --
                # closer to how a real user's question gets answered, and
                # more likely to reflect a business's *current* visibility.
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
