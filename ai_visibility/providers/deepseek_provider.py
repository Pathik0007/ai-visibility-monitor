import requests
from .base import BaseProvider, NotConfiguredError, PROVIDER_TIMEOUT, http_error


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
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json={"model": self.model(), "messages": [{"role": "user", "content": query}], "max_tokens": 800},
            timeout=PROVIDER_TIMEOUT,
        )
        if resp.status_code != 200:
            raise http_error(resp, "DeepSeek")
        return {"text": resp.json()["choices"][0]["message"]["content"], "sources": []}
