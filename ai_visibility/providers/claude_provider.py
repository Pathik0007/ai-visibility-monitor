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
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))
