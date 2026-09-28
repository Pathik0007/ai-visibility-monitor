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
        # The key travels in a header, not the URL -- a URL ends up in
        # requests.HTTPError's string form (and in some error/proxy logs),
        # so putting the key in the query string risked it leaking into
        # publicly-displayed report error text on a failed call.
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.0-flash:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": key,
            },
            json={
                "contents": [{"parts": [{"text": query}]}],
                # Ground answers in live Google Search results rather than
                # training data alone -- closer to how Gemini actually
                # answers "best X near me" style questions in production.
                "tools": [{"google_search": {}}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
