import requests
from .base import BaseProvider, NotConfiguredError


class OpenAIProvider(BaseProvider):
    name = "chatgpt"
    display_name = "ChatGPT"
    env_var = "OPENAI_API_KEY"

    def ask(self, query: str) -> str:
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 500,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
