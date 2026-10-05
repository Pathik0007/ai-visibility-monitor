"""SSRF protection for visitor-supplied URLs (website check, Maps links)."""

import http.server
import ipaddress
import socket
import threading
import time

import pytest
import requests

import safe_http
from safe_http import UnsafeURL, check_url, is_public_ip


@pytest.mark.parametrize("url", [
    "ftp://example.com/", "file:///etc/passwd", "gopher://example.com/",
    "https://maps.google.com:@169.254.169.254/latest/meta-data/",   # userinfo trick
    "http://g.co:x@10.0.0.5/", "https://user:pw@example.com/",
    "http://example.com:6379/", "https://example.com:8443/",
    "http://localhost/", "http://printer.local/", "http://db.internal/", "http://metadata.google.internal/",
    "http://127.0.0.1/", "http://10.1.2.3/", "http://169.254.169.254/", "http://[::1]/", "http://0.0.0.0/",
    "http://100.64.0.1/", "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::a9fe:a9fe]/",
])
def test_rejected_urls(url):
    with pytest.raises(UnsafeURL):
        check_url(url)


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com:80/x", "https://93.184.216.34/"])
def test_allowed_urls(url):
    check_url(url)


@pytest.mark.parametrize("ip,public", [
    ("8.8.8.8", True), ("2606:4700::1111", True),
    ("127.0.0.1", False), ("10.0.0.1", False), ("192.168.1.1", False), ("172.16.0.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("::1", False), ("fe80::1", False),
    ("::ffff:10.0.0.1", False), ("64:ff9b::a9fe:a9fe", False), ("::127.0.0.1", False), ("224.0.0.1", False),
])
def test_public_ip_classification(ip, public):
    assert is_public_ip(ipaddress.ip_address(ip)) is public


# ---------- connect-time checks (DNS rebinding) against a real local server ----------

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/drip":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            for _ in range(1000):
                try:
                    self.wfile.write(b"x"); self.wfile.flush(); time.sleep(0.2)
                except OSError:
                    return
            return
        if self.path == "/redirect-internal":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        body = b"<html><head><title>Hi</title></head><body>hello</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture()
def resolve_to_loopback(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *a, **k):
        if host.endswith(".example"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        return real(host, port, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def test_rebinding_name_is_refused_at_connect(server, resolve_to_loopback):
    # Passes every static check, but resolves to 127.0.0.1 at connect time.
    with safe_http.guarded_session() as s, pytest.raises(UnsafeURL):
        s.get(f"http://rebind.example:{server}/", timeout=3)


def test_guarded_session_really_connects(server, resolve_to_loopback, monkeypatch):
    monkeypatch.setattr(safe_http, "is_public_ip", lambda ip: True)  # pretend loopback is public
    with safe_http.guarded_session() as s:
        assert s.get(f"http://site.example:{server}/", timeout=3).status_code == 200


def test_redirect_to_internal_address_is_refused(server, resolve_to_loopback, monkeypatch):
    real_is_public = safe_http.is_public_ip
    monkeypatch.setattr(safe_http, "is_public_ip", lambda ip: str(ip) == "127.0.0.1" or real_is_public(ip))
    monkeypatch.setattr(safe_http, "check_url", lambda u, **k: None if ":%d" % server in u else real_check(u))
    real_check = check_url
    with pytest.raises(UnsafeURL):
        safe_http.fetch(f"http://site.example:{server}/redirect-internal")


def test_slow_drip_is_cut_off_by_the_deadline(server, resolve_to_loopback, monkeypatch):
    monkeypatch.setattr(safe_http, "is_public_ip", lambda ip: True)
    monkeypatch.setattr(safe_http, "check_url", lambda u, **k: None)
    start = time.monotonic()
    with pytest.raises(requests.Timeout):
        safe_http.fetch(f"http://site.example:{server}/drip", deadline=time.monotonic() + 1.5)
    assert time.monotonic() - start < 4
