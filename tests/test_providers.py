"""Provider calls: retries, deadlines, and empty answers treated as
failures (never as 'not mentioned')."""

import time
from unittest import mock

import pytest

from ai_visibility import pipeline
from ai_visibility.providers import base
from ai_visibility.providers.claude_provider import ClaudeProvider
from ai_visibility.providers.deepseek_provider import DeepSeekProvider
from ai_visibility.providers.gemini_provider import GeminiProvider
from ai_visibility.providers.openai_provider import OpenAIProvider
from ai_visibility.providers.perplexity_provider import PerplexityProvider


def resp(status=200, body=None, headers=None):
    r = mock.Mock(status_code=status, headers=headers or {}, text="")
    r.json.return_value = body if body is not None else {}
    return r


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setattr(base.time, "sleep", lambda s: None)


def post_returning(*responses):
    return mock.patch.object(base.requests, "post", side_effect=list(responses))


@pytest.mark.parametrize("provider,body", [
    (ClaudeProvider(), {"content": [{"type": "text", "text": "Let me search."}], "stop_reason": "pause_turn"}),
    (ClaudeProvider(), {"content": [], "stop_reason": "end_turn"}),
    (OpenAIProvider(), {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                        "output": [{"type": "reasoning"}]}),
    (DeepSeekProvider(), {"choices": [{"message": {"content": None}, "finish_reason": "length"}]}),
    (PerplexityProvider(), {"choices": [{"message": {"content": ""}}]}),
    (GeminiProvider(), {"candidates": [{"finishReason": "SAFETY"}]}),
])
def test_empty_or_cut_off_answers_are_errors_not_misses(provider, body):
    with post_returning(resp(200, body)):
        result = pipeline._run_one("best dentist in Ryde?", provider, "Ryde Dental", "dentist", "Ryde", [])
    assert result["error"] is True and result["mentioned"] is False


def test_successful_answer_is_parsed():
    body = {"content": [{"type": "text", "text": "1. **Ryde Dental** - great"}], "stop_reason": "end_turn"}
    with post_returning(resp(200, body)):
        r = pipeline._run_one("q", ClaudeProvider(), "Ryde Dental", "dentist", "Ryde", [])
    assert r["error"] is False and r["mentioned"] is True and r["position"] == 1


def test_rate_limit_is_retried():
    ok = {"choices": [{"message": {"content": "Try Ryde Dental."}}]}
    with post_returning(resp(429, {"error": {"message": "slow down"}}, {"retry-after": "1"}), resp(200, ok)) as p:
        out = PerplexityProvider().ask_full("q", {"deadline": time.monotonic() + 60})
    assert out["text"] == "Try Ryde Dental." and p.call_count == 2


def test_gives_up_after_max_retries():
    with post_returning(*[resp(503) for _ in range(5)]) as p:
        with pytest.raises(RuntimeError):
            DeepSeekProvider().ask_full("q", {"deadline": time.monotonic() + 60})
    assert p.call_count == base.MAX_RETRIES + 1


def test_no_call_after_the_deadline():
    with post_returning() as p:
        with pytest.raises(base.DeadlineExceeded):
            ClaudeProvider().ask_full("q", {"deadline": time.monotonic() - 1})
    assert p.call_count == 0


def test_error_text_is_scrubbed():
    msg = "Rate limit reached for org-AbCdEf123456 on requests; key sk-proj-XYZ123456789"
    err = base.http_error(resp(400, {"error": {"message": msg}}), "OpenAI")
    assert "org-AbCdEf123456" not in str(err) and "sk-proj" not in str(err)


def test_api_key_never_shown_in_report(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSECRET123456789")
    with mock.patch.object(GeminiProvider, "ask_full", side_effect=RuntimeError("bad url ?key=AIzaSECRET123456789")):
        r = pipeline._run_one("q", GeminiProvider(), "B", "cafe", "Sydney", [])
    assert "AIzaSECRET123456789" not in r["raw_text"]


def test_demo_answers_are_stable(monkeypatch):
    for k in ("ANTHROPIC_API_KEY",):
        monkeypatch.delenv(k)
    a = pipeline._run_one("best cafe in Ryde?", ClaudeProvider(), "Bean There", "cafe", "Ryde", [])
    b = pipeline._run_one("best cafe in Ryde?", ClaudeProvider(), "Bean There", "cafe", "Ryde", [])
    assert a["is_demo"] and a["raw_text"] == b["raw_text"]


def test_full_check_in_demo_mode(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(k)
    with mock.patch("places.geocode_location", return_value=None):
        rep = pipeline.run_visibility_check("Bean There", "cafe", "Ryde, NSW", ["Grind House"], num_queries=4)
    assert rep["any_demo_data"] and rep["visibility_score"] is not None
    assert len(rep["results"]) == 4 * 5
    assert rep["location_context"] is None  # the internal deadline never leaks into the report
