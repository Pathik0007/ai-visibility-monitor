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
from concurrent.futures import ThreadPoolExecutor, wait
from .query_generator import generate_queries_with_themes
from .providers import ALL_PROVIDERS
from .providers.base import NotConfiguredError
from .analyzer import analyze_answer
from .report import build_report
from .demo_mode import generate_mock_answer

MAX_WORKERS = 40
OVERALL_TIMEOUT = int(os.environ.get("CHECK_TIMEOUT", "80"))  # seconds, whole check

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


def _error_result(provider, query: str, message: str, is_demo: bool = False) -> dict:
    return {
        "provider": provider.display_name, "query": query,
        "mentioned": False, "position": None, "competitors_mentioned": [],
        "raw_text": f"[Error calling {provider.display_name}: {message}]",
        "is_demo": is_demo, "error": True, "sources": [],
    }


def _run_one(query: str, provider, business: str, category: str, location: str,
             competitors: list[str], context: dict | None = None) -> dict:
    seed = hash((business, provider.name, query)) & 0xFFFFFFFF
    is_demo = not provider.is_configured()
    sources: list[dict] = []

    if is_demo:
        raw_text = generate_mock_answer(query, business, category, location, competitors, seed)
    else:
        try:
            answer = provider.ask_full(query, context)
            raw_text, sources = answer["text"], answer.get("sources") or []
        except NotConfiguredError:
            is_demo = True
            raw_text = generate_mock_answer(query, business, category, location, competitors, seed)
        except Exception as exc:
            return _error_result(provider, query, _redact_secrets(str(exc)))

    analysis = analyze_answer(raw_text, business, competitors)
    return {
        "provider": provider.display_name,
        "query": query,
        "is_demo": is_demo,
        "error": False,
        "sources": sources,
        "live_search": provider.uses_live_search and not is_demo,
        **analysis,
    }


def _location_context(location: str) -> dict | None:
    """Where the imaginary customer is asking from, so assistants with live
    search localise results the way they would for a real person there."""
    try:
        from places import geocode_location
        geo = geocode_location(location)
    except Exception:
        return None
    if not geo or not geo.get("country"):
        return None
    return {k: geo.get(k) for k in ("country", "city", "region", "lat", "lon")}


def run_visibility_check(business: str, category: str, location: str,
                          competitors: list[str], num_queries: int = 6,
                          extra_queries: list[str] | None = None,
                          profile_benchmark: bool = False,
                          website: str | None = None) -> dict:
    themed = generate_queries_with_themes(business, category, location, count=num_queries)
    themes = {q: t for q, t in themed}
    queries = [q for q, _ in themed]
    for q in extra_queries or []:
        q = " ".join(q.split())
        if q and q not in queries:
            queries.append(q)
            themes[q] = "custom"
    tasks = [(query, provider) for query in queries for provider in ALL_PROVIDERS]

    if not tasks:
        return build_report(business, category, competitors, [])

    context = _location_context(location)
    results: list[dict | None] = [None] * len(tasks)
    # Every call runs at once (they're network waits, not CPU), with one
    # overall deadline: live web-search answers can take 20-40s each, and
    # the old 8-thread pool queued them in rounds -- long enough for the
    # web server to kill the request before the report was ever shown.
    executor = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tasks)) + 1)
    website_future = None
    if website:
        from website_audit import audit_website
        website_future = executor.submit(audit_website, website, business, location, category)
    futures = {
        executor.submit(_run_one, query, provider, business, category, location, competitors, context): i
        for i, (query, provider) in enumerate(tasks)
    }
    done, _pending = wait(futures, timeout=OVERALL_TIMEOUT)
    for future, i in futures.items():
        query, provider = tasks[i]
        if future in done:
            try:
                results[i] = future.result()
            except Exception as exc:
                results[i] = _error_result(provider, query, _redact_secrets(str(exc)))
        else:
            results[i] = _error_result(provider, query, "timed out")
    website_report = None
    if website_future is not None:
        try:
            website_report = website_future.result(timeout=max(5, OVERALL_TIMEOUT // 4))
        except Exception:
            website_report = {"ok": False, "url": website, "error": "The website check didn't finish in time."}
    executor.shutdown(wait=False, cancel_futures=True)

    report = build_report(business, category, competitors, results)
    report["website"] = website_report
    report["location_context"] = context
    report["question_themes"] = themes
    if profile_benchmark:
        try:
            from places import profile_benchmark as _benchmark
            report["profiles"] = _benchmark(business, location, report.get("top_competitors") or [],
                                            competitors, context)
        except Exception as exc:
            report["profiles"] = {"error": str(exc)[:200]}
    return report
