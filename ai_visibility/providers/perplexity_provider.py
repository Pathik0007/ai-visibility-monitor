import requests
from .base import BaseProvider, NotConfiguredError, PROVIDER_TIMEOUT, http_error, make_source, dedupe_sources


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
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json=body,
            timeout=PROVIDER_TIMEOUT,
        )
        if resp.status_code != 200:
            raise http_error(resp, "Perplexity")
        data = resp.json()
        sources = [make_source(r.get("url"), r.get("title")) for r in data.get("search_results") or []]
        sources += [make_source(u) for u in data.get("citations") or [] if isinstance(u, str)]
        return {"text": data["choices"][0]["message"]["content"], "sources": dedupe_sources(sources)}
