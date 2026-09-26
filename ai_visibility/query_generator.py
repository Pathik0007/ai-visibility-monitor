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
    "Is {business} a good {category} in {location}?",
    "Compare the top {category} options in {location}.",
]

AUDIENCES = ["families", "walk-ins", "urgent appointments", "first-time customers"]


def generate_queries(business: str, category: str, location: str, count: int = 8) -> list[str]:
    queries = []
    i = 0
    while len(queries) < count:
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

    queries.extend(_llm_extra_queries(business, category, location))
    return queries[:count] if len(queries) < count else queries


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
