"""
Generates a realistic *simulated* AI-assistant answer for providers that
have no API key configured, so the whole pipeline is runnable today.

Every mock answer is tagged so the UI can clearly label it "DEMO DATA" --
never presented as if it came from a real ChatGPT/Perplexity/Gemini call.
"""

from __future__ import annotations
import random

REASON_PHRASES = [
    "known for great reviews",
    "highly rated for customer service",
    "convenient location and opening hours",
    "competitive pricing",
    "fast response times",
    "strong reputation in the area",
]

SAMPLE_RIVALS = ["Sample Rival A", "Sample Rival B", "Sample Rival C"]

INTROS = [
    "Here are a few good options in {location}:",
    "Based on reviews and availability, I'd suggest:",
    "A few well-regarded choices near {location}:",
    "You might want to consider:",
]


def generate_mock_answer(query: str, business: str, category: str, location: str,
                          competitors: list[str], seed: int) -> str:
    """Deterministic-ish per (business, provider, query) so results feel stable
    across a run, but vary across different queries/providers."""
    rng = random.Random(seed)
    # With no competitors typed in, the pool used to be just [business] --
    # so every simulated answer named it at #1 and every demo report showed
    # a fake 100%. Clearly-labelled placeholder rivals keep the sample
    # realistic without inventing plausible-looking real business names.
    rivals = list(competitors) or SAMPLE_RIVALS
    pool = [business] + rivals
    rng.shuffle(pool)

    # Sometimes the business doesn't make the shortlist at all.
    if rng.random() < 0.4 and business in pool and len(pool) > 1:
        pool.remove(business)

    lines = [rng.choice(INTROS).format(location=location)]
    shortlist = pool[: rng.randint(2, 4)] if len(pool) > 2 else pool
    if business in pool and business not in shortlist and rng.random() < 0.5:
        shortlist[-1] = business  # keep the business's odds of appearing realistic
    for i, name in enumerate(shortlist, start=1):
        reason = rng.choice(REASON_PHRASES)
        lines.append(f"{i}. {name} - {reason}.")

    return "\n".join(lines)
