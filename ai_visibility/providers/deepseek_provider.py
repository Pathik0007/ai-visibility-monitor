from .base import BaseProvider, NotConfiguredError, http_error, post_json, require_answer


class DeepSeekProvider(BaseProvider):
    """No web search in DeepSeek's API -- answers come from training data,
    which is also how the DeepSeek app answers by default."""
    name = "deepseek"
    display_name = "DeepSeek"
    env_var = "DEEPSEEK_API_KEY"
    model_env = "DEEPSEEK_MODEL"
    # "deepseek-chat" was retired; "deepseek-flash" is the current general model.
    default_model = "deepseek-flash"
    uses_live_search = False

    def ask_full(self, query, context=None):
        key = self.api_key()
        if not key:
            raise NotConfiguredError()
        resp = post_json(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            body={"model": self.model(), "messages": [{"role": "user", "content": query}], "max_tokens": 1000},
            provider="DeepSeek", context=context,
        )
        if resp.status_code != 200:
            raise http_error(resp, "DeepSeek")
        choice = (resp.json().get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        return {"text": require_answer(text, "DeepSeek", f"finish_reason: {choice.get('finish_reason')}"), "sources": []}
