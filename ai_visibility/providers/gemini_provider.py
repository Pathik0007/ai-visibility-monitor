import requests
from .base import BaseProvider, NotConfiguredError, PROVIDER_TIMEOUT, http_error, make_source, dedupe_sources


class GeminiProvider(BaseProvider):
    name = "gemini"
    display_name = "Gemini"
    env_var = "GOOGLE_API_KEY"
    model_env = "GEMINI_MODEL"
    # gemini-2.0-flash (used before) was shut down on 1 June 2026.
    default_model = "gemini-3.5-flash"
    uses_live_search = True

    def ask_full(self, query, context=None):
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        # Key in a header, never the URL (URLs end up in error text/logs).
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model()}:generateContent",
            headers={"content-type": "application/json", "x-goog-api-key": key},
            json={
                "contents": [{"parts": [{"text": query}]}],
                # Grounded in live Google Search, like the Gemini app.
                "tools": [{"google_search": {}}],
            },
            timeout=PROVIDER_TIMEOUT,
        )
        if resp.status_code != 200:
            raise http_error(resp, "Gemini")
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            raise RuntimeError(f"Gemini returned no text (finishReason: {cand.get('finishReason', 'unknown')})")
        sources = []
        for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
            web = chunk.get("web") or {}
            # Gemini's uri is a Google redirect; its title is the site's domain.
            title = web.get("title", "")
            sources.append(make_source(web.get("uri"), title, domain=title if "." in title else None))
        return {"text": text, "sources": dedupe_sources(sources)}
