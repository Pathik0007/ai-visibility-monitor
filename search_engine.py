"""
Search-as-you-type for every search box (business name, competitors,
location), borrowing the mechanics the big map/search engines use:

1. Query understanding -- people type the *what* and the *where* together
   ("nene chicken macquarie center"). We try the trailing 1-3 words as a
   place; if they geocode to a real place near the user, the rest is the
   business name and that place becomes the search centre (Google Maps and
   Yelp both split queries like this).
2. Candidate generation from more than one angle (full query, name-only
   near the detected place), then merge + de-duplicate -- more diverse
   candidates, fewer dead ends.
3. Re-ranking on our side instead of trusting raw provider order:
     text relevance  -- how many of the typed name words appear in the
                        result's *name* (typo-tolerant: prefix match, edit
                        distance, centre/center), address words count less;
     proximity       -- distance to the Location field, or to the
                        browser's time-zone city when Location is empty
                        (the permission-free stand-in for IP location);
     same-country    -- results outside the user's country sink.
   Anything whose name matches under half of the typed name words is
   dropped: that's what let "JR Auto Center N.V." (Aruba) through for
   "nene chicken macquarie center" -- it only shared the word "center".
4. Google Places (when configured) is the primary source, since it has the
   Google Business Profile listings; OpenStreetMap results fill the gaps.

Everything here fails soft: any error -> fewer suggestions, never a
broken form.
"""

from __future__ import annotations
import math
import os
import re
import unicodedata
import logging
from concurrent.futures import ThreadPoolExecutor

import places

logger = logging.getLogger(__name__)

_STOPWORDS = {"the", "a", "an", "and", "of", "in", "at", "near", "me", "on", "by", "for", "pty", "ltd",
              "co", "inc", "llc", "shop", "store"}
_SPELLING = {"centre": "center", "theatre": "theater", "colour": "color", "jewellery": "jewelry",
             "tyre": "tire", "tyres": "tires", "mt": "mount", "st": "saint", "rd": "road"}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return text.replace("&", " and ").replace("'", "").replace("’", "")


def tokens(text: str, keep_stopwords: bool = False) -> list[str]:
    out = []
    for t in re.split(r"[^a-z0-9]+", fold(text)):
        if not t:
            continue
        t = _SPELLING.get(t, t)
        if keep_stopwords or t not in _STOPWORDS:
            out.append(t)
    return out


def _edit_distance(a: str, b: str, limit: int = 2) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def token_matches(q: str, t: str, is_last: bool = False) -> bool:
    """q = a typed word, t = a word in a result. The last typed word may be
    unfinished, so a prefix counts ("chick" -> "chicken")."""
    if q == t:
        return True
    if (is_last or len(q) >= 4) and t.startswith(q) and len(q) >= 2:
        return True
    if len(q) >= 4 and len(t) >= 4:
        allowed = 1 if len(q) < 8 else 2
        if _edit_distance(q, t[: len(q) + allowed], allowed) <= allowed or _edit_distance(q, t, allowed) <= allowed:
            return True
    if len(q) >= 5 and q in t:  # joined words: "seafood" in "deepseafood"
        return True
    return False


def coverage(query_tokens: list[str], text_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0
    joined = "".join(text_tokens)  # "sea food" still matches "seafood"
    hits = 0
    for i, q in enumerate(query_tokens):
        last = i == len(query_tokens) - 1
        if any(token_matches(q, t, last) for t in text_tokens) or (len(q) >= 5 and q in joined):
            hits += 1
    return hits / len(query_tokens)


def required_coverage(n_tokens: int) -> float:
    """Short names must match fully ("nene chicken" must not return
    "Chicken Treat"); longer ones tolerate one missing/misspelt word."""
    return 1.0 if n_tokens <= 2 else 0.66


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ---------- query understanding ----------

def split_place_hint(query: str, bias: dict | None) -> tuple[str, dict] | None:
    """("nene chicken macquarie center", ...) -> ("nene chicken", <Macquarie
    Centre geo>) when the trailing words are a real place near the user."""
    words = query.split()
    if len(words) < 2:
        return None
    lat = bias.get("lat") if bias else None
    lon = bias.get("lon") if bias else None
    tries = [k for k in (3, 2, 1) if len(words) - k >= 1 and len(" ".join(words[-k:])) >= 4]

    def attempt(k):
        hint = " ".join(words[-k:])
        name_part = " ".join(words[:-k])
        if not tokens(name_part):
            return None
        geo = places.geocode_location(hint, lat, lon)
        if not geo or geo.get("lat") is None:
            return None
        # What was found must actually be what was typed -- not a fuzzy
        # near-miss -- and must be near the user when we know where they are.
        found = tokens(" ".join(filter(None, [geo.get("name"), geo.get("city")])))
        if coverage(tokens(hint), found) < 0.75:
            return None
        if lat is not None and lon is not None and haversine_km(lat, lon, geo["lat"], geo["lon"]) > 1500:
            return None
        return (name_part, geo)

    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(attempt, tries))
    for r in results:  # longest place phrase that worked wins
        if r:
            return r
    return None


def resolve_bias(lat, lon, tz: str | None) -> dict | None:
    if lat is not None and lon is not None:
        geo = {"lat": lat, "lon": lon}
        return geo
    return places.region_from_timezone(tz)


# ---------- businesses ----------

def name_matches(result: dict, name_toks: list[str]) -> bool:
    """Does this result's name contain what was typed? Short names must
    match fully; if extra words were a place we couldn't geocode ("aces
    seafood north ryde"), the leading words must be in the name and the
    rest may be in the address."""
    if not name_toks:
        return True
    rname = tokens(result.get("name", ""), keep_stopwords=True)
    need = required_coverage(len(name_toks))
    if coverage(name_toks, rname) >= need:
        return True
    raddr = tokens(" ".join(filter(None, [result.get("full_address"), result.get("location")])), keep_stopwords=True)
    lead = name_toks[: max(1, (len(name_toks) + 1) // 2)]
    return coverage(lead, rname) == 1.0 and coverage(name_toks, rname + raddr) >= need


def _score(result: dict, name_toks: list[str], all_toks: list[str], center: dict | None,
           country: str | None) -> float | None:
    rname = tokens(result.get("name", ""), keep_stopwords=True)
    raddr = tokens(" ".join(filter(None, [result.get("full_address"), result.get("location")])), keep_stopwords=True)
    if not name_matches(result, name_toks):
        return None  # the result's name doesn't contain what was typed
    name_cov = coverage(name_toks, rname)
    all_cov = coverage(all_toks, rname + raddr)
    score = 0.55 * name_cov + 0.2 * all_cov
    # Starts-with and exact-name bonuses (what people expect at the top).
    joined_q, joined_r = " ".join(name_toks), " ".join(tokens(result.get("name", "")))
    if joined_q and joined_r.startswith(joined_q):
        score += 0.1
    if joined_q and joined_q == joined_r:
        score += 0.05
    if center and result.get("lat") is not None and center.get("lat") is not None:
        km = haversine_km(center["lat"], center["lon"], result["lat"], result["lon"])
        result["distance_km"] = round(km, 1)
        score += 0.3 / (1 + km / 8)  # ~0.3 on the spot, 0.15 at 8 km, ~0 far away
    if country and result.get("_country") and result["_country"] != country:
        score -= 0.4
    return score


def _dedupe(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        key_name = " ".join(tokens(r["name"]))
        dup = False
        for o in out:
            if " ".join(tokens(o["name"])) == key_name:
                # Without coordinates (Google suggestions have none) only the
                # address can tell branches apart -- "close" can't be assumed,
                # or every branch of a chain collapsed into one suggestion.
                if r.get("lat") is not None and o.get("lat") is not None:
                    close = haversine_km(r["lat"], r["lon"], o["lat"], o["lon"]) < 0.3
                else:
                    close = False
                addr_r, addr_o = fold(r.get("full_address", "")), fold(o.get("full_address", ""))
                same_addr = addr_r == addr_o and (bool(addr_r) or (r.get("lat") is None and o.get("lat") is None))
                if close or same_addr:
                    dup = True
                    break
        if not dup:
            out.append(r)
    return out


def _clean(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_") and k not in ("lat", "lon")}


def search_businesses(query: str, lat=None, lon=None, region: str | None = None, session: str | None = None,
                      tz: str | None = None, limit: int = 6) -> list[dict]:
    query = " ".join((query or "").split())
    if len(query) < 3 or len(query) > places.MAX_QUERY_LEN:
        return []
    location_given = lat is not None and lon is not None
    bias = resolve_bias(lat, lon, tz)
    country = (region or (bias or {}).get("country") or "").upper() or None

    # Understand "what + where" only when the Location field didn't already say where.
    split = None if location_given else split_place_hint(query, bias)
    name_part = split[0] if split else query
    center = split[1] if split else bias
    name_toks = tokens(name_part) or tokens(name_part, keep_stopwords=True)
    all_toks = tokens(query)

    candidates: list[dict] = []
    google_ok = False
    if places.google_places_enabled():
        try:
            g = places._search_google(
                query, os.environ["GOOGLE_PLACES_API_KEY"], limit,
                lat=(center or {}).get("lat"), lon=(center or {}).get("lon"), session=session, region=country)
            for i, r in enumerate(g):
                r["_rank"] = i
            candidates += g
            google_ok = True
        except Exception as exc:
            logger.warning("Google autocomplete failed, using OpenStreetMap: %s", exc)

    # OSM: always when Google isn't available; as a gap-filler when Google
    # came back thin. Two angles: the full query, and the name alone near
    # the detected place.
    if not google_ok or len(candidates) < 3:
        jobs = [(query, bias)]
        if split and name_part:
            jobs.append((name_part, center))
        cache_key = f"biz|{fold(query)}|{(center or {}).get('lat')},{(center or {}).get('lon')}"
        cached = places._cache_get(cache_key)
        if cached is not None:
            osm = [dict(r) for r in cached]
        else:
            def run(job):
                q, b = job
                try:
                    return places._search_photon(q, 15, (b or {}).get("lat"), (b or {}).get("lon"))
                except Exception as exc:
                    logger.warning("Photon search failed: %s", exc)
                    return None
            with ThreadPoolExecutor(max_workers=2) as ex:
                outs = list(ex.map(run, jobs))
            osm = [r for o in outs if o for r in o]
            if any(o is not None for o in outs):  # never cache a failure
                places._cache_set(cache_key, [dict(r) for r in osm])
        candidates += osm

    scored = []
    for r in candidates:
        if r.get("source") == "google":
            # Google already ranks by its own relevance + our location bias;
            # keep its order, but still drop names that don't match at all.
            if not name_matches(r, name_toks):
                continue
            scored.append((2.0 - r["_rank"] * 0.01, r))
            continue
        s = _score(r, name_toks, all_toks, center, country)
        if s is not None:
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    ranked = _dedupe([r for _, r in scored])
    # Same-country results exist? Then drop the overseas namesakes entirely
    # (the "Singapore / Toronto branch" problem).
    if country and any(r.get("_country") == country or r.get("source") == "google" for r in ranked):
        ranked = [r for r in ranked if not r.get("_country") or r["_country"] == country]
    return [_clean(r) for r in ranked[:limit]]


# ---------- locations (suburbs / towns / cities) ----------

def search_locations(query: str, tz: str | None = None, session: str | None = None, limit: int = 6) -> list[dict]:
    query = " ".join((query or "").split())
    if len(query) < 2 or len(query) > places.MAX_QUERY_LEN:
        return []
    bias = places.region_from_timezone(tz)
    results: list[dict] = []
    if places.google_places_enabled():
        try:
            results = places.google_regions(query, os.environ["GOOGLE_PLACES_API_KEY"], bias=bias, session=session)
        except Exception as exc:
            logger.warning("Google region autocomplete failed, using OpenStreetMap: %s", exc)
    if not results:
        cache_key = f"loc|{fold(query)}|{(bias or {}).get('country')}"
        cached = places._cache_get(cache_key)
        if cached is not None:
            results = [dict(r) for r in cached]
        else:
            try:
                results = places._photon_places(query, 12, (bias or {}).get("lat"), (bias or {}).get("lon"))
                places._cache_set(cache_key, [dict(r) for r in results])
            except Exception as exc:
                logger.warning("Photon place search failed: %s", exc)
                return []
        qt = tokens(query, keep_stopwords=True)
        country = (bias or {}).get("country")
        scored = []
        for i, r in enumerate(results):
            cov = coverage(qt, tokens(r["name"], keep_stopwords=True) + tokens(r.get("full_address", ""), keep_stopwords=True))
            if cov < 0.5:
                continue
            s = cov + (0.15 if fold(r["name"]).startswith(fold(query.split(",")[0])) else 0) - i * 0.01
            if country and r.get("country") and r["country"] != country:
                s -= 0.3
            scored.append((s, r))
        scored.sort(key=lambda x: -x[0])
        results = [r for _, r in scored]
    seen, out = set(), []
    for r in results:
        key = fold(r.get("value") or r["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:limit]
