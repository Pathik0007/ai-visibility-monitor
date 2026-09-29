"""
Turns one raw AI-assistant answer into structured signal:
  - was the business actually recommended (not just named)
  - where it ranks in the assistant's list (1st, 2nd...), if there is a list
  - which other businesses were named, and what the assistant said about
    each one ("known for its seafood boil") -- the raw material for advice
    that's specific to this business rather than generic

"Mentioned" and "position" are tracked separately: a prose answer ("I'd go
with Riverside Dental") mentions the business without a ranking, so position
stays None rather than guessing #1.

Name matching is deliberately forgiving about how the same business gets
written across the web, and strict about everything else:
  - curly quotes, accents, "&"/"and" are normalised;
  - for names of 5+ letters, apostrophes, spaces, hyphens and dots between
    letters are optional, so "Ace's Deep Sea Food" matches "Aces Deep
    Seafood" and "Kickin'Inn" matches "Kickin' Inn";
  - legal suffixes ("Pty Ltd"), a leading "The", and a " - Suburb" tail are
    also tried as variants;
  - matches must sit on word boundaries, so "Ace" never matches "Palace".

A name that only appears in a "couldn't find any information about X"
style sentence is NOT counted as a recommendation -- that's the assistant
saying it doesn't know you, which is the opposite of visibility.
"""

from __future__ import annotations
import re
import unicodedata
from functools import lru_cache

_QUOTE_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_SEP = r"[\s'`\-.]*"
_LEGAL_SUFFIX_RE = re.compile(r",?\s*(pty\.?\s*ltd\.?|pty\.?|ltd\.?|limited|inc\.?|llc|co\.)\s*$", re.I)

_NEGATIVE_RE = re.compile(
    r"(couldn'?t find|could not find|can'?t find|cannot find|unable to (?:find|locate|verify)|"
    r"no (?:specific |reliable |current |up-to-date )?information|not (?:familiar|aware)|"
    r"(?:don'?t|do not) have (?:any |specific |reliable )?(?:information|details|data)|"
    r"no (?:reviews|results|listing)|permanently closed|closed permanently|no longer (?:open|operating|in business)|"
    r"may have closed|not able to (?:find|locate|confirm))", re.I)


def _normalize(text: str) -> str:
    text = (text or "").translate(_QUOTE_TRANS)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"\s*&\s*", " and ", text)
    return text


def _alnum(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def _variants(name: str) -> list[str]:
    n = _LEGAL_SUFFIX_RE.sub("", _normalize(name).strip()).strip()
    out = [n]
    for sep in (" - ", " | ", " @ ", ", "):
        if sep in n:
            head = n.split(sep)[0].strip()
            if len(_alnum(head)) >= 5:
                out.append(head)
    if n.lower().startswith("the ") and len(_alnum(n[4:])) >= 5:
        out.append(n[4:])
    return [v for v in dict.fromkeys(out) if v]


@lru_cache(maxsize=512)
def _patterns(name: str) -> tuple:
    pats = []
    for v in _variants(name):
        chars = _alnum(v)
        if len(chars) >= 5:
            body = _SEP.join(re.escape(c) for c in chars)
            pats.append(re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.I))
        elif v.strip():
            pats.append(re.compile(r"(?<!\w)" + re.escape(v.strip()) + r"(?!\w)", re.I))
    return tuple(pats)


def _search(text: str, name: str):
    for p in _patterns(name):
        m = p.search(text)
        if m:
            return m
    return None


def _contains_name(normalized_text: str, name: str) -> bool:
    return bool(name) and _search(normalized_text, name) is not None


def names_match(a: str, b: str) -> bool:
    """True if two business names refer to the same business (same
    forgiving rules as matching inside an answer)."""
    return bool(a and b) and (_search(_normalize(a), b) is not None or _search(_normalize(b), a) is not None)


# Numbered ("1.", "2)") or bulleted ("-", "•", "*") list item, optionally
# prefixed by a markdown heading marker ("### 1. Foo").
_LIST_ITEM_RE = re.compile(r"^(\s*)(?:#{1,6}\s*)?(\d+[.)]|[-•*])\s+")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# Sub-bullet labels that aren't business names ("- Address: ...").
_FIELD_LABELS = {
    "address", "location", "locations", "price", "prices", "price range", "pricing", "hours", "opening hours",
    "phone", "contact", "website", "why", "why go", "cuisine", "rating", "ratings", "reviews", "review",
    "highlights", "highlight", "specialty", "specialties", "speciality", "note", "notes", "tip", "tips",
    "pros", "cons", "best for", "atmosphere", "menu", "services", "features", "known for", "recommended",
    "must try", "must-try", "what to order", "vibe", "parking", "booking", "bookings", "delivery",
    "summary", "overview", "details", "google rating", "average cost", "cost", "open", "suburb", "area",
}


def _list_items(text: str) -> list[dict]:
    """Top-level list items only: sub-bullets under a numbered item
    ("   - Address: ...") are not separate recommendations, and counting
    them used to push the 2nd recommendation down to "#4"."""
    items = []
    for line in text.splitlines():
        m = _LIST_ITEM_RE.match(line)
        if not m:
            continue
        items.append({"indent": len(m.group(1).expandtabs(4)), "numbered": m.group(2)[0].isdigit(),
                      "rest": line[m.end():].strip()})
    if not items:
        return []
    if any(i["numbered"] for i in items):
        top = [i for i in items if i["numbered"]]
        min_indent = min(i["indent"] for i in top)
        return [i for i in top if i["indent"] == min_indent]
    min_indent = min(i["indent"] for i in items)
    return [i for i in items if i["indent"] == min_indent]


def _item_name_and_detail(rest: str) -> tuple[str, str]:
    bold = _BOLD_RE.search(rest)
    if bold and bold.start() <= 3:
        name = bold.group(1)
        detail = rest[bold.end():]
    else:
        parts = re.split(r"\s+[-:–—]\s+|:\s+|\s+\(|,\s+", rest, maxsplit=1)
        name, detail = parts[0], (parts[1] if len(parts) > 1 else "")
    name = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", name)  # [Name](link) -> Name
    name = name.strip("*_ \t:-").strip()
    if ")" in detail and "(" not in detail.split(")")[0]:
        detail = detail.split(")", 1)[1]  # drop the rest of "(Coxs Rd)" after a "(" split
    detail = re.sub(r"\[(\d+)\]", "", detail)  # citation markers [1]
    detail = re.sub(r"\*\*|__", "", detail).strip(" \t:-–—,.")
    return name, detail[:220]


def _looks_like_business_name(name: str) -> bool:
    if not name or len(name) > 80 or len(name.split()) > 9:
        return False
    if name.lower().rstrip(":") in _FIELD_LABELS:
        return False
    if not (name[0].isupper() or name[0].isdigit()):
        return False
    return not name.endswith(":")


def _position(items: list[dict], business: str) -> int | None:
    for idx, item in enumerate(items, start=1):
        if _search(item["rest"], business):
            return idx
    return None


def _mention_sentences(text: str, name: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip() and _search(s, name)]


def analyze_answer(raw_text: str, business: str, competitors: list[str]) -> dict:
    text = _normalize(raw_text)
    items = _list_items(text)

    sentences = _mention_sentences(text, business) if _contains_name(text, business) else []
    negative = [s for s in sentences if _NEGATIVE_RE.search(s)]
    mentioned = bool(sentences) and len(negative) < len(sentences)
    position = _position(items, business) if mentioned else None

    # What the assistant said about each business it listed.
    item_details = []
    business_snippet = None
    for item in items:
        name, detail = _item_name_and_detail(item["rest"])
        if not _looks_like_business_name(name):
            continue
        is_you = _search(name, business) is not None or _search(item["rest"][:len(name) + 6], business) is not None
        item_details.append({"name": name, "detail": detail, "is_you": is_you})
        if is_you and detail and not business_snippet:
            business_snippet = detail
    if mentioned and not business_snippet:
        positive = [s for s in sentences if not _NEGATIVE_RE.search(s)]
        business_snippet = positive[0][:220] if positive else None

    competitors_mentioned = [c for c in competitors if _contains_name(text, c)]
    # Also surface businesses the assistant named that the user never typed in.
    for d in item_details:
        if d["is_you"]:
            continue
        if any(names_match(d["name"], c) for c in competitors_mentioned):
            continue
        competitors_mentioned.append(d["name"])

    return {
        "mentioned": mentioned,
        "position": position,
        "competitors_mentioned": competitors_mentioned,
        "item_details": item_details[:8],
        "business_snippet": business_snippet,
        "negative_mention": negative[0][:220] if (negative and not mentioned) else None,
        "raw_text": raw_text,
    }
