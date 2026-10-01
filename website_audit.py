"""
Website AI-readiness check: can AI assistants (and the search engines they
lean on) read this business's website, and does it clearly say who the
business is, what it does, where, and when?

What's checked, and why -- grounded in what the providers actually say:
  - AI *search* crawlers allowed in robots.txt: OAI-SearchBot (ChatGPT
    search), Claude-SearchBot (Claude search), PerplexityBot (Perplexity),
    plus Googlebot and Bingbot. Blocking these hides the site from those
    answers. *Training* crawlers (GPTBot, ClaudeBot, Google-Extended) are
    reported for information only -- each provider documents that blocking
    them does not affect search answers, so that's the owner's choice.
  - Not marked noindex, reachable, HTTPS.
  - The basics stated in text: business name, suburb, what you do, phone,
    opening hours -- Google says AI features need nothing special beyond
    "content in text form" and accurate business information, so this is
    the core.
  - Structured data (LocalBusiness JSON-LD): helps assistants confirm
    details; Google is explicit that it isn't *required*, so it's weighted
    as helpful, not critical. llms.txt is not checked as a requirement for
    the same reason (no major assistant says it uses it for ranking).

Safety: this fetches a URL a visitor typed, so it must never become a way
to make our server reach internal addresses. Every hop (including
redirects) is resolved and refused if it points at a private, loopback,
link-local or otherwise non-public IP; only ports 80/443; capped size and
time.
"""

from __future__ import annotations
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests

TIMEOUT = 8
MAX_BYTES = 2_500_000
MAX_REDIRECTS = 5
UA = "Mozilla/5.0 (compatible; AIVisibilityMonitor/1.0; website check)"

SEARCH_BOTS = [  # blocking these hides you from AI/search answers
    ("OAI-SearchBot", "ChatGPT search"),
    ("Claude-SearchBot", "Claude search"),
    ("PerplexityBot", "Perplexity"),
    ("Googlebot", "Google Search & Gemini"),
    ("Bingbot", "Bing & ChatGPT"),
]
TRAINING_BOTS = [  # owner's choice; doesn't affect search answers
    ("GPTBot", "OpenAI model training"),
    ("ClaudeBot", "Anthropic model training"),
    ("Google-Extended", "Google AI training"),
]


class UnsafeURL(ValueError):
    pass


def normalize_site_url(text: str) -> str | None:
    t = (text or "").strip()
    if not t or len(t) > 500 or " " in t:
        return None
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t
    u = urlparse(t)
    if u.scheme not in ("http", "https") or not u.hostname or "." not in u.hostname:
        return None
    return t


def _check_host(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise UnsafeURL("Only http(s) websites can be checked.")
    port = u.port or (443 if u.scheme == "https" else 80)
    if port not in (80, 443):
        raise UnsafeURL("Only standard web ports can be checked.")
    host = u.hostname or ""
    if host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
        raise UnsafeURL("That address isn't a public website.")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURL("That website's address doesn't exist (DNS lookup failed).")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL("That address isn't a public website.")


def safe_get(url: str, accept: str = "text/html,*/*") -> tuple[requests.Response | None, str, bytes]:
    """GET with SSRF guards on every hop. Returns (response, final_url, body)."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_host(current)
        resp = requests.get(current, allow_redirects=False, timeout=TIMEOUT, stream=True,
                            headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en"})
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
            resp.close()
            current = urljoin(current, resp.headers["Location"])
            continue
        body = b""
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                break
        resp.close()
        return resp, current, body
    raise UnsafeURL("Too many redirects.")


# ---------- page parsing helpers ----------

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.S | re.I)
_LDJSON_RE = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_DAY_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b|\b\d{1,2}:\d{2}\b", re.I)
_NON_BUSINESS_TYPES = {"website", "webpage", "breadcrumblist", "imageobject", "searchaction", "sitenavigationelement",
                       "wpheader", "wpfooter", "readaction", "listitem", "person", "videoobject", "article", "blogposting"}


def _meta(html: str, name: str) -> str | None:
    n = re.escape(name)
    m = re.search(r"<meta[^>]+(?:name|property)=[\"']?%s[\"']?[^>]*content=(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))" % n, html, re.I) \
        or re.search(r"<meta[^>]+content=(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))[^>]*(?:name|property)=[\"']?%s\b" % n, html, re.I)
    if not m:
        return None
    return next((g for g in m.groups() if g is not None), "").strip()


def _visible_text(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


def _jsonld_types(html: str) -> tuple[list[str], list[dict]]:
    types, objs = [], []

    def walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            for x in (t if isinstance(t, list) else [t]):
                if isinstance(x, str):
                    types.append(x)
                    objs.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for raw in _LDJSON_RE.findall(html):
        try:
            walk(json.loads(raw.strip()))
        except Exception:
            continue
    return types, objs


# ---------- the audit ----------

def audit_website(url_text: str, business: str = "", location: str = "", category: str = "") -> dict:
    """Never raises. Returns {"ok": bool, "url", "final_url", "score",
    "checks": [{key,label,status,detail,fix,weight}], "error"}."""
    url = normalize_site_url(url_text)
    if not url:
        return {"ok": False, "url": url_text, "error": "That doesn't look like a website address."}
    try:
        resp, final_url, body = safe_get(url)
    except UnsafeURL as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    except requests.exceptions.SSLError:
        return {"ok": False, "url": url, "error": "The website's security certificate is broken -- browsers and AI crawlers will warn or refuse."}
    except requests.exceptions.Timeout:
        return {"ok": False, "url": url, "error": "The website took too long to respond (over 8 seconds)."}
    except Exception:
        return {"ok": False, "url": url, "error": "Couldn't reach the website."}

    checks: list[dict] = []

    def add(key, label, ok, detail, fix, weight, status=None):
        checks.append({"key": key, "label": label, "status": status or ("pass" if ok else "fail"),
                       "detail": detail, "fix": "" if (status or ("pass" if ok else "fail")) == "pass" else fix,
                       "weight": weight})

    status = resp.status_code
    add("reachable", "Website loads", status == 200, f"Responded with HTTP {status}.",
        "Fix the error so the homepage loads -- crawlers drop sites that fail.", 10)
    if status != 200:
        return _finish(url, final_url, checks)

    html = body.decode(resp.encoding or "utf-8", errors="replace")
    text = _visible_text(html)
    low_text = text.lower()
    words = len(text.split())

    add("https", "Secure (HTTPS)", final_url.lower().startswith("https://"),
        "Served over HTTPS." if final_url.lower().startswith("https://") else "Served over plain HTTP.",
        "Turn on HTTPS (most hosts offer it free).", 4)

    robots_meta = (_meta(html, "robots") or "").lower()
    x_robots = (resp.headers.get("X-Robots-Tag") or "").lower()
    noindex = "noindex" in robots_meta or "noindex" in x_robots
    add("indexable", "Not hidden from search", not noindex,
        "The page tells search engines not to index it (noindex)." if noindex else "No noindex directive.",
        "Remove the noindex tag -- right now search engines and AI search are told to ignore this page.", 10)

    # robots.txt
    parsed = urlparse(final_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    blocked_search, blocked_training, robots_found = [], [], False
    try:
        r_resp, _, r_body = safe_get(root + "/robots.txt", accept="text/plain,*/*")
        if r_resp is not None and r_resp.status_code == 200 and len(r_body) < 500_000:
            robots_found = True
            rp = RobotFileParser()
            rp.parse(r_body.decode("utf-8", errors="replace").splitlines())
            for bot, what in SEARCH_BOTS:
                if not rp.can_fetch(bot, final_url):
                    blocked_search.append(f"{bot} ({what})")
            for bot, what in TRAINING_BOTS:
                if not rp.can_fetch(bot, final_url):
                    blocked_training.append(f"{bot} ({what})")
    except Exception:
        pass
    add("ai_crawlers", "AI search crawlers allowed", not blocked_search,
        ("Blocked in robots.txt: " + ", ".join(blocked_search)) if blocked_search
        else ("robots.txt allows the AI search crawlers." if robots_found else "No robots.txt -- everything is allowed."),
        "Allow these in robots.txt -- while blocked, those assistants can't show or cite your site.", 10)
    if blocked_training:
        add("training_crawlers", "AI training crawlers", True,
            "Blocked (your choice -- doesn't affect search answers): " + ", ".join(blocked_training), "", 0, status="info")

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", _TAG_RE.sub("", title_m.group(1))).strip() if title_m else ""
    from ai_visibility.analyzer import _search, _normalize  # same forgiving name matching as answers
    name_in_title = bool(business) and _search(_normalize(title), business) is not None
    add("title", "Page title names the business", bool(title) and (name_in_title or not business),
        f"Title: “{title[:90]}”" if title else "No <title> tag.",
        f"Use a title like “{business or 'Business name'} | {category or 'what you do'} in {location or 'your suburb'}”.", 5)

    desc = _meta(html, "description") or _meta(html, "og:description")
    add("description", "Meta description", bool(desc),
        f"“{desc[:110]}”" if desc else "No meta description.",
        "Add a one-sentence description: what you do, where, and what makes you different.", 2)

    if business:
        name_on_page = _search(_normalize(text), business) is not None
        add("name", "Business name in page text", name_on_page,
            "Name appears in the page text." if name_on_page else "The business name isn't in the visible text (maybe only in a logo image).",
            "Write the business name in plain text (heading or intro), not only in the logo.", 6)

    suburb = (location or "").split(",")[0].strip()
    if suburb:
        loc_ok = suburb.lower() in low_text
        add("location", "Suburb/area mentioned", loc_ok,
            f"“{suburb}” appears on the page." if loc_ok else f"“{suburb}” isn't mentioned on the homepage.",
            f"Say where you are and the areas you serve in text (e.g. “{category or 'Service'} in {suburb} and nearby suburbs”).", 7)

    if category:
        cat_words = [w for w in re.findall(r"[a-z]{4,}", category.lower()) if w not in ("shop", "store", "service", "services", "restaurant", "centre", "center")] \
            or re.findall(r"[a-z]{4,}", category.lower())
        does = any(w[:6] in low_text for w in cat_words)
        add("services", "Says what you do", does,
            "The page describes your type of business." if does else f"Words like “{category}” don't appear on the homepage.",
            f"Describe your services in plain words customers use (“{category}”), ideally a section per main service.", 6)

    has_tel = "tel:" in html.lower() or bool(_PHONE_RE.search(text))
    add("phone", "Phone number visible", has_tel,
        "Phone number found." if has_tel else "No phone number found on the homepage.",
        "Show your phone number as text with a tap-to-call link.", 5)

    types, objs = _jsonld_types(html)
    business_types = [t for t in types if t.lower() not in _NON_BUSINESS_TYPES]
    hours_schema = any(("openingHours" in o or "openingHoursSpecification" in o) for o in objs)
    hours_text = len(_DAY_RE.findall(text)) >= 2 and bool(_TIME_RE.search(text))
    add("hours", "Opening hours on the site", hours_schema or hours_text,
        "Opening hours found." if (hours_schema or hours_text) else "No opening hours found on the homepage.",
        "List your opening hours in text (and keep them identical to Google).", 5)

    lb = [t for t in business_types if t.lower() not in ("organization", "corporation")]
    add("schema", "Business structured data", bool(lb),
        ("Structured data: " + ", ".join(sorted(set(lb))[:4])) if lb
        else ("Only generic Organization data found." if business_types else "No LocalBusiness structured data (JSON-LD)."),
        "Add LocalBusiness (or the specific type, e.g. Dentist, Restaurant) JSON-LD with name, address, phone, hours. "
        "Not required, but it helps assistants confirm your details.", 4,
        status=None if lb else ("warn" if business_types else "fail"))

    js_heavy = words < 120 and html.lower().count("<script") >= 5
    add("content", "Enough readable text", words >= 150,
        f"About {words} words of readable text." + (" Most content seems to load via JavaScript, which many AI crawlers don't run." if js_heavy else ""),
        "Add a few paragraphs of real text: services, area, prices, FAQs. Many AI crawlers don't run JavaScript, so text must be in the HTML.", 6)

    faq = "faqpage" in [t.lower() for t in types] or bool(re.search(r"frequently asked|\bfaqs?\b", low_text))
    add("faq", "Answers common questions", faq,
        "FAQ content found." if faq else "No FAQ section found.",
        "Add an FAQ answering what customers ask (prices, hours, areas, urgent jobs) -- assistants quote these answers.", 3,
        status=None if faq else "warn")

    viewport = bool(re.search(r"<meta[^>]+name=[\"']?viewport", html, re.I))
    add("mobile", "Mobile-friendly setup", viewport, "Viewport tag present." if viewport else "No mobile viewport tag.",
        "Add a responsive viewport tag / mobile-friendly theme.", 2)

    return _finish(url, final_url, checks)


def _finish(url: str, final_url: str, checks: list[dict]) -> dict:
    scored = [c for c in checks if c["weight"]]
    total = sum(c["weight"] for c in scored) or 1
    earned = sum(c["weight"] * (1 if c["status"] == "pass" else 0.5 if c["status"] == "warn" else 0) for c in scored)
    order = {"fail": 0, "warn": 1, "info": 2, "pass": 3}
    checks.sort(key=lambda c: (order[c["status"]], -c["weight"]))
    return {"ok": True, "url": url, "final_url": final_url, "score": round(100 * earned / total), "checks": checks}
