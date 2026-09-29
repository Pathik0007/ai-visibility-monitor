"""
Is a "competitor" actually a competitor? Groups free-text categories into
broad industries and compares the business with each competitor.

A cafe and a car wash never compete for the same customer question, so an
AI assistant will never recommend one instead of the other -- tracking the
car wash as a "competitor" of a cafe just adds noise to the report. Verdicts:
  match     -- same industry (cafe vs seafood restaurant)
  related   -- neighbouring industries that sometimes overlap
              (hair salon vs day spa, dentist vs cosmetic clinic)
  different_specialty -- same industry, different trade/specialty
              (plumber vs electrician, dentist vs physio) -- soft warning
  mismatch  -- different industries (cafe vs car wash)
  unknown   -- we can't tell from the wording; never warned about
"""

from __future__ import annotations
import re

# Checked in order: specific industries first, generic "retail" last, so
# "coffee shop", "barber shop" and "pet shop" land in the right place.
_GROUPS: list[tuple[str, str, str]] = [
    ("automotive", "Automotive",
     r"\b(car|cars|auto|automotive|mechanic|tyres?|tires?|smash repair|panel beat\w*|detailing|motor\w*|vehicle|"
     r"transmission|windscreen|car wash|driving school)\b"),
    ("pets", "Pets & vets", r"\b(vets?|veterinar\w*|animal|pets?|dog \w+|cat \w+|groomer|kennel)\b"),
    ("health", "Health & medical",
     r"\b(dentist\w*|dental|doctor|clinic|medical|gp|general practitioner|physio\w*|chiropract\w*|optometr\w*|"
     r"optician|psycholog\w*|podiatr\w*|pharmac\w*|chemist|hospital|orthodont\w*|dermatolog\w*|osteopath\w*|"
     r"naturopath\w*|dietitian|nutritionist|pediatric\w*|paediatric\w*|hearing|acupunctur\w*|speech|"
     r"occupational therap\w*|surgeon|pathology|radiology|aged care|nursing home)\b"),
    ("beauty", "Hair & beauty",
     r"\b(hair\w*|barber\w*|nails?|beauty|salon|spa|lash\w*|brows?|eyebrow|makeup|cosmetic\w*|skin|tattoo|"
     r"waxing|massage\w*|tanning)\b"),
    ("fitness", "Fitness & sport",
     r"\b(gym|fitness|pilates|yoga|martial arts|crossfit|boxing|personal trainer|swim\w*|climbing|sports club|"
     r"dance school|tennis|golf)\b"),
    ("education", "Education & childcare",
     r"\b(schools?|tutor\w*|tuition|college|university|preschool|child ?care|early learning|academy|"
     r"kindergarten|kinder|daycare|coaching|lessons?|teacher)\b"),
    ("food", "Food & drink",
     r"\b(restaurants?|cafes?|café|coffee|bakery|bakeries|bars?|pubs?|takeaway|food|pizz\w*|burgers?|sushi|"
     r"kebabs?|desserts?|ice cream|gelato|juice|tea house|bubble tea|bistro|diner|grill|steakhouse|noodles?|"
     r"ramen|dumplings?|bbq|barbecue|chicken|seafood|fish|fish and chips|caterer|catering|brewery|winery|deli|"
     r"patisserie|cake shop|donut|creperie|eatery|brunch|breakfast|wine bar|cocktail)\b"),
    ("accommodation", "Accommodation",
     r"\b(hotels?|motels?|hostels?|resorts?|bed and breakfast|b&b|lodge|serviced apartments?|guest house|inn)\b"),
    ("entertainment", "Entertainment & venues",
     r"\b(cinema|museum|gallery|theatre|theater|bowling|escape room|karaoke|night ?club|event venue|"
     r"wedding venue|function centre|arcade|comedy club|concert)\b"),
    ("trades", "Trades & home services",
     r"\b(plumb\w*|electric\w*|builders?|building|carpent\w*|roof\w*|painters?|painting|locksmith\w*|handyman|"
     r"removal\w*|movers|moving|clean\w*|pest|landscap\w*|garden\w*|tiler|tiling|concret\w*|fenc\w*|glazier|"
     r"plaster\w*|air conditioning|hvac|solar|renovat\w*|pool|gutter|flooring|kitchen|bathroom|joiner\w*)\b"),
    ("professional", "Professional services",
     r"\b(lawyers?|solicitors?|attorney|accountant\w*|accounting|tax|bookkeep\w*|mortgage|insurance|real estate|"
     r"consult\w*|marketing|architect\w*|financial|recruitment|agency|agent|notary|conveyanc\w*|it support|"
     r"web design\w*|software)\b"),
    ("retail", "Shops & retail",
     r"\b(store|shop|boutique|florist|grocer\w*|supermarket|mall|hardware|jewell?ery|clothing|bookstore|"
     r"newsagent|pharmacy|bottle shop|liquor|furniture|electronics|toys?|gift)\b"),
]

_RELATED = {frozenset(p) for p in [
    ("health", "beauty"), ("health", "fitness"), ("beauty", "fitness"), ("food", "retail"),
    ("food", "entertainment"), ("food", "accommodation"), ("accommodation", "entertainment"),
    ("trades", "retail"), ("automotive", "retail"), ("pets", "retail"), ("education", "fitness"),
    ("professional", "trades"),
]}

_COMPILED = [(key, label, re.compile(rx, re.I)) for key, label, rx in _GROUPS]

# In these industries the specialty matters: a plumber doesn't compete with
# an electrician, nor a dentist with a physio, even though they share a group.
_SPECIALTIES = {
    "food": ["burger", "pizz", "sushi|japanese|ramen", "fish|seafood",
             "cafe|café|coffee|brunch|breakfast|bakery|cake|patisserie", "donut|dessert|gelato|ice cream", "indian", "thai", "chinese|dumpling|yum cha",
             "italian|pasta", "mexican|taco", "kebab|lebanese|turkish|middle eastern", "chicken", "vietnamese|pho",
             "korean", "bars?\\b|pubs?\\b|wine|cocktail|brewery", "steak", "vegan|vegetarian", "bubble tea|tea house",
             "caterer|catering"],
    "health": ["dent|orthodont", "physio", "chiropract", "optometr|optician", "psycholog", "podiatr",
               "pharmac|chemist", "doctor|gp|general practitioner|medical cent", "dermatolog|skin",
               "osteopath", "naturopath", "dietitian|nutritionist", "hearing|audiolog", "speech", "cosmetic"],
    "trades": ["plumb", "electric", "roof", "paint", "locksmith", "clean", "pest", "landscap|garden",
               "tile|tiling", "concret", "fenc", "glaz", "plaster", "air condition|hvac", "solar", "pool",
               "removal|mov", "build|renovat|carpent|joiner|kitchen|bathroom"],
    "professional": ["law|solicitor|attorney|conveyanc|notary", "account|tax|bookkeep", "mortgage|financial",
                     "insurance", "real estate", "architect", "marketing|web design|software|it support",
                     "recruitment"],
    "automotive": ["car wash|detailing", "mechanic|repair|service|tyre|tire|transmission|smash|panel",
                   "car dealer|cars|dealer", "driving school"],
}


def _specialty(group: str, category: str) -> int | None:
    for i, rx in enumerate(_SPECIALTIES.get(group, [])):
        if re.search(rx, category, re.I):
            return i
    return None


def group_for(category: str | None) -> tuple[str, str] | None:
    c = (category or "").strip()
    if not c:
        return None
    for key, label, rx in _COMPILED:
        if rx.search(c):
            return key, label
    return None


def compare(business_category: str | None, competitor_category: str | None) -> dict:
    a, b = group_for(business_category), group_for(competitor_category)
    if not a or not b:
        verdict = "unknown"
    elif a[0] == b[0]:
        sa, sb = _specialty(a[0], business_category or ""), _specialty(b[0], competitor_category or "")
        verdict = "different_specialty" if (sa is not None and sb is not None and sa != sb) else "match"
    elif frozenset((a[0], b[0])) in _RELATED:
        verdict = "related"
    else:
        verdict = "mismatch"
    return {
        "verdict": verdict,
        "business_group": a[1] if a else None,
        "competitor_group": b[1] if b else None,
        "competitor_category": competitor_category or "",
        "group_key": a[0] if a else None,
    }


def _an(word: str) -> str:
    return ("an " if (word or "")[:1].lower() in "aeiou" and word else "a ") + (word or "")


def mismatch_message(name: str, business_category: str, result: dict) -> str:
    return (f"{name} is {_an(result['competitor_category'])} ({result['competitor_group'].lower()}), "
            f"not {_an(business_category)} -- AI assistants won't recommend one instead of the other, "
            f"so it isn't a useful competitor to track.")


def specialty_message(name: str, business_category: str, result: dict) -> str:
    if result.get("group_key") == "food":
        return (f"{name} is {_an(result['competitor_category'])} -- different food from {_an(business_category)}. "
                f"You'll only compete on broad questions (\u201ctakeaway near me\u201d), so it's kept but treat it as a "
                f"partial competitor.")
    return (f"{name} is {_an(result['competitor_category'])}, a different specialty from {business_category} -- "
            f"customers rarely choose between the two, so it may not be a useful comparison.")


def parse_meta(raw) -> dict[str, str]:
    """`competitor_meta` form field: JSON {competitor name: category},
    filled in by the page when a competitor is picked from suggestions or
    added from a Google Maps link. Untrusted input -- validated hard."""
    import json
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw or "{}")
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in list(data.items())[:30]:
        if isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= 200 and len(v) <= 100:
            out[k.strip()] = v.strip()
    return out


def screen_competitors(business_category: str, competitors: list[str], meta: dict[str, str]):
    """Returns (competitors to track, flagged notes). Clear mismatches are
    left out of tracking; different specialties are kept but noted."""
    from ai_visibility.analyzer import names_match
    kept, flagged = [], []
    from categories import refine_category, guess_from_name
    for name in competitors:
        cat = meta.get(name) or next((v for k, v in meta.items() if names_match(k, name)), "")
        inferred = False
        if cat:
            cat = refine_category(name, cat)[0]  # "restaurant" says little; the name often says more
        else:
            cat, inferred = guess_from_name(name), True
        if not cat:
            kept.append(name)
            continue
        res = compare(business_category, cat)
        if inferred and res["verdict"] == "mismatch":
            # Only guessed from the name -- never drop a competitor on a guess.
            flagged.append({"name": name, "category": cat, "verdict": "possible_mismatch", "excluded": False,
                            "message": f"{name} sounds like {_an(cat)}, not {_an(business_category)}. If that's right, "
                                       f"assistants won't compare the two -- consider replacing it."})
            kept.append(name)
            continue
        if res["verdict"] == "mismatch":
            flagged.append({"name": name, "category": cat, "verdict": "mismatch", "excluded": True,
                            "message": mismatch_message(name, business_category, res)})
            continue
        if res["verdict"] == "different_specialty":
            flagged.append({"name": name, "category": cat, "verdict": "different_specialty", "excluded": False,
                            "message": specialty_message(name, business_category, res)})
        kept.append(name)
    return kept, flagged
