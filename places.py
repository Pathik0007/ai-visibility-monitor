"""
Business-name autocomplete for the "Business name" field.

Same demo-mode philosophy as ai_visibility/providers/: works out of the box
with zero setup, and upgrades automatically to Google's own business
database (the same listings behind Google Maps / Google Business Profile)
when GOOGLE_PLACES_API_KEY is set.

Google path uses **Places API (New)** -- Autocomplete (New) while typing,
then one Place Details (New) call when a suggestion is picked, both tied
together by a session token so Google bills them as one search session
rather than per keystroke. The legacy Places Autocomplete endpoint this
used before can't be enabled on new Google Cloud projects, so a freshly
created key would have silently fallen back to the free path forever.

The free default is Photon (photon.komoot.io), an OpenStreetMap-based
search API that's actually built for search-as-you-type use. An earlier
version of this called OpenStreetMap's own Nominatim search endpoint
directly for this -- that was a mistake: Nominatim's usage policy
explicitly prohibits autocomplete/typeahead traffic against its public
instance, and it also tends to rate-limit or reject requests from cloud/
datacenter IPs (which is what a Render/Railway/Heroku-style host looks
like to it) -- so in production it would silently return nothing, every
time, which is exactly the symptom that flagged this.

Coverage caveat either way: the free path only ever suggests places that
exist in OpenStreetMap's own database. Well-known chains are reliably
there; a small independent business may return zero results even when
everything here is working correctly -- that's a data-coverage limit, not
a bug. Set GOOGLE_PLACES_API_KEY for Google's much larger place database.

Either backend returns enough to fill in all three fields when someone picks
a suggestion: the business name, a best-guess category (e.g. "restaurant",
"dentist"), and a location string -- so the person only has to type the name
and the rest can autofill.

This is a nice-to-have, never a hard dependency: any failure (network down,
provider outage, rate limited, no result) returns an empty list rather than
raising, so the manual text fields underneath always keep working.
"""

from __future__ import annotations
import os
import re
import time
import logging
import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 4  # seconds -- this backs an as-you-type UI, never worth a long wait
MAX_QUERY_LEN = 100
DEFAULT_LIMIT = 5

# Small in-memory cache so identical queries typed by many users (or by the
# same user re-focusing the field) don't re-hit the external API every time,
# and so we stay well within the free Photon instance's fair-use expectations.
_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # seconds
_CACHE_MAX_ENTRIES = 500

# Generic OSM/Google place types that aren't useful as a "category" on their
# own -- skipped when picking which type to show.
_GENERIC_TYPES = {
    "point_of_interest", "establishment", "premise", "subpremise",
    "geocode", "political", "place", "yes",
}


def _cache_get(key: str):
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: list[dict]) -> None:
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        _CACHE.clear()  # simple/cheap; this is a convenience cache, not correctness-critical
    _CACHE[key] = (time.time(), value)


def _humanize(type_str: str) -> str:
    return type_str.replace("_", " ").strip().lower()


# OSM tag values -> the wording people (and Google) actually use, so an
# autofilled category reads naturally in questions ("fast_food" alone gave
# "I need a fast food in Sydney").
_OSM_VALUE_NAMES = {
    "fast_food": "fast food restaurant", "doctors": "medical centre", "hairdresser": "hair salon",
    "car_repair": "car repair shop", "beauty": "beauty salon", "clothes": "clothing store",
    "butcher": "butcher shop", "optician": "optometrist", "veterinary": "veterinarian",
    "fitness_centre": "gym", "kindergarten": "preschool", "childcare": "child care centre",
    "ice_cream": "ice cream shop", "alcohol": "bottle shop", "hardware": "hardware store",
    "shoes": "shoe store", "books": "bookstore", "jewelry": "jewelry store", "furniture": "furniture store",
    "electronics": "electronics store", "mobile_phone": "cell phone store", "pet": "pet shop",
    "car": "car dealer", "bicycle": "bicycle shop", "massage": "massage therapist",
    "physiotherapist": "physiotherapist", "clinic": "medical centre", "nightclub": "night club",
}


def _map_osm_props_category(props: dict) -> str:
    osm_value = props.get("osm_value", "")
    if osm_value in _OSM_VALUE_NAMES:
        return _OSM_VALUE_NAMES[osm_value]
    if osm_value and osm_value not in _GENERIC_TYPES:
        return _humanize(osm_value)
    osm_key = props.get("osm_key", "")
    return _humanize(osm_key) if osm_key else ""


def _format_photon_location(props: dict) -> str:
    city = props.get("city") or props.get("district") or props.get("county") or ""
    state = props.get("state") or ""
    parts = [p for p in (city, state) if p]
    return ", ".join(parts)


def _format_photon_address(props: dict) -> str:
    parts = []
    street_part = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    if street_part:
        parts.append(street_part)
    for key in ("city", "state", "country"):
        value = props.get(key)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


# OSM feature kinds that are areas/roads rather than businesses -- a
# business-name search returning "North Ryde" (the suburb) or "Waterloo
# Road" isn't a useful suggestion.
_PHOTON_NON_BUSINESS_KEYS = {"place", "highway", "boundary", "landuse", "natural", "waterway", "railway"}


def _search_photon(query: str, limit: int, lat: float | None = None, lon: float | None = None) -> list[dict]:
    params = {"q": query, "limit": limit + 3, "lang": "en"}  # over-fetch: some get filtered below
    if lat is not None and lon is not None:
        # Biases (doesn't strictly filter) results toward this point -- without
        # it, Photon ranks purely on text-match fuzziness with no geography at
        # all, so a query like "nene chicken" can rank a Singapore or Toronto
        # branch above the one actually near the location the user typed.
        params["lat"] = lat
        params["lon"] = lon
        params["location_bias_scale"] = 1.0
    resp = requests.get(
        "https://photon.komoot.io/api/",
        params=params,
        headers={"User-Agent": "AI-Visibility-Monitor/1.0 (business-name autocomplete)"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    results = []
    for feature in resp.json().get("features", []):
        props = feature.get("properties") or {}
        name = props.get("name")
        if not name:
            continue  # a bare street/postcode match with no place name isn't a useful suggestion here
        if props.get("osm_key") in _PHOTON_NON_BUSINESS_KEYS:
            continue
        results.append({
            "name": name,
            "category": _map_osm_props_category(props),
            "location": _format_photon_location(props),
            "full_address": _format_photon_address(props),
            "source": "osm",
        })
        if len(results) >= limit:
            break
    return results


def _geocode_photon(location_text: str) -> dict | None:
    resp = requests.get(
        "https://photon.komoot.io/api/",
        params={"q": location_text, "limit": 1, "lang": "en"},
        headers={"User-Agent": "AI-Visibility-Monitor/1.0 (location geocoding)"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        return None
    coords = (features[0].get("geometry") or {}).get("coordinates")
    if not coords or len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]  # GeoJSON order is [lon, lat]
    props = features[0].get("properties") or {}
    # Also where it is -- used to localise the AI assistants' own web
    # searches (country/city) and to keep business suggestions in-country.
    place_name = props.get("name") if props.get("osm_key") == "place" else None
    return {
        "lat": lat, "lon": lon,
        "country": (props.get("countrycode") or "").upper() or None,
        "city": place_name or props.get("city") or props.get("district") or None,
        "region": props.get("state") or None,
    }


def geocode_location(location_text: str) -> dict | None:
    """Best-effort: turn free-text like "Parramatta, Sydney" into a
    lat/lon so the business-name search below can be biased toward it.
    Never raises -- a failure here should just mean an unbiased (global)
    name search, not a broken page.

    Always Photon: it geocodes suburbs/cities well, it's free, and it means a
    Google key only needs "Places API (New)" enabled -- not the separate
    Geocoding API as well (a key without it used to fail every geocode
    first, adding a wasted round-trip to every keystroke in Location)."""
    location_text = (location_text or "").strip()
    if len(location_text) < 3 or len(location_text) > MAX_QUERY_LEN:
        return None

    cache_key = f"geocode|{location_text.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or None  # cached `{}` means "looked up, found nothing"

    try:
        result = _geocode_photon(location_text)
    except Exception as exc:
        logger.warning("Photon geocoding failed: %s", exc)
        return None  # never cache a failure -- retry on the next keystroke

    # A genuine "nothing there" answer is cached (as {}) like a hit.
    _cache_set(cache_key, result or {})
    return result


# ---------- Google Places API (New) ----------

_GOOGLE_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
_GOOGLE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
# Only "Essentials"-tier fields -- the cheapest Place Details SKU. The name
# already comes from the autocomplete suggestion, so displayName (a "Pro"
# field) isn't needed.
_GOOGLE_DETAILS_FIELDS = "addressComponents,types,shortFormattedAddress"

_GOOGLE_GENERIC_TYPES = _GENERIC_TYPES | {"food", "store", "health", "finance", "general_contractor"}
_GOOGLE_ADDRESS_ONLY_TYPES = {"street_address", "route", "premise", "subpremise", "postal_code",
                               "locality", "sublocality", "political", "geocode", "neighborhood",
                               "administrative_area_level_1", "administrative_area_level_2", "country"}

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,400}$")


def valid_session_token(token) -> str | None:
    return token if isinstance(token, str) and _SESSION_RE.match(token) else None


_GOOGLE_TYPE_NAMES = {
    "car_repair": "car repair shop", "hair_care": "hair salon", "meal_takeaway": "takeaway restaurant",
    "meal_delivery": "food delivery", "lodging": "accommodation", "doctor": "medical centre",
    "real_estate_agency": "real estate agency", "moving_company": "removalist",
}


def _google_category(types: list[str]) -> str:
    """Google lists types most-specific first ("seafood_restaurant",
    "restaurant", "food", "point_of_interest", ...) -- take the first one
    that actually says what the business is."""
    for t in types or []:
        if t not in _GOOGLE_GENERIC_TYPES and t not in _GOOGLE_ADDRESS_ONLY_TYPES:
            return _GOOGLE_TYPE_NAMES.get(t) or _humanize(t)
    for t in types or []:
        if t in ("food", "store", "health"):
            return _humanize(t)
    return ""


def _location_from_secondary(secondary: str) -> str:
    """Best guess at suburb/city from Google's secondary text, used until
    Place Details fills in the exact value. "Waterloo Rd, North Ryde NSW,
    Australia" -> "North Ryde NSW"; "Main St, Springfield, IL, USA" ->
    "Springfield, IL"."""
    parts = [p.strip() for p in (secondary or "").split(",") if p.strip()]
    if len(parts) < 2:
        return parts[0] if parts else ""
    parts = parts[:-1]  # drop the country
    last = parts[-1]
    if len(last) <= 3 and last.isupper() and len(parts) >= 2:
        return f"{parts[-2]}, {last}"
    return last


def _google_error(resp) -> str:
    try:
        err = resp.json().get("error", {})
        return f"HTTP {resp.status_code} {err.get('status', '')}: {err.get('message', '')}".strip()
    except Exception:
        return f"HTTP {resp.status_code}"


def _search_google(query: str, api_key: str, limit: int, lat: float | None = None,
                   lon: float | None = None, session: str | None = None,
                   region: str | None = None) -> list[dict]:
    body: dict = {"input": query}
    if region:
        # Keep suggestions in the user's country -- without it a small local
        # business competes with same-named places worldwide.
        body["includedRegionCodes"] = [region.lower()]
    if lat is not None and lon is not None:
        # "Bias", not "restrict": a strict filter would hide a real result just
        # outside an arbitrary radius; this only pushes nearby matches higher.
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 50000.0}}
    if session:
        body["sessionToken"] = session
    resp = requests.post(
        _GOOGLE_AUTOCOMPLETE_URL,
        json=body,
        headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        _record_google_error(f"Autocomplete: {_google_error(resp)}")
        raise RuntimeError(f"Google Places autocomplete failed: {_google_error(resp)}")
    _record_google_error(None)
    results = []
    for suggestion in resp.json().get("suggestions", []):
        pred = suggestion.get("placePrediction")
        if not pred:
            continue
        types = pred.get("types") or []
        # Skip bare addresses/suburbs -- this field is for businesses.
        if types and not ({"establishment", "point_of_interest"} & set(types)):
            continue
        structured = pred.get("structuredFormat") or {}
        name = ((structured.get("mainText") or {}).get("text")) or ((pred.get("text") or {}).get("text")) or ""
        secondary = (structured.get("secondaryText") or {}).get("text", "")
        if not name:
            continue
        results.append({
            "name": name,
            "category": _google_category(types),
            "location": _location_from_secondary(secondary),
            "full_address": secondary or (pred.get("text") or {}).get("text", ""),
            "place_id": pred.get("placeId"),
            "source": "google",
        })
        if len(results) >= limit:
            break
    return results


def place_details(place_id: str, session: str | None = None) -> dict | None:
    """Called once when someone picks a Google suggestion: exact suburb/city
    and category for the autofill. Passing the same session token as the
    autocomplete calls closes the billing session. Never raises."""
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key or not isinstance(place_id, str) or not _PLACE_ID_RE.match(place_id):
        return None
    params = {}
    if session:
        params["sessionToken"] = session
    try:
        resp = requests.get(
            _GOOGLE_DETAILS_URL.format(place_id=place_id),
            params=params,
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _GOOGLE_DETAILS_FIELDS},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            _record_google_error(f"Place Details: {_google_error(resp)}")
            logger.warning("Google Place Details failed: %s", _google_error(resp))
            return None
        data = resp.json()
    except Exception as exc:
        logger.warning("Google Place Details failed: %s", exc)
        return None

    comps = data.get("addressComponents") or []

    def find(*wanted, short=False):
        for w in wanted:
            for c in comps:
                if w in (c.get("types") or []):
                    return c.get("shortText" if short else "longText") or ""
        return ""

    area = find("locality", "postal_town", "sublocality", "administrative_area_level_2")
    state = find("administrative_area_level_1", short=True)
    location = ", ".join(p for p in (area, state) if p)
    return {
        "location": location,
        "category": _google_category(data.get("types") or []),
        "full_address": data.get("shortFormattedAddress", ""),
    }


def google_places_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_PLACES_API_KEY"))


_REGION_RE = re.compile(r"^[A-Za-z]{2}$")


def search_places(query: str, limit: int = DEFAULT_LIMIT,
                   lat: float | None = None, lon: float | None = None,
                   session: str | None = None, region: str | None = None) -> list[dict]:
    """Look up business-name suggestions. Never raises -- worst case is [].

    `lat`/`lon`, when given, bias results toward that point -- pass the
    geocoded coordinates of whatever the user has already typed into the
    Location field so "nene chicken" ranks the branch actually near them
    above unrelated branches on the other side of the world.

    Google results are never cached here: Google's terms only allow caching
    place IDs, and each keystroke is already covered by the session token.
    Only the free OSM path uses the short in-memory cache."""
    query = (query or "").strip()
    if len(query) < 3 or len(query) > MAX_QUERY_LEN:
        return []

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if api_key:
        try:
            region = region if region and _REGION_RE.match(region) else None
            results = _search_google(query, api_key, limit, lat=lat, lon=lon, session=session, region=region)
            if results:
                return results
            # Zero Google matches: fall through to OSM -- occasionally it has
            # a small place Google doesn't, and it costs nothing to ask.
        except Exception as exc:
            logger.warning("Google Places autocomplete failed, falling back: %s", exc)

    bias_key = f"{round(lat, 2)},{round(lon, 2)}" if lat is not None and lon is not None else "nobias"
    cache_key = f"{query.lower()}|{limit}|{bias_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        results = _search_photon(query, limit, lat=lat, lon=lon)
    except Exception as exc:
        logger.warning("Photon autocomplete failed: %s", exc)
        return []  # a failed lookup is never cached -- retry on the next keystroke

    # A completed lookup -- including a genuine zero-result answer -- is cached.
    _cache_set(cache_key, results)
    return results


# ---------- Google profile benchmark (Places API (New) Text Search) ----------
#
# Looks up the business and its most-named competitors on Google Maps and
# compares the things assistants demonstrably lean on: rating, number of
# reviews, primary category, whether a website is listed, weekend hours.
# Uses Enterprise-tier fields (rating, reviews, hours, website), so it's
# only run for subscriber checks (see pipeline `profile_benchmark=`).

_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_PROFILE_FIELDS = ",".join([
    "places.id", "places.displayName", "places.rating", "places.userRatingCount",
    "places.primaryTypeDisplayName", "places.websiteUri", "places.googleMapsUri",
    "places.businessStatus", "places.regularOpeningHours.weekdayDescriptions",
    "places.formattedAddress",
])
_SAMPLE_PREFIX = "sample rival"
_last_google_error: dict = {"message": None, "at": None}


def _record_google_error(message: str | None) -> None:
    _last_google_error["message"] = message
    _last_google_error["at"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()) if message else None


def google_status() -> dict:
    """For /healthz: which business-search backend is active and the last
    Google error, if any (e.g. "API not enabled", "billing not enabled")."""
    return {
        "business_search": "google" if google_places_enabled() else "openstreetmap (no GOOGLE_PLACES_API_KEY)",
        "last_google_error": _last_google_error["message"],
        "last_google_error_at": _last_google_error["at"],
    }


def _open_on(descriptions: list[str], day: str) -> bool | None:
    for d in descriptions or []:
        if d.lower().startswith(day):
            return "closed" not in d.lower()
    return None


def _lookup_profile(name: str, location: str, context: dict | None, api_key: str) -> dict:
    from ai_visibility.analyzer import names_match
    body: dict = {"textQuery": f"{name} {location}".strip(), "pageSize": 3}
    if context and context.get("lat") is not None and context.get("lon") is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": context["lat"], "longitude": context["lon"]},
                                           "radius": 30000.0}}
    if context and context.get("country"):
        body["regionCode"] = context["country"]
    resp = requests.post(
        _TEXT_SEARCH_URL, json=body, timeout=8,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _PROFILE_FIELDS, "Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        msg = _google_error(resp)
        _record_google_error(f"Text Search: {msg}")
        raise RuntimeError(msg)
    for place in resp.json().get("places") or []:
        google_name = (place.get("displayName") or {}).get("text", "")
        if not names_match(google_name, name):
            continue  # a different business -- don't compare against the wrong listing
        hours = (place.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
        return {
            "name": name, "found": True, "google_name": google_name,
            "rating": place.get("rating"), "reviews": place.get("userRatingCount") or 0,
            "category": (place.get("primaryTypeDisplayName") or {}).get("text", ""),
            "website": bool(place.get("websiteUri")), "maps_url": place.get("googleMapsUri"),
            "status": place.get("businessStatus"), "address": place.get("formattedAddress", ""),
            "hours_listed": bool(hours),
            "open_sat": _open_on(hours, "saturday"), "open_sun": _open_on(hours, "sunday"),
        }
    return {"name": name, "found": False}


def profile_benchmark(business: str, location: str, top_competitors: list, competitors: list[str],
                      context: dict | None = None, max_competitors: int = 4) -> dict:
    from ai_visibility.analyzer import names_match
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        return {"available": False, "reason": "no_key"}

    names: list[str] = []
    for n in [c for c, _ in top_competitors] + list(competitors):
        if not n or n.lower().startswith(_SAMPLE_PREFIX) or names_match(n, business):
            continue
        if any(names_match(n, x) for x in names):
            continue
        names.append(n)
        if len(names) >= max_competitors:
            break

    from concurrent.futures import ThreadPoolExecutor
    def safe(n):
        try:
            return _lookup_profile(n, location, context, api_key)
        except Exception as exc:
            return {"name": n, "found": False, "error": str(exc)[:160]}
    with ThreadPoolExecutor(max_workers=5) as ex:
        profiles = list(ex.map(safe, [business] + names))
    if all(p.get("error") for p in profiles):
        return {"available": False, "reason": "error", "error": profiles[0]["error"]}
    _record_google_error(None)
    return {"available": True, "you": profiles[0], "competitors": profiles[1:]}
