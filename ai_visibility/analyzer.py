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

Matching is normalized and word-boundary-based:
  - curly quotes ('smart quotes') are folded to plain ASCII ones, so
    "Joe's Pizza" matches text that renders "Joe's Pizza" with a typographic
    apostrophe.
  - "&" and "and" are treated as interchangeable, since the same business
    name gets written both ways across the web.
  - matches only occur on whole-word boundaries, so a short name like "Ace"
    doesn't false-positive match inside "Palace" or "Spacey".
"""

from __future__ import annotations
import re

_QUOTE_TRANS = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
})


def _normalize(text: str) -> str:
    text = text.translate(_QUOTE_TRANS)
    text = re.sub(r"\s*&\s*", " and ", text)
    return text


def _name_pattern(name: str) -> "re.Pattern":
    normalized = _normalize(name).strip()
    escaped = re.escape(normalized)
    return re.compile(r"(?<!\w)" + escaped + r"(?!\w)", re.IGNORECASE)


def _contains_name(normalized_text: str, name: str) -> bool:
    if not name:
        return False
    return _name_pattern(name).search(normalized_text) is not None


# Matches a numbered ("1.", "2)") or bulleted ("-", "•", "*") list item,
# optionally prefixed by a markdown heading marker ("### 1. Foo") -- some
# assistants render their top picks as headings rather than a plain list.
_LIST_ITEM_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s*)?(?:\d+[.)]|[-•*])\s*")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _find_position(normalized_text: str, name: str) -> int | None:
    item_lines = [l for l in normalized_text.splitlines() if _LIST_ITEM_RE.match(l)]
    pattern = _name_pattern(name)
    for idx, line in enumerate(item_lines, start=1):
        if pattern.search(line):
            return idx
    return None


def _extract_list_item_names(normalized_text: str) -> list[str]:
    """Best-effort extraction of the "name" heading each ranked list item --
    used to surface competitors the assistant named that the user never
    typed in. Prefers a bolded phrase (the common style for these answers),
    else the text up to the first separator."""
    names = []
    for line in normalized_text.splitlines():
        if not _LIST_ITEM_RE.match(line):
            continue
        rest = _LIST_ITEM_RE.sub("", line).strip()
        if not rest:
            continue
        bold = _BOLD_RE.search(rest)
        candidate = bold.group(1).strip() if bold else re.split(r"[-:–—,]", rest, maxsplit=1)[0].strip()
        candidate = candidate.strip("*_ \t")
        if candidate and len(candidate) <= 80:
            names.append(candidate)
    return names


def analyze_answer(raw_text: str, business: str, competitors: list[str]) -> dict:
    normalized_text = _normalize(raw_text)
    mentioned = _contains_name(normalized_text, business)
    position = _find_position(normalized_text, business) if mentioned else None

    competitors_mentioned = [c for c in competitors if _contains_name(normalized_text, c)]

    # Also surface competitors the assistant named that the user never typed
    # in -- otherwise "who's showing up instead" only shows names the user
    # already knew to ask about, missing anyone new the assistant mentions.
    seen_lower = {c.lower() for c in competitors_mentioned} | {business.lower()}
    for candidate in _extract_list_item_names(normalized_text):
        if candidate.lower() in seen_lower:
            continue
        competitors_mentioned.append(candidate)
        seen_lower.add(candidate.lower())

    return {
        "mentioned": mentioned,
        "position": position,
        "competitors_mentioned": competitors_mentioned,
        "raw_text": raw_text,
    }
