from .base import BaseProvider, NotConfiguredError, http_error, make_source, dedupe_sources, post_json, remaining


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
        # Grounded in Google Search *and* Google Maps (Business Profile data),
        # the way the Gemini app answers local questions. Maps grounding can
        # be combined with Search on Gemini 3.5 Flash and later; if a model
        # or key rejects it, retry with Search only rather than failing.
        body = {"contents": [{"parts": [{"text": query}]}],
                "tools": [{"google_search": {}}, {"googleMaps": {}}]}
        if context and context.get("lat") is not None and context.get("lon") is not None:
            body["toolConfig"] = {"retrievalConfig": {"latLng": {"latitude": context["lat"], "longitude": context["lon"]}}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model()}:generateContent"
        # Key in a header, never the URL (URLs end up in error text/logs).
        headers = {"content-type": "application/json", "x-goog-api-key": key}
        resp = post_json(url, headers=headers, body=body, provider="Gemini", context=context)
        if resp.status_code == 400 and remaining(context) > 15:
            body.pop("toolConfig", None)
            body["tools"] = [{"google_search": {}}]
            resp = post_json(url, headers=headers, body=body, provider="Gemini", context=context)
        if resp.status_code != 200:
            raise http_error(resp, "Gemini")
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        if not text.strip():
            raise RuntimeError(f"Gemini returned no text (finishReason: {cand.get('finishReason', 'unknown')})")
        sources = []
        for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
            place = chunk.get("maps")
            if place:
                sources.append(make_source(place.get("uri"), place.get("title", ""), domain="google maps"))
                continue
            web = chunk.get("web") or {}
            # Gemini's uri is a Google redirect; its title is the site's domain.
            title = web.get("title", "")
            sources.append(make_source(web.get("uri"), title, domain=title if "." in title else None))
        return {"text": text, "sources": dedupe_sources(sources)}
