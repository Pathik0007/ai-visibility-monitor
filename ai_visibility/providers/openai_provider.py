from .base import BaseProvider, NotConfiguredError, http_error, make_source, dedupe_sources, post_json, require_answer


class OpenAIProvider(BaseProvider):
    """Uses the Responses API with the web_search tool -- plain Chat
    Completions answers only from training data, which is not how ChatGPT
    answers "best X near me" for a real user today."""
    name = "chatgpt"
    display_name = "ChatGPT"
    env_var = "OPENAI_API_KEY"
    model_env = "OPENAI_MODEL"
    default_model = "gpt-5.4-mini"
    uses_live_search = True

    def ask_full(self, query, context=None):
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        tool = {"type": "web_search"}
        if context and context.get("country"):
            tool["user_location"] = {"type": "approximate", "country": context["country"],
                                     **({"city": context["city"]} if context.get("city") else {}),
                                     **({"region": context["region"]} if context.get("region") else {})}
        resp = post_json(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            body={
                "model": self.model(),
                "input": query,
                "tools": [tool],
                "include": ["web_search_call.action.sources"],
                # Reasoning tokens count against this too; too low and the
                # model stops (status "incomplete") before writing an answer.
                "max_output_tokens": 2500,
            },
            provider="OpenAI", context=context,
        )
        if resp.status_code != 200:
            raise http_error(resp, "OpenAI")
        data = resp.json()
        text, cited, consulted = [], [], []
        for item in data.get("output") or []:
            if item.get("type") == "message":
                for c in item.get("content") or []:
                    if c.get("type") == "output_text":
                        text.append(c.get("text", ""))
                        for a in c.get("annotations") or []:
                            if a.get("type") == "url_citation":
                                cited.append(make_source(a.get("url"), a.get("title")))
            elif item.get("type") == "web_search_call":
                for s in ((item.get("action") or {}).get("sources") or []):
                    consulted.append(make_source(s.get("url"), s.get("title", "")))
        # Cited-in-the-answer sources first; then other pages it read.
        why = ""
        if data.get("status") == "incomplete":
            why = "incomplete: " + str((data.get("incomplete_details") or {}).get("reason", "unknown"))
        return {"text": require_answer("".join(text), "ChatGPT", why), "sources": dedupe_sources(cited + consulted)}
