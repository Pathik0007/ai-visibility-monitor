"""
Aggregates per-query, per-provider analysis results into the thing a
business owner actually reads: one score, a breakdown, and a fix list.
"""

from __future__ import annotations
from collections import Counter, OrderedDict
from .solutions import build_action_plan

FIX_LIBRARY = [
    {
        "trigger": "not_mentioned_majority",
        "text": "You weren't mentioned in most answers. AI assistants lean heavily "
                "on your Google Business Profile and recent reviews -- make sure "
                "both are complete and up to date (hours, services, service area).",
    },
    {
        "trigger": "competitor_dominant",
        "text": "{competitor} was recommended more than you across these questions. "
                "Check what they list that you don't (opening hours, specific "
                "services, response time) and match or beat it on your own profile.",
    },
    {
        "trigger": "weak_position",
        "text": "You're being mentioned, but usually near the bottom of the list. "
                "Encourage recent, detailed reviews that mention the specific "
                "services people search for -- assistants weight recency and "
                "specificity, not just star rating.",
    },
    {
        "trigger": "engine_gap",
        "text": "You show up on some assistants but not others ({engines}). "
                "That's usually a sign your info is inconsistent across the web "
                "(directory listings, website, socials) -- align your name, "
                "address and phone number everywhere.",
    },
]


def build_report(business: str, category: str, competitors: list[str], results: list[dict]) -> dict:
    """`results` is a flat list of dicts, each one query x provider run:
    {provider, query, mentioned, position, competitors_mentioned, is_demo, error, raw_text}

    Results with error=True (the provider call itself failed -- network,
    rate limit, bad key) are excluded from scoring entirely. Counting an API
    failure as "not mentioned" would silently deflate a business's score for
    a reason that has nothing to do with their actual visibility.
    """
    scoreable = [r for r in results if not r.get("error")]
    errored = [r for r in results if r.get("error")]

    total = len(scoreable)
    mentioned_results = [r for r in scoreable if r["mentioned"]]
    mention_rate = len(mentioned_results) / total if total else 0
    visibility_score = round(mention_rate * 100) if total else None

    # Position is only meaningful when the answer was in a clear ranked list.
    # A mention with no clear position (prose-style answer) still counts
    # toward the score, but is excluded from the average-position number so
    # it can't be silently mis-ranked.
    ranked_mentions = [r for r in mentioned_results if r["position"] is not None]
    avg_pos = (sum(r["position"] for r in ranked_mentions) / len(ranked_mentions)) if ranked_mentions else None
    unranked_mention_count = len(mentioned_results) - len(ranked_mentions)

    by_engine: dict[str, dict] = {}
    for r in results:
        e = by_engine.setdefault(r["provider"], {"mentioned": 0, "total": 0, "errors": 0, "is_demo": r["is_demo"]})
        if r.get("error"):
            e["errors"] += 1
            continue
        e["total"] += 1
        if r["mentioned"]:
            e["mentioned"] += 1

    # Counted once per answer and merged case-insensitively ("Joe's Fish Bar"
    # and "joe's fish bar" in one answer used to count as two mentions).
    competitor_counts = Counter()
    display_name: dict[str, str] = {}
    for r in scoreable:
        keys = set()
        for name in r["competitors_mentioned"]:
            key = name.strip().lower()
            if key and key != business.lower():
                keys.add(key)
                display_name.setdefault(key, name.strip())
        competitor_counts.update(keys)
    top_competitors = [(display_name[k], n) for k, n in competitor_counts.most_common(5)]

    recommendations = _build_recommendations(
        mention_rate=mention_rate,
        avg_position=avg_pos,
        by_engine=by_engine,
        top_competitors=top_competitors,
        error_count=len(errored),
        total_count=len(results),
    )

    action_plan = build_action_plan(
        category=category,
        by_engine=by_engine,
        mention_rate=mention_rate,
        top_competitors=top_competitors,
    )

    # Grouped by the actual question asked, so the report reads as "here's
    # how each assistant answered this specific question" rather than one
    # long flat list repeating the same handful of questions once per
    # provider -- much easier to scan when there are 4-5 providers.
    results_by_query: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in results:
        results_by_query.setdefault(r["query"], []).append(r)

    return {
        "business": business,
        "category": category,
        "visibility_score": visibility_score,
        "mention_rate": mention_rate,
        "avg_position": avg_pos,
        "unranked_mention_count": unranked_mention_count,
        "by_engine": by_engine,
        "top_competitors": top_competitors,
        "recommendations": recommendations,
        "action_plan": action_plan,
        "results": results,
        "results_by_query": [{"query": q, "answers": answers} for q, answers in results_by_query.items()],
        "error_count": len(errored),
        "any_demo_data": any(r["is_demo"] for r in results),
    }


def _build_recommendations(mention_rate, avg_position, by_engine, top_competitors,
                            error_count=0, total_count=0) -> list[str]:
    recs = []

    if error_count and total_count and error_count / total_count >= 0.25:
        recs.append(
            f"{error_count} of {total_count} checks failed to get an answer at all "
            "(API error, not a real 'not mentioned') and were excluded from the score "
            "above -- results may be incomplete. Try again shortly."
        )

    if mention_rate < 0.5:
        recs.append(FIX_LIBRARY[0]["text"])

    if top_competitors:
        leader, _count = top_competitors[0]
        recs.append(FIX_LIBRARY[1]["text"].format(competitor=leader))

    if avg_position is not None and avg_position >= 3:
        recs.append(FIX_LIBRARY[2]["text"])

    engine_rates = {
        name: (stats["mentioned"] / stats["total"] if stats["total"] else 0)
        for name, stats in by_engine.items()
    }
    weak_engines = [name for name, rate in engine_rates.items() if rate < mention_rate - 0.25]
    if weak_engines and len(by_engine) > 1:
        recs.append(FIX_LIBRARY[3]["text"].format(engines=", ".join(weak_engines)))

    if not recs:
        recs.append("Strong visibility across the board right now -- keep reviews "
                     "and business info fresh to hold this position.")

    return recs
