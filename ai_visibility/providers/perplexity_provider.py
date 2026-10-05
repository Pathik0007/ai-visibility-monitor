from .base import BaseProvider, NotConfiguredError, http_error, make_source, dedupe_sources, post_json, require_answer


class PerplexityProvider(BaseProvider):
    name = "perplexity"
    display_name = "Perplexity"
    env_var = "PERPLEXITY_API_KEY"
    model_env = "PERPLEXITY_MODEL"
    default_model = "sonar"
    uses_live_search = True

    def ask_full(self, query, context=None):
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        body = {"model": self.model(), "messages": [{"role": "user", "content": query}]}
        if context and context.get("country"):
            loc = {"country": context["country"]}
            if context.get("lat") is not None and context.get("lon") is not None:
                loc.update(latitude=context["lat"], longitude=context["lon"])
            if context.get("city"):
                loc["city"] = context["city"]
            if context.get("region"):
                loc["region"] = context["region"]
            body["web_search_options"] = {"user_location": loc}
        resp = post_json(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            body=body, provider="Perplexity", context=context,
        )
        if resp.status_code != 200:
            raise http_error(resp, "Perplexity")
        data = resp.json()
        sources = [make_source(r.get("url"), r.get("title")) for r in data.get("search_results") or [] if isinstance(r, dict)]
        sources += [make_source(u) for u in data.get("citations") or [] if isinstance(u, str)]
        text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        return {"text": require_answer(text, "Perplexity"), "sources": dedupe_sources(sources)}
