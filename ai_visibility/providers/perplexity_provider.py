import requests
from .base import BaseProvider, NotConfiguredError


class PerplexityProvider(BaseProvider):
    name = "perplexity"
    display_name = "Perplexity"
    env_var = "PERPLEXITY_API_KEY"

    def ask(self, query: str) -> str:
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
