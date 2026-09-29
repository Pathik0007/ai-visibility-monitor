"""
Generates the realistic customer questions we'll put to each AI assistant.

Template-based so it needs no API key and always works. If ANTHROPIC_API_KEY
is set, it also asks Claude to add a few more natural-sounding variations on
top of the templates -- purely additive, never required.
"""

from __future__ import annotations
import os

import re

TEMPLATES = [
    "What's the best {category} in {location}?",
    "Can you recommend a good {category} near {location}?",
    "I need a {category} in {location}, any suggestions?",
    "Top rated {category} in {location}?",
    "Which {category} in {location} has the best reviews?",
    "Affordable {category} in {location}?",
    "Which {category} in {location} is open on weekends?",
    "Best {category} in {location} for {audience}?",
    "Compare the top {category} options in {location}.",
]

# A bare cuisine/adjective isn't a noun a customer would ask for ("I need a
# fast food in Sydney"), so these get " restaurant" added in questions.
_ADJECTIVE_CATEGORIES = {
    "fast food", "seafood", "italian", "thai", "chinese", "indian", "japanese", "korean", "vietnamese",
    "mexican", "greek", "lebanese", "turkish", "french", "spanish", "vegan", "vegetarian", "halal",
    "asian", "mediterranean", "middle eastern", "malaysian", "nepalese", "american", "pizza", "burger",
    "sushi", "chicken", "barbecue", "bbq", "dessert", "breakfast", "brunch", "gluten-free", "fusion",
}
_PROPER_ADJECTIVES = {
    "italian", "thai", "chinese", "indian", "japanese", "korean", "vietnamese", "mexican", "greek",
    "lebanese", "turkish", "french", "spanish", "asian", "mediterranean", "middle", "eastern",
    "malaysian", "nepalese", "american",
}

_FOOD_RE = re.compile(r"\b(restaurant|cafe|café|coffee|bakery|pizz|burger|sushi|kebab|bars?\b|pubs?\b|diner|takeaway|"
                      r"food|dessert|ice cream|bistro|eatery|grill|steakhouse|noodle|ramen|dumpling|bbq|"
                      r"barbecue|chicken|seafood|fish|gelato|brunch|breakfast|catering|caterer)", re.I)
_HEALTH_RE = re.compile(r"\b(dentist|dental|doctor|clinic|medical|gp\b|general practitioner|physio|chiropract|"
                        r"optometr|psycholog|podiatr|veterinar|vets?\b|pharmac|chemist|hospital|orthodont|"
                        r"dermatolog|osteopath|naturopath|dietitian|nutritionist|pediatric|hearing)", re.I)
_TRADES_RE = re.compile(r"\b(plumb|electrician|builder|carpent|roof|painter|locksmith|handyman|mechanic|"
                        r"removal|movers|moving|clean|pest|landscap|gardener|tiler|concret|fenc|glazier|"
                        r"plaster|air conditioning|solar|renovat|repair|install)", re.I)

_AUDIENCES = {
    "food": ["families", "a quick lunch", "a group dinner", "a date night"],
    "health": ["urgent appointments", "families", "new patients", "weekend appointments"],
    "trades": ["an urgent job", "a free quote", "a small job", "a weekend job"],
    "default": ["families", "first-time customers", "a last-minute booking", "value for money"],
}

# Keyword -> what that kind of question is really testing. Used by the report
# to turn "you were missed on these questions" into a specific fix.
QUESTION_THEMES = [
    ("affordable", "price"),
    ("open on weekends", "hours"),
    ("best reviews", "reviews"),
    ("top rated", "reviews"),
    (" for ", "audience"),
    ("compare", "comparison"),
    ("recommend", "recommendation"),
    ("any suggestions", "recommendation"),
    ("what's the best", "best_of"),
]


def question_theme(query: str) -> str:
    q = (query or "").lower()
    for needle, theme in QUESTION_THEMES:
        if needle in q:
            return theme
    return "general"


def category_kind(category: str) -> str:
    c = category or ""
    if _HEALTH_RE.search(c):
        return "health"
    if _FOOD_RE.search(c):
        return "food"
    if _TRADES_RE.search(c):
        return "trades"
    return "default"


def question_category(category: str) -> str:
    """Turns whatever's in the Category field into something that reads as
    a noun in a question: "fast food" -> "fast food restaurant",
    "italian" -> "Italian restaurant", "dentist" -> "dentist"."""
    c = " ".join((category or "").strip().split())
    low = c.lower()
    if low in _ADJECTIVE_CATEGORIES:
        c = low + " restaurant"
    elif low.endswith(" food") and "restaurant" not in low and "shop" not in low and "truck" not in low:
        c = low + " restaurant"
    words = c.split(" ")
    return " ".join(w.capitalize() if w.lower() in _PROPER_ADJECTIVES else w for w in words)


def _sentence_case(q: str) -> str:
    return q[:1].upper() + q[1:] if q else q


def generate_queries(business: str, category: str, location: str, count: int = 8) -> list[str]:
    # Template-based queries never mention `business` -- we're measuring
    # whether the assistant names it *unprompted*, so a query that already
    # says the business's name would inflate the score for a question no
    # real customer would actually type.
    noun = question_category(category)
    audiences = _AUDIENCES[category_kind(noun)]
    queries = []
    i = 0
    max_template_rounds = len(TEMPLATES) * max(1, (count // len(TEMPLATES) + 2))
    rounds = 0
    while len(queries) < count and rounds < max_template_rounds:
        template = TEMPLATES[i % len(TEMPLATES)]
        q = _sentence_case(template.format(
            category=noun,
            location=location,
            business=business,
            audience=audiences[(i // len(TEMPLATES)) % len(audiences)],
        ))
        if q not in queries:
            queries.append(q)
        i += 1
        rounds += 1

    # (An optional Claude call used to add extra phrasings here, but the
    # templates always fill `count` first, so its output was thrown away --
    # a wasted paid API call on every check. Removed.)
    return queries[:count]
