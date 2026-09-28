"""
The reusable core: business+competitors in, a full visibility report out.
Used by both the anonymous quick-check page and the saved-business weekly job.

Provider calls are network I/O (each with its own timeout), so they run
concurrently across a thread pool rather than one at a time -- with 4
providers x up to 10 queries, sequential calls could take 40+ x a few
seconds each; in parallel, wall-clock time is roughly bounded by the
slowest single call instead of the sum of all of them.
"""

from __future__ import annotations
import os
from concurrent.futures import ThreadPoolExecutor
from .query_generator import generate_queries
from .providers import ALL_PROVIDERS
from .providers.base import NotConfiguredError
from .analyzer import analyze_answer
from .report import build_report
from .demo_mode import generate_mock_answer

MAX_WORKERS = 8

_SECRET_ENV_MARKERS = ("_API_KEY", "_SECRET", "_TOKEN", "_KEY")


def _redact_secrets(text: str) -> str:
    """Defense in depth: strip any configured API key/secret value out of an
    error message before it's ever shown to a user. The Gemini provider used
    to put its key in the request URL, which meant a failed call's error
    text (surfaced directly on the public report page) could leak it --
    fixed at the source by moving the key to a header, but a provider's own
    error string, a proxy, or a future provider could still echo a secret
    back verbatim, so every configured secret is scrubbed here too."""
    for name, value in os.environ.items():
        if value and len(value) >= 6 and any(name.endswith(m) for m in _SECRET_ENV_MARKERS):
            if value in text:
                text = text.replace(value, "[redacted]")
    return text


def _run_one(query: str, provider, business: str, category: str, location: str,
             competitors: list[str]) -> dict:
    seed = hash((business, provider.name, query)) & 0xFFFFFFFF
    is_demo = not provider.is_configured()

    if is_demo:
        raw_text = generate_mock_answer(query, business, category, location, competitors, seed)
    else:
        try:
            raw_text = provider.ask(query)
        except NotConfiguredError:
            is_demo = True
            raw_text = generate_mock_answer(query, business, category, location, competitors, seed)
        except Exception as exc:
            safe_message = _redact_secrets(str(exc))
            return {
                "provider": provider.display_name, "query": query,
                "mentioned": False, "position": None,
                "competitors_mentioned": [], "raw_text": f"[Error calling {provider.display_name}: {safe_message}]",
                "is_demo": is_demo, "error": True,
            }

    analysis = analyze_answer(raw_text, business, competitors)
    return {
        "provider": provider.display_name,
        "query": query,
        "is_demo": is_demo,
        "error": False,
        **analysis,
    }


def run_visibility_check(business: str, category: str, location: str,
                          competitors: list[str], num_queries: int = 6) -> dict:
    queries = generate_queries(business, category, location, count=num_queries)
    tasks = [(query, provider) for query in queries for provider in ALL_PROVIDERS]

    if not tasks:
        return build_report(business, category, competitors, [])

    results_by_index: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tasks))) as executor:
        futures = {
            executor.submit(_run_one, query, provider, business, category, location, competitors): i
            for i, (query, provider) in enumerate(tasks)
        }
        for future in futures:
            results_by_index[futures[future]] = future.result()

    results = [results_by_index[i] for i in range(len(tasks))]
    return build_report(business, category, competitors, results)
