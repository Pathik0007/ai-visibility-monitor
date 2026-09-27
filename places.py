"""
Business-name autocomplete for the "Business name" field.

Same demo-mode philosophy as ai_visibility/providers/: works out of the box
with zero setup (OpenStreetMap Nominatim, free, no key), and upgrades
automatically to Google Places if GOOGLE_PLACES_API_KEY is set in .env.

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
# and so we stay well within Nominatim's "no heavy use" usage policy.
_CACHE: dict[str, tuple[float, list[dict]]] = {}
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


def _map_osm_category(item: dict) -> str:
    extratags = item.get("extratags") or {}
    if extratags.get("cuisine"):
        return _humanize(extratags["cuisine"].split(";")[0])
    osm_type = item.get("type", "")
    if osm_type and osm_type not in _GENERIC_TYPES:
        return _humanize(osm_type)
    osm_class = item.get("class", "")
    return _humanize(osm_class) if osm_class else ""


def _format_osm_location(address: dict) -> str:
    if not address:
        return ""
    city = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("suburb") or address.get("municipality") or ""
    )
    region = address.get("state") or address.get("region") or ""
    parts = [p for p in (city, region) if p]
    return ", ".join(parts)


def _search_nominatim(query: str, limit: int) -> list[dict]:
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": query, "format": "jsonv2", "addressdetails": 1,
            "extratags": 1, "limit": limit,
        },
        headers={
            # Nominatim's usage policy requires an identifying User-Agent.
            "User-Agent": "AI-Visibility-Monitor/1.0 (business-name autocomplete)"
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    results = []
    for item in resp.json():
        name = item.get("namedetails", {}).get("name") or item.get("name") or item.get("display_name", "").split(",")[0]
        results.append({
            "name": name,
            "category": _map_osm_category(item),
            "location": _format_osm_location(item.get("address") or {}),
            "full_address": item.get("display_name", ""),
        })
    return results


def _map_google_types(types: list[str]) -> str:
    for t in types or []:
        if t not in _GENERIC_TYPES:
            return _humanize(t)
    return ""


def _search_google(query: str, api_key: str, limit: int) -> list[dict]:
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/place/autocomplete/json",
        params={"input": query, "key": api_key, "types": "establishment"},
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


def search_places(query: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Look up business-name suggestions. Never raises -- worst case is []."""
    query = (query or "").strip()
    if len(query) < 3 or len(query) > MAX_QUERY_LEN:
        return []

    cache_key = f"{query.lower()}|{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    results: list[dict] = []

    if api_key:
        try:
            results = _search_google(query, api_key, limit)
        except Exception as exc:
            logger.warning("Google Places autocomplete failed, falling back: %s", exc)
            results = []

    if not results:
        try:
            results = _search_nominatim(query, limit)
        except Exception as exc:
            logger.warning("Nominatim autocomplete failed: %s", exc)
            results = []

    _cache_set(cache_key, results)
    return results
