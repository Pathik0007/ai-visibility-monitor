"""
Business-name autocomplete for the "Business name" field.

Same demo-mode philosophy as ai_visibility/providers/: works out of the box
with zero setup, and upgrades automatically to Google Places if
GOOGLE_PLACES_API_KEY is set in .env.

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


def _map_osm_props_category(props: dict) -> str:
    osm_value = props.get("osm_value", "")
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


def _search_photon(query: str, limit: int, lat: float | None = None, lon: float | None = None) -> list[dict]:
    params = {"q": query, "limit": limit, "lang": "en"}
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
        results.append({
            "name": name,
            "category": _map_osm_props_category(props),
            "location": _format_photon_location(props),
            "full_address": _format_photon_address(props),
        })
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
    return {"lat": lat, "lon": lon}


def _geocode_google(location_text: str, api_key: str) -> dict | None:
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": location_text, "key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    loc = data["results"][0]["geometry"]["location"]
    return {"lat": loc["lat"], "lon": loc["lng"]}


def geocode_location(location_text: str) -> dict | None:
    """Best-effort: turn free-text like "Parramatta, Sydney" into a
    lat/lon so the business-name search below can be biased toward it.
    Never raises -- a failure here should just mean an unbiased (global)
    name search, not a broken page."""
    location_text = (location_text or "").strip()
    if len(location_text) < 3 or len(location_text) > MAX_QUERY_LEN:
        return None

    cache_key = f"geocode|{location_text.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or None  # cached `{}` means "looked up, found nothing"

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    result = None
    succeeded = False
    if api_key:
        try:
            result = _geocode_google(location_text, api_key)
            succeeded = True
        except Exception as exc:
            logger.warning("Google geocoding failed, falling back: %s", exc)
    if not succeeded:
        try:
            result = _geocode_photon(location_text)
            succeeded = True
        except Exception as exc:
            logger.warning("Photon geocoding failed: %s", exc)

    # Only cache a lookup that actually completed -- including a genuine
    # "nothing there" answer from a successful call. Caching a *failure*
    # (timeout, rate limit, transient network blip) as if it were a real
    # empty result would silently suppress every retry for the next 5
    # minutes, even once the provider recovers.
    if succeeded:
        _cache_set(cache_key, result or {})
    return result


def _map_google_types(types: list[str]) -> str:
    for t in types or []:
        if t not in _GENERIC_TYPES:
            return _humanize(t)
    return ""


def _search_google(query: str, api_key: str, limit: int, lat: float | None = None, lon: float | None = None) -> list[dict]:
    params = {"input": query, "key": api_key, "types": "establishment"}
    if lat is not None and lon is not None:
        # "Bias", not "restrict": a strict location+radius filter would hide
        # a real result just outside an arbitrary radius; this only pushes
        # nearby matches higher, the same intent as Photon's lat/lon above.
        params["location"] = f"{lat},{lon}"
        params["radius"] = 50000
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/place/autocomplete/json",
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise RuntimeError(f"Google Places autocomplete error: {status}")
    results = []
    for pred in data.get("predictions", [])[:limit]:
        structured = pred.get("structured_formatting", {})
        results.append({
            "name": structured.get("main_text") or pred.get("description", ""),
            "category": _map_google_types(pred.get("types") or []),
            "location": structured.get("secondary_text", ""),
            "full_address": pred.get("description", ""),
        })
    return results


def search_places(query: str, limit: int = DEFAULT_LIMIT,
                   lat: float | None = None, lon: float | None = None) -> list[dict]:
    """Look up business-name suggestions. Never raises -- worst case is [].

    `lat`/`lon`, when given, bias results toward that point -- pass the
    geocoded coordinates of whatever the user has already typed into the
    Location field so "nene chicken" ranks the branch actually near them
    above unrelated branches on the other side of the world."""
    query = (query or "").strip()
    if len(query) < 3 or len(query) > MAX_QUERY_LEN:
        return []

    bias_key = f"{round(lat, 2)},{round(lon, 2)}" if lat is not None and lon is not None else "nobias"
    cache_key = f"{query.lower()}|{limit}|{bias_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    results: list[dict] = []
    succeeded = False

    if api_key:
        try:
            results = _search_google(query, api_key, limit, lat=lat, lon=lon)
            succeeded = True
        except Exception as exc:
            logger.warning("Google Places autocomplete failed, falling back: %s", exc)
            results = []

    if not succeeded:
        try:
            results = _search_photon(query, limit, lat=lat, lon=lon)
            succeeded = True
        except Exception as exc:
            logger.warning("Photon autocomplete failed: %s", exc)
            results = []

    # As above: only cache a completed lookup. A real zero-result answer
    # (query succeeded, nothing matched -- e.g. a small business that just
    # isn't in this provider's database) is worth caching; a failed request
    # is not, or one Photon blip would hide results for 5 minutes afterward.
    if succeeded:
        _cache_set(cache_key, results)
    return results
