import requests
from .base import BaseProvider, NotConfiguredError


class GeminiProvider(BaseProvider):
    name = "gemini"
    display_name = "Gemini"
    env_var = "GOOGLE_API_KEY"

    def ask(self, query: str) -> str:
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={key}",
            headers={"content-type": "application/json"},
            json={"contents": [{"parts": [{"text": query}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
