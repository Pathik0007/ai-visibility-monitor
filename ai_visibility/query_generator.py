"""
Generates the realistic customer questions we'll put to each AI assistant.

Template-based so it needs no API key and always works. If ANTHROPIC_API_KEY
is set, it also asks Claude to add a few more natural-sounding variations on
top of the templates -- purely additive, never required.
"""

from __future__ import annotations
import os
from .providers.claude_provider import ClaudeProvider
from .providers.base import NotConfiguredError

TEMPLATES = [
    "What's the best {category} in {location}?",
    "Can you recommend a good {category} near {location}?",
    "I need a {category} in {location}, any suggestions?",
    "Top rated {category} in {location}?",
    "Which {category} in {location} has the best reviews?",
    "Affordable {category} in {location}?",
    "{category} in {location} open on weekends?",
    "Best {category} near me in {location} for {audience}?",
    "Compare the top {category} options in {location}.",
]

AUDIENCES = ["families", "walk-ins", "urgent appointments", "first-time customers"]


def generate_queries(business: str, category: str, location: str, count: int = 8) -> list[str]:
    # Template-based queries never mention `business` -- we're measuring
    # whether the assistant names it *unprompted*, so a query that already
    # says the business's name would inflate the score for a question no
    # real customer would actually type.
    queries = []
    i = 0
    max_template_rounds = len(TEMPLATES) * max(1, (count // len(TEMPLATES) + 2))
    rounds = 0
    while len(queries) < count and rounds < max_template_rounds:
        template = TEMPLATES[i % len(TEMPLATES)]
        q = template.format(
            category=category,
            location=location,
            business=business,
            audience=AUDIENCES[i % len(AUDIENCES)],
        )
        if q not in queries:
            queries.append(q)
        i += 1
        rounds += 1

    queries.extend(_llm_extra_queries(business, category, location))
    # Always respect the caller's requested count -- previously this only
    # truncated when there were *fewer* than `count` queries, so adding the
    # optional Claude-generated extras (or simply having a Claude key set)
    # would silently make num_queries un-enforced and answers slower/pricier
    # than the user asked for.
    return queries[:count]


def _llm_extra_queries(business: str, category: str, location: str) -> list[str]:
    """Optional: use Claude to add 2-3 more natural questions, if configured."""
    provider = ClaudeProvider()
    if not provider.is_configured():
        return []
    prompt = (
        f"List 3 short, realistic questions a real customer might type into "
        f"ChatGPT or Perplexity while looking for a '{category}' in "
        f"'{location}'. One per line, no numbering, no extra commentary."
    )
    try:
        text = provider.ask(prompt)
    except Exception:
        return []
    lines = [l.strip("-• \t") for l in text.splitlines() if l.strip()]
    return lines[:3]
