"""Google Maps link handling: only Google hosts, never raises."""

import pytest

import links


@pytest.mark.parametrize("url,ok", [
    ("https://maps.app.goo.gl/abc123", True),
    ("https://www.google.com/maps/place/Burger+Boys/@-33.7,151.1,17z", True),
    ("https://www.google.com.au/maps?q=Joe's+Cafe", True),
    ("https://maps.google.com:@169.254.169.254/latest/meta-data/", False),
    ("http://g.co:x@10.0.0.5:6379/", False),
    ("https://google.com.evil.com/maps", False),
    ("https://www.google.com:8080/maps", False),
    ("https://example.com/maps/place/X", False),
])
def test_only_google_links(url, ok):
    assert bool(links.normalize_url(url)) is ok


def test_place_name_is_read_from_the_url_without_fetching(monkeypatch):
    monkeypatch.setattr(links, "_free_lookup", lambda info: {"name": info["name"], "category": "", "location": ""})
    r = links.resolve_link("https://www.google.com/maps/place/The+Burger+Boys/@-33.79,151.12,17z")
    assert r["ok"] and r["name"] == "The Burger Boys"


@pytest.mark.parametrize("text", ["https://www.google.com/maps?q=Joe's Cafe,,", "https://g.page/", "", "javascript:alert(1)"])
def test_resolve_link_never_raises(text, monkeypatch):
    monkeypatch.setattr(links, "_osm_reverse", lambda *a: None)
    monkeypatch.setattr("places._search_photon", lambda *a, **k: [])
    monkeypatch.setattr("safe_http.fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert isinstance(links.resolve_link(text), dict)
