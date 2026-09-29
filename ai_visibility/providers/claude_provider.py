import requests
from .base import BaseProvider, NotConfiguredError, PROVIDER_TIMEOUT, http_error, make_source, dedupe_sources


class ClaudeProvider(BaseProvider):
    name = "claude"
    display_name = "Claude"
    env_var = "ANTHROPIC_API_KEY"
    model_env = "CLAUDE_MODEL"
    default_model = "claude-sonnet-4-6"
    uses_live_search = True

    def ask_full(self, query, context=None):
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
        if context and context.get("country"):
            tool["user_location"] = {"type": "approximate", "country": context["country"],
                                     **({"city": context["city"]} if context.get("city") else {}),
                                     **({"region": context["region"]} if context.get("region") else {})}
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": self.model(),
                "max_tokens": 900,
                "messages": [{"role": "user", "content": query}],
                # Live web search, like Claude.ai does for "best X near me" questions.
                "tools": [tool],
            },
            timeout=PROVIDER_TIMEOUT,
        )
        if resp.status_code != 200:
            raise http_error(resp, "Claude")
        text, sources = [], []
        for block in resp.json().get("content", []):
            if block.get("type") == "text":
                text.append(block.get("text", ""))
                for c in block.get("citations") or []:
                    sources.append(make_source(c.get("url"), c.get("title")))
            elif block.get("type") == "web_search_tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    for r in content:
                        sources.append(make_source(r.get("url"), r.get("title")))
        return {"text": "".join(text), "sources": dedupe_sources(sources)}
