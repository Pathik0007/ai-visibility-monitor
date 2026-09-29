"""
Generates a realistic *simulated* AI-assistant answer for providers that
have no API key configured, so the whole pipeline is runnable today.

Every mock answer is tagged so the UI can clearly label it "DEMO DATA" --
never presented as if it came from a real ChatGPT/Perplexity/Gemini call.
"""

from __future__ import annotations
import random

# Reasons that fit the kind of business -- "fast response times" for a
# fish and chip shop made sample reports read as nonsense.
REASONS = {
    "food": ["generous portions", "great value for money", "friendly staff", "quick takeaway service",
             "consistently good reviews", "popular with locals", "fresh ingredients", "open late"],
    "health": ["gentle, thorough care", "easy online booking", "short wait times", "bulk-billing options",
               "highly rated by patients", "modern facilities"],
    "trades": ["fast call-outs", "upfront quotes", "licensed and insured", "tidy, reliable work",
               "same-day availability", "strong local reviews"],
    "default": ["well reviewed locally", "friendly service", "convenient location", "good value",
                "responsive to enquiries", "long-standing local business"],
}

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
    across a run, but vary across different queries/providers.

    Every candidate -- the business and each rival -- independently has a
    fair chance of being listed, so no single name appears in every answer
    (a lone typed competitor used to show up in 30 of 30 sample answers).
    Clearly-labelled "Sample Rival" placeholders pad a short list; real
    business names are never invented."""
    from .query_generator import category_kind, question_category
    rng = random.Random(seed)
    reasons = REASONS.get(category_kind(question_category(category)), REASONS["default"])

    rivals = list(competitors)[:6]
    rivals += SAMPLE_RIVALS[: max(0, 3 - len(rivals))]
    listed = [r for r in rivals if rng.random() < 0.6]
    if rng.random() < 0.55:
        listed.append(business)
    while len(listed) < 2:
        extra = rng.choice([r for r in rivals if r not in listed] or rivals)
        listed.append(extra)
    rng.shuffle(listed)

    lines = [rng.choice(INTROS).format(location=location)]
    for i, name in enumerate(listed[:4], start=1):
        lines.append(f"{i}. {name} - {rng.choice(reasons)}.")
    return "\n".join(lines)
