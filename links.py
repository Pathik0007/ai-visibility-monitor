"""
Turn a pasted Google Maps / Google Business Profile link into business
details (name, category, suburb) -- for the Business and Competitor fields.

Handles every shape Google hands out:
  - long Maps URLs      google.com/maps/place/Ace's+Deep+Sea+Food/@-33.79,151.12,17z/data=...!3d-33.79!4d151.12
  - Share-button links  maps.app.goo.gl/xxxx, goo.gl/maps/xxxx
  - Business Profile    g.page/<name>, g.co/kgs/xxxx, share.google/xxxx
  - search / query      google.com/maps?q=Name, Address   google.com/search?q=Name+Suburb
  - place IDs           ...?query_place_id=ChIJ...        ...?q=place_id:ChIJ...

Short links are expanded by following redirects ourselves, one hop at a
time, and only ever to Google-owned hosts (never an arbitrary URL -- this
endpoint must not become a way to make our server fetch anything). A
cookie-consent interstitial (consent.google.com?continue=...) is unwrapped.

With GOOGLE_PLACES_API_KEY the place is then looked up in Places API (New)
for the exact name/category/suburb; without it, the name comes from the
link and the suburb from the link's coordinates (free OpenStreetMap reverse
geocoding), with the category matched from OSM or guessed from the name.
"""

from __future__ import annotations
import os
import re
import logging
from urllib.parse import urlparse, parse_qs, unquote_plus, urljoin

import time

import requests

import safe_http

logger = logging.getLogger(__name__)

TIMEOUT = 5
MAX_REDIRECTS = 6
_UA = "Mozilla/5.0 (compatible; AI-Visibility-Monitor/1.0; +link-resolver)"

_SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl", "g.page", "g.co", "share.google", "maps.google.com"}
_GOOGLE_HOST_RE = re.compile(r"^(?:[a-z0-9-]+\.)*google\.(?:com|[a-z]{2}|com?\.[a-z]{2})$")


def is_google_host(host: str) -> bool:
    """`host` must be a bare hostname (urlparse(...).hostname). A netloc
    such as "maps.google.com:@169.254.169.254" is rejected: the part before
    "@" is a username, and the real host is the address after it."""
    host = (host or "").lower().rstrip(".")
    if "@" in host or ":" in host:
        return False
    return host in _SHORT_HOSTS or bool(_GOOGLE_HOST_RE.match(host))


def is_google_url(url: str) -> bool:
    try:
        u = urlparse(url)
        port = u.port
    except ValueError:
        return False
    return (u.scheme in ("http", "https") and u.username is None and u.password is None
            and "@" not in u.netloc and port in (None, 80, 443) and is_google_host(u.hostname or ""))


def looks_like_link(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(re.match(r"^(https?://)?([a-z0-9-]+\.)*(google\.[a-z.]+|goo\.gl|g\.page|g\.co|share\.google)/", t))


def normalize_url(text: str) -> str | None:
    t = (text or "").strip()
    if not t or len(t) > 2000:
        return None
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t
    return t if is_google_url(t) else None


def expand(url: str) -> str:
    """Follow redirects hop by hop, staying on Google hosts."""
    current = url
    for _ in range(MAX_REDIRECTS):
        u = urlparse(current)
        if (u.hostname or "").startswith("consent.google."):
            cont = parse_qs(u.query).get("continue", [None])[0]
            if cont and is_google_url(cont):
                current = cont
                continue
            break
        if _parse(current).get("name") or _parse(current).get("place_id"):
            return current  # already informative, no need to fetch
        if not is_google_url(current):
            raise ValueError("That link redirects outside Google.")
        # One hop at a time through the SSRF-guarded client (public IPs only,
        # resolved once at connect time).
        resp, _final, _ = safe_http.fetch(current, headers={"User-Agent": _UA, "Accept-Language": "en"},
                                          max_redirects=0, read_body=False,
                                          deadline=time.monotonic() + TIMEOUT + 1)
        loc = resp.headers.get("Location")
        if resp.status_code in (301, 302, 303, 307, 308) and loc:
            nxt = urljoin(current, loc)
            if not is_google_url(nxt):
                raise ValueError("That link redirects outside Google.")
            current = nxt
            continue
        break
    return current


_COORD_DATA_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_COORD_AT_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_PLACE_ID_RE = re.compile(r"(ChIJ[0-9A-Za-z_-]{10,})")


def _parse(url: str) -> dict:
    u = urlparse(url)
    qs = parse_qs(u.query)
    path = unquote_plus(u.path)
    out: dict = {}

    m = re.search(r"/maps/place/([^/@]+)", path)
    if m:
        out["name"] = m.group(1).strip()
    else:
        m = re.search(r"/maps/search/([^/@]+)", path)
        if m:
            out["query"] = m.group(1).strip()
    for key in ("q", "query"):
        v = (qs.get(key) or [None])[0]
        if v:
            if v.startswith("place_id:"):
                out["place_id"] = v.split(":", 1)[1]
            elif "name" not in out and not re.match(r"^-?\d+(\.\d+)?,\s*-?\d+(\.\d+)?$", v):
                out["query"] = v.strip()
            elif re.match(r"^-?\d+(\.\d+)?,\s*-?\d+(\.\d+)?$", v):
                lat, lon = v.split(",")
                out.setdefault("lat", float(lat)); out.setdefault("lon", float(lon))
    pid = (qs.get("query_place_id") or qs.get("place_id") or [None])[0]
    if pid:
        out["place_id"] = pid
    else:
        m = _PLACE_ID_RE.search(url)
        if m and "place_id" not in out:
            out["place_id"] = m.group(1)
    m = _COORD_DATA_RE.search(url) or _COORD_AT_RE.search(url)
    if m:
        out["lat"], out["lon"] = float(m.group(1)), float(m.group(2))
    # g.page/<business-slug> -- the slug is the name when nothing better exists
    if (u.hostname or "") == "g.page" and "name" not in out:
        slug = path.strip("/").split("/")[0]
        if slug and not slug.startswith("r/"):
            out["slug"] = slug.replace("-", " ")
    return out


def _split_name_address(text: str) -> tuple[str, str]:
    """"Ace's Deep Sea Food, 1 Coxs Rd, North Ryde NSW 2113" -> name + rest."""
    parts = [p.strip() for p in text.split(",")]
    return parts[0], ", ".join(parts[1:])


# ---------- resolution ----------

def _google_lookup(info: dict, api_key: str) -> dict | None:
    fields = "id,displayName,types,primaryType,addressComponents,location,shortFormattedAddress,websiteUri"
    headers = {"X-Goog-Api-Key": api_key, "Content-Type": "application/json"}
    place = None
    if info.get("place_id") and re.fullmatch(r"[A-Za-z0-9_-]{10,400}", info["place_id"]):
        r = requests.get(f"https://places.googleapis.com/v1/places/{info['place_id']}", timeout=TIMEOUT,
                         headers={**headers, "X-Goog-FieldMask": fields})
        if r.status_code == 200:
            place = r.json()
    if place is None and info.get("text"):
        body: dict = {"textQuery": info["text"], "pageSize": 3}
        if info.get("lat") is not None:
            body["locationBias"] = {"circle": {"center": {"latitude": info["lat"], "longitude": info["lon"]},
                                               "radius": 500.0}}
        r = requests.post("https://places.googleapis.com/v1/places:searchText", json=body, timeout=TIMEOUT,
                          headers={**headers, "X-Goog-FieldMask": ",".join("places." + f for f in fields.split(","))})
        if r.status_code == 200:
            cands = r.json().get("places") or []
            from ai_visibility.analyzer import names_match
            place = next((p for p in cands if names_match((p.get("displayName") or {}).get("text", ""), info.get("name") or info["text"])), None) \
                or (cands[0] if cands else None)
        else:
            import places as _p
            _p._record_google_error(f"Link lookup: {_p._google_error(r)}")
    if not place:
        return None
    import places as _p
    comps = place.get("addressComponents") or []

    def find(*wanted, short=False):
        for w in wanted:
            for c in comps:
                if w in (c.get("types") or []):
                    return c.get("shortText" if short else "longText") or ""
        return ""
    area = find("locality", "postal_town", "sublocality", "administrative_area_level_2")
    state = find("administrative_area_level_1", short=True)
    loc = place.get("location") or {}
    return {
        "name": (place.get("displayName") or {}).get("text") or info.get("name") or info.get("text"),
        "category": _p._google_category([place.get("primaryType")] + (place.get("types") or []) if place.get("primaryType") else place.get("types") or []),
        "location": ", ".join(p for p in (area, state) if p),
        "full_address": place.get("shortFormattedAddress", ""),
        "lat": loc.get("latitude"), "lon": loc.get("longitude"),
        "country": find("country", short=True) or None,
        "website": place.get("websiteUri") or "",
        "source": "google",
    }


def _osm_reverse(lat: float, lon: float) -> dict | None:
    r = requests.get("https://photon.komoot.io/reverse", params={"lat": lat, "lon": lon, "lang": "en", "limit": 1},
                     timeout=TIMEOUT, headers={"User-Agent": "AI-Visibility-Monitor/1.0 (link resolver)"})
    r.raise_for_status()
    feats = r.json().get("features") or []
    if not feats:
        return None
    p = feats[0].get("properties") or {}
    import places as _p
    area = p.get("district") or p.get("locality") or p.get("city") or ""
    return {"location": ", ".join(x for x in (area, _p._short_state(p.get("state", ""), p.get("countrycode"))) if x),
            "country": (p.get("countrycode") or "").upper() or None}


def _guess_category(name: str) -> str:
    from categories import guess_from_name
    return guess_from_name(name)


def _free_lookup(info: dict) -> dict:
    import places as _p
    from ai_visibility.analyzer import names_match
    name = info.get("name") or info.get("text") or ""
    result = {"name": name, "category": "", "location": "", "full_address": "", "source": "link",
              "lat": info.get("lat"), "lon": info.get("lon"), "country": None}
    if (info.get("address") or "").strip(" ,"):
        result["full_address"] = info["address"].strip(" ,")
    if info.get("lat") is not None:
        try:
            rev = _osm_reverse(info["lat"], info["lon"])
            if rev:
                result.update({k: v for k, v in rev.items() if v})
        except Exception as exc:
            logger.warning("Reverse geocode failed: %s", exc)
    try:  # OSM may know this exact place and its category
        for c in _p._search_photon(name, 10, info.get("lat"), info.get("lon")):
            if names_match(c["name"], name):
                result["category"] = c["category"]
                if not result["location"]:
                    result["location"] = c["location"]
                break
    except Exception as exc:
        logger.warning("Photon name lookup failed: %s", exc)
    if not result["category"]:
        result["category"] = _guess_category(name)
    if not result["location"] and info.get("address"):
        parts = [p.strip() for p in info["address"].split(",") if p.strip()]
        if len(parts) >= 2 and re.fullmatch(r"[A-Za-z .]+", parts[-1]) and len(parts[-1].split()) <= 3 \
                and not re.search(r"\b[A-Z]{2,3}\b", parts[-1]):
            parts = parts[:-1]  # drop a trailing country ("Australia")
        if parts:
            result["location"] = re.sub(r"\s+\d{3,5}$", "", parts[-1]).strip()
    if not result["location"] and info.get("place"):
        result["location"] = info["place"]
    return result


def resolve_link(text: str) -> dict:
    """Returns {"ok": True, name, category, location, ...} or
    {"ok": False, "error": "..."}. Never raises."""
    try:
        return _resolve_link(text)
    except Exception:
        logger.exception("resolve_link failed")
        return {"ok": False, "error": "Couldn't read that link -- type the business name instead."}


def _resolve_link(text: str) -> dict:
    url = normalize_url(text)
    if not url:
        return {"ok": False, "error": "That isn't a Google Maps link. In Google Maps, open the business, tap Share, then Copy link."}
    try:
        final = expand(url)
    except safe_http.UnsafeURL:
        return {"ok": False, "error": "That link can't be opened."}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("Link expand failed: %s", exc)
        if not any(_parse(url).get(k) for k in ("name", "query", "slug", "place_id")):
            return {"ok": False, "error": "Couldn't open that link right now -- try again, or type the name instead."}
        final = url  # the link itself still tells us enough

    info = _parse(final)
    if info.get("name"):
        info["text"] = info["name"]
    elif info.get("query"):
        name, address = _split_name_address(info["query"])
        if not address:
            # "sparkle car wash ryde" -> name "sparkle car wash", place "Ryde"
            try:
                import search_engine
                split = search_engine.split_place_hint(name, None)
                if split:
                    info["place"] = (split[1].get("name") or split[1].get("city") or "").strip()
                    name = split[0]
            except Exception:
                pass
        if name.islower():
            name = name.title().replace("'S ", "'s ")
        info.update(name=name, address=address, text=info["query"])
    elif info.get("slug"):
        info.update(name=info["slug"].title(), text=info["slug"])

    if not (info.get("text") or info.get("place_id")):
        return {"ok": False, "error": "That link doesn't say which business it is. Use the Share button on the business's own Google Maps page."}

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    result = None
    if api_key:
        try:
            result = _google_lookup(info, api_key)
        except Exception as exc:
            logger.warning("Google link lookup failed: %s", exc)
    if result is None:
        if not info.get("text"):
            return {"ok": False, "error": "Reading this kind of link needs the Google Places connection -- type the name instead."}
        result = _free_lookup(info)
    result["name"] = re.sub(r"\s+", " ", result.get("name") or "").strip()
    if not result["name"]:
        return {"ok": False, "error": "Couldn't read a business name from that link."}
    result["ok"] = True
    return result
