"""
Outbound HTTP for URLs that come from visitors (website checks, pasted
Google Maps links) -- without letting the server be pointed at itself or
its private network (SSRF).

Two layers:
  1. check_url(): scheme http(s) only, no "user:pass@" part (the classic
     "maps.google.com:@169.254.169.254" trick), ports 80/443 only, no
     localhost-style names.
  2. The connection itself: DNS is resolved ONCE, inside the socket
     connect, and every resolved address must be public before we connect
     to that exact address. Validating a name and then letting the HTTP
     library resolve it again would allow DNS rebinding (first lookup
     public, second lookup 127.0.0.1). TLS still verifies the certificate
     against the original hostname.

Redirects are followed by hand so each hop goes through both layers, and a
whole fetch has one deadline (per-socket timeouts alone let a server that
drips a byte every few seconds hold a thread indefinitely).
"""

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlparse, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError, NameResolutionError

MAX_REDIRECTS = 5
_BAD_NAMES = ("localhost", "localhost.localdomain", "metadata", "metadata.google.internal")
_BAD_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa", ".intranet", ".corp")
_EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in (
    "64:ff9b::/96",      # NAT64 -- wraps an IPv4 address (could be private)
    "64:ff9b:1::/48",
    "::/96",             # deprecated IPv4-compatible IPv6
    "100.64.0.0/10",     # carrier-grade NAT
    "2002::/16",         # 6to4 -- wraps an IPv4 address
    "::ffff:0:0:0/96",   # IPv4-translated (SIIT)
)]


class UnsafeURL(ValueError):
    """The URL points somewhere we refuse to fetch."""


def is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_public_ip(ip.ipv4_mapped)
    if ip.is_multicast or not ip.is_global:
        return False
    return not any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version)


def check_url(url: str, allowed_schemes=("http", "https")) -> None:
    try:
        u = urlparse(url)
        port = u.port
    except ValueError:
        raise UnsafeURL("That address isn't valid.")
    if u.scheme.lower() not in allowed_schemes:
        raise UnsafeURL("Only http(s) web addresses can be checked.")
    if u.username is not None or u.password is not None or "@" in (u.netloc or ""):
        raise UnsafeURL("Web addresses with a username/password part can't be checked.")
    if port not in (None, 80, 443):
        raise UnsafeURL("Only standard web ports can be checked.")
    host = (u.hostname or "").lower().rstrip(".")
    if not host or host in _BAD_NAMES or host.endswith(_BAD_SUFFIXES):
        raise UnsafeURL("That address isn't a public website.")
    try:  # a literal IP is checked right away (DNS names are checked at connect time)
        if not is_public_ip(ipaddress.ip_address(host.strip("[]"))):
            raise UnsafeURL("That address isn't a public website.")
    except ValueError as exc:
        if isinstance(exc, UnsafeURL):
            raise


def _public_connect(host: str, port: int, timeout, source_address=None, socket_options=None) -> socket.socket:
    """Resolve once, refuse non-public answers, connect to the vetted address."""
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos:
        raise socket.gaierror("no addresses")
    for info in infos:
        if not is_public_ip(ipaddress.ip_address(info[4][0].split("%")[0])):
            raise UnsafeURL("That address isn't a public website.")
    last: Exception | None = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            for opt in socket_options or []:
                sock.setsockopt(*opt)
            if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError("connect failed")


class _GuardedConnMixin:
    def _new_conn(self):  # mirrors urllib3's own error mapping
        try:
            return _public_connect(self._dns_host, self.port, self.timeout,
                                   source_address=self.source_address, socket_options=self.socket_options)
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc
        except socket.timeout as exc:
            raise ConnectTimeoutError(self, f"Connection to {self.host} timed out.") from exc
        except UnsafeURL:
            raise
        except OSError as exc:
            raise NewConnectionError(self, f"Failed to establish a new connection: {exc}") from exc


class _GuardedHTTPConnection(_GuardedConnMixin, HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedConnMixin, HTTPSConnection):
    pass


class _GuardedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _GuardedHTTPSConnection


class _GuardedAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _GuardedHTTPPool, "https": _GuardedHTTPSPool}
        self.poolmanager.key_fn_by_scheme = dict(self.poolmanager.key_fn_by_scheme)


def guarded_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # never route visitor URLs through an env-configured proxy
    adapter = _GuardedAdapter(max_retries=0)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def fetch(url: str, *, headers: dict | None = None, max_bytes: int = 2_500_000, deadline: float | None = None,
          max_redirects: int = MAX_REDIRECTS, follow=None, read_body: bool = True):
    """GET `url`, following redirects by hand. Every hop is checked by
    check_url() (+ `follow(next_url)`, which may raise to stop) and connects
    only to public IPs. Returns (response, final_url, body_bytes).
    Raises UnsafeURL, requests.Timeout or requests.RequestException."""
    deadline = deadline or (time.monotonic() + 15)
    current = url
    with guarded_session() as session:
        for _ in range(max_redirects + 1):
            check_url(current)
            left = deadline - time.monotonic()
            if left <= 0.5:
                raise requests.Timeout("Gave up waiting for the website.")
            resp = session.get(current, allow_redirects=False, stream=True, headers=headers or {},
                               timeout=(min(5.0, left), min(8.0, left)))
            try:
                loc = resp.headers.get("Location")
                if resp.status_code in (301, 302, 303, 307, 308) and loc:
                    nxt = urljoin(current, loc)
                    if follow:
                        follow(nxt)
                    current = nxt
                    continue
                body = b""
                if read_body:
                    # read1 returns as soon as SOME bytes arrive, so the
                    # deadline is checked after every socket read -- a plain
                    # read(n) blocks until n bytes, which a server dripping
                    # one byte at a time could stretch out forever.
                    while len(body) <= max_bytes:
                        if time.monotonic() > deadline:
                            raise requests.Timeout("The website took too long to send its page.")
                        chunk = resp.raw.read1(65536, decode_content=True)
                        if not chunk:
                            break
                        body += chunk
                return resp, current, body[:max_bytes]
            finally:
                resp.close()
    raise UnsafeURL("Too many redirects.")
