import requests
from .base import BaseProvider, NotConfiguredError


class DeepSeekProvider(BaseProvider):
    name = "deepseek"
    display_name = "DeepSeek"
    env_var = "DEEPSEEK_API_KEY"

    def ask(self, query: str) -> str:
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        # DeepSeek exposes an OpenAI-compatible chat-completions API.
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 500,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
