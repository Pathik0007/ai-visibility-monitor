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
import codecs
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from safe_http import UnsafeURL, check_url, fetch

TIMEOUT = 8
MAX_BYTES = 2_500_000
PARSE_BYTES = 800_000  # the facts we look for are near the top of a page
AUDIT_DEADLINE = 20    # seconds for the whole check (homepage + robots.txt)
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


def normalize_site_url(text: str) -> str | None:
    """'example.com.au' -> 'https://example.com.au'. None if it isn't a
    plausible public web address. Never raises."""
    t = (text or "").strip()
    if not t or len(t) > 480 or any(ch.isspace() for ch in t):
        return None
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t
    try:
        u = urlparse(t)
        u.port  # raises ValueError on a bad port
    except ValueError:
        return None
    if u.scheme.lower() not in ("http", "https") or not u.hostname or "." not in u.hostname:
        return None
    if u.username is not None or u.password is not None:
        return None
    return t


def _check_host(url: str) -> None:
    """Kept for callers/tests: static URL checks (DNS is checked at connect)."""
    check_url(url)


def safe_get(url: str, accept: str = "text/html,*/*", deadline: float | None = None):
    """GET with SSRF guards on every hop. Returns (response, final_url, body)."""
    return fetch(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en"},
                 max_bytes=MAX_BYTES, deadline=deadline)


# ---------- page parsing (linear-time: no backtracking regexes on HTML) ----------

_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_DAY_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b|\b\d{1,2}:\d{2}\b", re.I)
_NON_BUSINESS_TYPES = {"website", "webpage", "breadcrumblist", "imageobject", "searchaction", "sitenavigationelement",
                       "wpheader", "wpfooter", "readaction", "listitem", "person", "videoobject", "article", "blogposting"}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class _Page(HTMLParser):
    """One pass over the HTML collecting what the audit needs. Python's
    HTMLParser is linear and tolerant of broken markup, unlike the old
    regexes, which a hostile page could make take minutes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metas: list[dict] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.ldjson: list[str] = []
        self.script_count = 0
        self.has_tel = False
        self._stack: list[str] = []
        self._in_title = False
        self._ld = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs if k}
        if tag == "meta":
            self.metas.append(a)
        elif tag == "a" and a.get("href", "").strip().lower().startswith("tel:"):
            self.has_tel = True
        elif tag == "title" and not self._stack and not self.title_parts:
            self._in_title = True  # the page title only -- not an <svg><title>
        elif tag == "script":
            self.script_count += 1
            self._ld = "ld+json" in a.get("type", "").lower()
        if tag in _SKIP_TAGS:
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass
            if tag == "script":
                self._ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif self._stack:
            if self._stack[-1] == "script" and self._ld:
                self.ldjson.append(data)
        else:
            self.text_parts.append(data)

    def meta(self, name: str) -> str | None:
        name = name.lower()
        for m in self.metas:
            if (m.get("name") or m.get("property") or "").strip().lower() == name and "content" in m:
                return m["content"].strip()
        return None

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.title_parts)).strip()

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text_parts)).strip()


def parse_page(html: str) -> _Page:
    page = _Page()
    try:
        page.feed(html[:PARSE_BYTES])
        page.close()
    except Exception:
        pass  # whatever was collected before the parser gave up is still useful
    return page


def _meta(html: str, name: str) -> str | None:
    return parse_page(html).meta(name)


def _visible_text(html: str) -> str:
    return parse_page(html).text


def _jsonld_types(page_or_html) -> tuple[list[str], list[dict]]:
    page = page_or_html if isinstance(page_or_html, _Page) else parse_page(page_or_html)
    types, objs = [], []

    def walk(o, depth=0):
        if depth > 30:
            return
        if isinstance(o, dict):
            t = o.get("@type")
            for x in (t if isinstance(t, list) else [t]):
                if isinstance(x, str):
                    types.append(x)
                    objs.append(o)
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)

    for raw in page.ldjson:
        try:
            walk(json.loads(raw.strip()))
        except Exception:
            continue
    return types, objs


def _decode(body: bytes, resp) -> str:
    """Charset from the header only if it was really sent, else <meta
    charset>, else UTF-8 (requests defaults text/html to ISO-8859-1, which
    turned 'Café' into 'CafÃ©' and failed the name check)."""
    candidates = []
    ctype = (resp.headers.get("Content-Type") or "").lower()
    m = re.search(r"charset=[\"']?([\w.:-]{1,40})", ctype)
    if m:
        candidates.append(m.group(1))
    m = re.search(rb"<meta[^>]{0,200}?charset=[\"']?([\w.:-]{1,40})", body[:4096], re.I)
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    for enc in candidates + ["utf-8"]:
        try:
            codecs.lookup(enc)
            return body.decode(enc, errors="replace")
        except (LookupError, TypeError):
            continue
    return body.decode("utf-8", errors="replace")


# ---------- robots.txt (RFC 9309, as Google / OpenAI / Anthropic apply it) ----------

def _robots_groups(text: str) -> list[tuple[list[str], list[tuple[bool, str]]]]:
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(val.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            last_was_agent = False
            if agents and val and len(rules) < 2000:
                rules.append((key == "allow", val))
        # Other lines (Crawl-delay, Sitemap...) don't end a group of
        # User-agent lines -- only a rule does (as Google parses it).
    if agents:
        groups.append((agents, rules))
    return groups


def _rule_matches(pattern: str, path: str) -> bool:
    """Wildcard match in O(len(pattern) x len(path)) -- no regex: a hostile
    robots.txt full of '*' made the old regex backtrack for minutes."""
    anchored = pattern.endswith("$")
    pat = re.sub(r"\*+", "*", pattern[:-1] if anchored else pattern)[:500]
    path = path[:2000]
    n = len(path)
    positions = {0}
    for ch in pat:
        if ch == "*":
            positions = set(range(min(positions), n + 1))
        else:
            positions = {p + 1 for p in positions if p < n and path[p] == ch}
        if not positions:
            return False
    return (n in positions) if anchored else True


def robots_allows(robots_text: str, bot: str, path: str) -> bool:
    """Exact (case-insensitive) user-agent token match, all matching groups
    merged, falling back to '*'; longest matching rule wins; Allow wins a
    tie; '*' and '$' wildcards supported."""
    groups = _robots_groups((robots_text or "").lstrip("\ufeff"))
    token = bot.lower()
    rules = [r for agents, rs in groups if token in agents for r in rs]
    if not any(token in agents for agents, _ in groups):
        rules = [r for agents, rs in groups if "*" in agents for r in rs]
    best_len, allowed = -1, True
    for allow, pattern in rules:
        if _rule_matches(pattern, path):
            length = len(pattern)
            if length > best_len or (length == best_len and allow):
                best_len, allowed = length, allow
    return allowed


# ---------- the audit ----------

def audit_website(url_text: str, business: str = "", location: str = "", category: str = "") -> dict:
    """Never raises. Returns {"ok": bool, "url", "final_url", "score",
    "checks": [{key,label,status,detail,fix,weight}], "error"}."""
    url = normalize_site_url(url_text)
    if not url:
        return {"ok": False, "url": url_text, "error": "That doesn't look like a website address."}
    try:
        return _audit(url, business, location, category)
    except Exception:  # a parsing surprise must never break the whole report
        return {"ok": False, "url": url, "error": "Couldn't analyse that website."}


def _audit(url: str, business: str, location: str, category: str) -> dict:
    deadline = time.monotonic() + AUDIT_DEADLINE
    try:
        resp, final_url, body = safe_get(url, deadline=deadline)
    except UnsafeURL as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    except requests.exceptions.SSLError:
        return {"ok": False, "url": url, "error": "The website's security certificate is broken -- browsers and AI crawlers will warn or refuse."}
    except requests.exceptions.Timeout:
        return {"ok": False, "url": url, "error": "The website took too long to respond."}
    except requests.exceptions.ConnectionError as exc:
        if "NameResolution" in repr(exc) or "getaddrinfo" in repr(exc):
            return {"ok": False, "url": url, "error": "That website's address doesn't exist (DNS lookup failed)."}
        return {"ok": False, "url": url, "error": "Couldn't reach the website."}
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

    html = _decode(body, resp)
    page = parse_page(html)
    text = page.text
    low_text = text.lower()
    words = len(text.split())

    add("https", "Secure (HTTPS)", final_url.lower().startswith("https://"),
        "Served over HTTPS." if final_url.lower().startswith("https://") else "Served over plain HTTP.",
        "Turn on HTTPS (most hosts offer it free).", 4)

    robots_meta = ((page.meta("robots") or "") + " " + (page.meta("googlebot") or "")).lower()
    x_robots = (resp.headers.get("X-Robots-Tag") or "").lower()
    noindex = "noindex" in robots_meta or "noindex" in x_robots
    add("indexable", "Not hidden from search", not noindex,
        "The page tells search engines not to index it (noindex)." if noindex else "No noindex directive.",
        "Remove the noindex tag -- right now search engines and AI search are told to ignore this page.", 10)

    # robots.txt
    parsed = urlparse(final_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    blocked_search, blocked_training, robots_state = [], [], "missing"
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    try:
        r_resp, _, r_body = safe_get(root + "/robots.txt", accept="text/plain,*/*", deadline=deadline)
        if r_resp.status_code == 200:
            robots_state = "found"
            robots_text = r_body[:500_000].decode("utf-8-sig", errors="replace")
            for bot, what in SEARCH_BOTS:
                if not robots_allows(robots_text, bot, path):
                    blocked_search.append(f"{bot} ({what})")
            for bot, what in TRAINING_BOTS:
                if not robots_allows(robots_text, bot, path):
                    blocked_training.append(f"{bot} ({what})")
        elif r_resp.status_code >= 500 or r_resp.status_code == 429:
            robots_state = "error"  # crawlers treat a failing robots.txt as "keep out"
    except Exception:
        robots_state = "error"
    if robots_state == "error":
        add("ai_crawlers", "AI search crawlers allowed", False,
            "robots.txt couldn't be read (server error or timeout). Google and other crawlers treat that as "
            "\u201cdon't crawl\u201d until it works again.",
            "Make sure yoursite/robots.txt loads (a 404 is fine; an error is not).", 10, status="warn")
    else:
        add("ai_crawlers", "AI search crawlers allowed", not blocked_search,
            ("Blocked in robots.txt: " + ", ".join(blocked_search)) if blocked_search
            else ("robots.txt allows the AI search crawlers." if robots_state == "found" else "No robots.txt -- everything is allowed."),
            "Allow these in robots.txt -- while blocked, those assistants can't show or cite your site.", 10)
    if blocked_training:
        add("training_crawlers", "AI training crawlers", True,
            "Blocked (your choice -- doesn't affect search answers): " + ", ".join(blocked_training), "", 0, status="info")

    title = page.title
    from ai_visibility.analyzer import _search, _normalize  # same forgiving name matching as answers
    name_in_title = bool(business) and _search(_normalize(title), business) is not None
    add("title", "Page title names the business", bool(title) and (name_in_title or not business),
        f"Title: “{title[:90]}”" if title else "No <title> tag.",
        f"Use a title like “{business or 'Business name'} | {category or 'what you do'} in {location or 'your suburb'}”.", 5)

    desc = page.meta("description") or page.meta("og:description")
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

    has_tel = page.has_tel or bool(_PHONE_RE.search(text))
    add("phone", "Phone number visible", has_tel,
        "Phone number found." if has_tel else "No phone number found on the homepage.",
        "Show your phone number as text with a tap-to-call link.", 5)

    types, objs = _jsonld_types(page)
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

    js_heavy = words < 120 and page.script_count >= 5
    add("content", "Enough readable text", words >= 150,
        f"About {words} words of readable text." + (" Most content seems to load via JavaScript, which many AI crawlers don't run." if js_heavy else ""),
        "Add a few paragraphs of real text: services, area, prices, FAQs. Many AI crawlers don't run JavaScript, so text must be in the HTML.", 6)

    faq = "faqpage" in [t.lower() for t in types] or bool(re.search(r"frequently asked|\bfaqs?\b", low_text))
    add("faq", "Answers common questions", faq,
        "FAQ content found." if faq else "No FAQ section found.",
        "Add an FAQ answering what customers ask (prices, hours, areas, urgent jobs) -- assistants quote these answers.", 3,
        status=None if faq else "warn")

    viewport = page.meta("viewport") is not None
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
