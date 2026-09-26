"""
Turns one raw AI-assistant answer into structured signal:
  - was the business mentioned at all
  - roughly how prominent (1st, 2nd... or not in the list)
  - which competitors were named instead/alongside it

Heuristic by default (works with zero API keys). If ANTHROPIC_API_KEY is
configured, a small LLM pass can be swapped in later for messier, less
list-shaped answers -- the heuristic below already handles the common
numbered/list style most assistants use for "best X near me" questions.

Important distinction: "mentioned" (does the name appear anywhere in the
answer) and "position" (where it ranks in a clear numbered/bulleted list)
are tracked separately. A prose-style answer like "I'd go with Riverside
Dental" mentions the business with no real ranking -- treating that as
"position #1" would be a guess dressed up as a measurement, so position
stays None whenever there's no actual list to rank within.
"""

from __future__ import annotations
import re


def _find_position(text: str, name: str) -> int | None:
    """Return the 1-based position at which `name` first appears among
    numbered/bulleted list items, or None if the answer isn't in list form
    (even if the name is mentioned elsewhere in prose)."""
    item_lines = [l for l in text.splitlines() if re.match(r"^\s*(\d+[.)]|[-•*])", l)]
    for idx, line in enumerate(item_lines, start=1):
        if name.lower() in line.lower():
            return idx
    return None


def analyze_answer(raw_text: str, business: str, competitors: list[str]) -> dict:
    mentioned = business.lower() in raw_text.lower()
    position = _find_position(raw_text, business) if mentioned else None

    competitors_mentioned = [c for c in competitors if c.lower() in raw_text.lower()]

    return {
        "mentioned": mentioned,
        "position": position,
        "competitors_mentioned": competitors_mentioned,
        "raw_text": raw_text,
    }
