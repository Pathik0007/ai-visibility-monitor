"""Website AI-readiness check: robots.txt rules as crawlers apply them,
hostile HTML, and the full audit on a good and a bad page."""

import time
from unittest import mock

import pytest

import website_audit as wa


@pytest.mark.parametrize("robots,bot,path,allowed", [
    ("User-agent: OAI-SearchBot\nDisallow: /*", "OAI-SearchBot", "/", False),         # wildcard
    ("User-agent: *\nAllow: /$\nDisallow: /", "Googlebot", "/", True),                 # $ anchor, longest match
    ("User-agent: *\nAllow: /$\nDisallow: /", "Googlebot", "/menu", False),
    ("User-agent: bot\nDisallow: /", "Googlebot", "/", True),                          # no substring matching
    ("User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /", "OAI-SearchBot", "/", True),
    ("User-agent: GPTBot\nUser-agent: OAI-SearchBot\nDisallow: /", "OAI-SearchBot", "/", False),  # shared group
    ("User-agent: *\nDisallow:", "Bingbot", "/", True),                                # empty disallow
    ("user-agent: perplexitybot\ndisallow: /", "PerplexityBot", "/", False),           # case-insensitive
    ("User-agent: *\nDisallow: /private\nAllow: /private/menu", "Googlebot", "/private/menu", True),
])
def test_robots_rules(robots, bot, path, allowed):
    assert wa.robots_allows(robots, bot, path) is allowed


@pytest.mark.parametrize("html", [
    "<meta name=robots " * 2000,
    "<" * 800_000,
    "<script>" * 100_000,
    "<script type='application/ld+json'>" * 50_000,
])
def test_hostile_html_parses_quickly(html):
    start = time.monotonic()
    wa.parse_page(html)
    assert time.monotonic() - start < 3


def test_parser_reads_what_the_audit_needs():
    page = wa.parse_page("""<html><head><title> Joe's  Cafe </title><meta name=description content='Coffee'>
        <meta name="viewport" content="width=device-width"><script type="application/ld+json">
        {"@graph":[{"@type":"CafeOrCoffeeShop","openingHours":"Mo-Fr"}]}</script><script>var x="<b>no</b>"</script></head>
        <body><h1>Joe's Cafe</h1><a href="tel:+6129">Call</a></body></html>""")
    assert page.title == "Joe's Cafe" and page.meta("description") == "Coffee" and page.meta("viewport")
    assert page.has_tel and "no" not in page.text and "Joe's Cafe" in page.text
    assert "CafeOrCoffeeShop" in wa._jsonld_types(page)[0]


@pytest.mark.parametrize("text,ok", [
    ("example.com.au", True), ("https://example.com", True), ("[::1", False), ("http://user@evil.com", False),
    ("example.com:99999", False), ("not a site", False), ("", False), ("x" * 600 + ".com", False),
])
def test_normalize_never_raises(text, ok):
    assert bool(wa.normalize_site_url(text)) is ok


def test_charset_handling():
    utf8_no_header = mock.Mock(headers={"Content-Type": "text/html"})
    bogus_charset = mock.Mock(headers={"Content-Type": "text/html; charset=utf8mb4"})
    assert wa._decode("Café".encode(), utf8_no_header) == "Café"
    assert wa._decode("Café".encode(), bogus_charset) == "Café"


GOOD = (b"<html><head><title>The Burger Boys | Burgers in North Ryde</title>"
        b"<meta name='description' content='Smash burgers'><meta name='viewport' content='width=device-width'>"
        b"<script type='application/ld+json'>{\"@type\":\"Restaurant\",\"openingHours\":\"Mo-Su 11:00-21:00\"}</script>"
        b"</head><body><h1>The Burger Boys</h1><p>Best smash burgers in North Ryde. " + b"Fresh burgers daily. " * 60
        + b"</p><a href='tel:0299999999'>Call</a><h2>FAQ</h2></body></html>")
BAD = b"<html><head><meta name='robots' content='noindex'></head><body>" + b"<script></script>" * 6 + b"</body></html>"


def _site(home, robots_status=200, robots=b"User-agent: *\nAllow: /"):
    def fake(url, accept=None, deadline=None):
        if url.endswith("/robots.txt"):
            return mock.Mock(status_code=robots_status, headers={}), url, robots
        return mock.Mock(status_code=200, headers={"Content-Type": "text/html; charset=utf-8"}), url, home
    return fake


def test_good_site_scores_high():
    with mock.patch.object(wa, "safe_get", side_effect=_site(GOOD)):
        r = wa.audit_website("theburgerboys.com.au", "The Burger Boys", "North Ryde, NSW", "burger restaurant")
    assert r["ok"] and r["score"] >= 90


def test_bad_site_scores_low_and_names_the_blocked_bot():
    robots = b"User-agent: OAI-SearchBot\nDisallow: /\n"
    with mock.patch.object(wa, "safe_get", side_effect=_site(BAD, robots=robots)):
        r = wa.audit_website("bad.example.com", "The Burger Boys", "North Ryde, NSW", "burger restaurant")
    by_key = {c["key"]: c for c in r["checks"]}
    assert r["score"] < 40
    assert by_key["indexable"]["status"] == "fail" and "OAI-SearchBot" in by_key["ai_crawlers"]["detail"]


def test_robots_server_error_is_a_warning_not_a_pass():
    with mock.patch.object(wa, "safe_get", side_effect=_site(GOOD, robots_status=503)):
        r = wa.audit_website("theburgerboys.com.au", "The Burger Boys", "North Ryde", "burgers")
    assert {c["key"]: c for c in r["checks"]}["ai_crawlers"]["status"] == "warn"


def test_unsafe_url_is_reported_not_raised():
    r = wa.audit_website("http://127.0.0.1/admin")
    assert r["ok"] is False and "public" in r["error"]


def test_wildcard_heavy_robots_rule_is_fast():
    start = time.monotonic()
    wa.robots_allows("User-agent: *\nDisallow: /" + "a*" * 50 + "b\n", "Googlebot", "/" + "a" * 2000)
    assert time.monotonic() - start < 1


def test_non_rule_lines_do_not_split_a_user_agent_group():
    robots = "User-agent: GPTBot\nCrawl-delay: 10\nUser-agent: OAI-SearchBot\nDisallow: /"
    assert wa.robots_allows(robots, "GPTBot", "/") is False


def test_svg_title_is_not_the_page_title():
    assert wa.parse_page("<title>Joe Plumbing</title><svg><title>Facebook</title></svg>").title == "Joe Plumbing"
