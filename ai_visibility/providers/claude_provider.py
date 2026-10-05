from .base import BaseProvider, NotConfiguredError, http_error, make_source, dedupe_sources, post_json, require_answer


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
        resp = post_json(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            body={
                "model": self.model(),
                "max_tokens": 1400,
                "messages": [{"role": "user", "content": query}],
                # Live web search, like Claude.ai does for "best X near me" questions.
                "tools": [tool],
            },
            provider="Claude", context=context,
        )
        if resp.status_code != 200:
            raise http_error(resp, "Claude")
        data = resp.json()
        stop = data.get("stop_reason")
        if stop in ("refusal", "pause_turn"):
            # pause_turn = stopped mid-search; what we have is only a preamble.
            raise RuntimeError(f"Claude didn't finish answering (stop_reason: {stop})")
        text, sources = [], []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text.append(block.get("text", ""))
                for c in block.get("citations") or []:
                    sources.append(make_source(c.get("url"), c.get("title")))
            elif block.get("type") == "web_search_tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    for r in content:
                        sources.append(make_source(r.get("url"), r.get("title")))
        answer = "".join(text)
        if stop == "max_tokens" and len(answer.strip()) < 200:
            raise RuntimeError("Claude ran out of room before answering (max_tokens)")
        return {"text": require_answer(answer, "Claude", f"stop_reason: {stop}"), "sources": dedupe_sources(sources)}
