"""PublicSession: POST + cookies acotadas sobre el mismo pinning de public_fetch."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.services import public_fetch
from app.services.public_fetch import PublicSession

PUBLIC_IP = "93.184.216.34"
HOST_A = "a.example"
HOST_B = "b.example"


class _Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []
    script: dict[tuple[str, str], tuple[int, dict[str, list[str]], bytes]] = {}

    def _handle(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.seen.append(
            {
                "method": method,
                "path": self.path,
                "host": self.headers.get("Host"),
                "cookie": self.headers.get("Cookie"),
                "body": body,
                "ua": self.headers.get("User-Agent"),
            }
        )
        status, headers, payload = self.script.get(
            (method, self.path), (200, {"Content-Type": ["text/html; charset=utf-8"]}, b"ok")
        )
        self.send_response(status)
        for name, values in headers.items():
            for value in values:
                self.send_header(name, value)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")

    def log_message(self, *args):
        pass


@pytest.fixture()
def server(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    connected: list[str] = []
    _Handler.seen = []
    _Handler.script = {}
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, port_, *args, **kwargs):
        if host in {HOST_A, HOST_B}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port_))]
        return real_getaddrinfo(host, port_, *args, **kwargs)

    monkeypatch.setattr(public_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    original = public_fetch.SyncBackend.connect_tcp

    def recording_connect(self, host, port_, *args, **kwargs):
        connected.append(host)
        if host == PUBLIC_IP:
            return original(self, "127.0.0.1", port, *args, **kwargs)
        raise OSError(f"conexion bloqueada en el test hacia {host}")

    monkeypatch.setattr(public_fetch.SyncBackend, "connect_tcp", recording_connect)
    try:
        yield connected
    finally:
        srv.shutdown()
        srv.server_close()


def _allow(url: str) -> bool:
    return url.startswith(f"http://{HOST_A}/") or url.startswith(f"http://{HOST_B}/")


def _only_a(url: str) -> bool:
    return url.startswith(f"http://{HOST_A}/")


def test_get_and_post_pin_ip_keep_host_and_send_form(server):
    with PublicSession(allowed_url=_allow, user_agent="UA-test/1") as session:
        got = session.get(f"http://{HOST_A}/p")
        posted = session.post(f"http://{HOST_A}/f", {"a": "1", "b": "x y"})
    assert got.status_code == 200 and got.text == "ok"
    assert posted.text == "ok"
    assert set(server) == {PUBLIC_IP}  # solo la IP validada, nunca el nombre
    assert _Handler.seen[0]["host"] == HOST_A and _Handler.seen[0]["ua"] == "UA-test/1"
    assert _Handler.seen[1]["method"] == "POST"
    assert _Handler.seen[1]["body"] == b"a=1&b=x+y"


def test_cookie_is_stored_and_resent_to_same_host_only(server):
    _Handler.script = {
        ("GET", "/login"): (200, {"Set-Cookie": ["sid=abc; Path=/; HttpOnly", "t=1"]}, b"hi"),
        ("GET", "/x-b"): (200, {}, b"b"),
    }
    session = PublicSession(allowed_url=_allow)
    session.get(f"http://{HOST_A}/login")
    session.get(f"http://{HOST_A}/next")
    session.get(f"http://{HOST_B}/x-b")
    assert _Handler.seen[0]["cookie"] is None
    assert _Handler.seen[1]["cookie"] == "sid=abc; t=1"
    assert _Handler.seen[2]["cookie"] is None  # otro host: no se cruza


def test_cookie_max_age_zero_deletes_and_garbage_is_ignored(server):
    _Handler.script = {
        ("GET", "/set"): (200, {"Set-Cookie": ["k=v", "bad cookie"]}, b""),
        ("GET", "/del"): (200, {"Set-Cookie": ["k=; Max-Age=0"]}, b""),
    }
    session = PublicSession(allowed_url=_allow)
    session.get(f"http://{HOST_A}/set")
    session.get(f"http://{HOST_A}/mid")
    session.get(f"http://{HOST_A}/del")
    session.get(f"http://{HOST_A}/end")
    assert _Handler.seen[1]["cookie"] == "k=v"
    assert _Handler.seen[3]["cookie"] is None


def test_secure_cookie_not_sent_over_http(server):
    _Handler.script = {("GET", "/s"): (200, {"Set-Cookie": ["sec=1; Secure", "pl=2"]}, b"")}
    session = PublicSession(allowed_url=_allow)
    session.get(f"http://{HOST_A}/s")
    session.get(f"http://{HOST_A}/t")
    assert _Handler.seen[1]["cookie"] == "pl=2"


def test_post_302_becomes_get_without_body_and_keeps_cookie(server):
    _Handler.script = {
        ("POST", "/f"): (302, {"Location": ["/landing"], "Set-Cookie": ["sid=zz"]}, b""),
    }
    session = PublicSession(allowed_url=_allow)
    response = session.post(f"http://{HOST_A}/f", {"a": "1"})
    assert response.text == "ok"
    assert [s["method"] for s in _Handler.seen] == ["POST", "GET"]
    assert _Handler.seen[1]["body"] == b"" and _Handler.seen[1]["cookie"] == "sid=zz"


def test_post_307_is_refused_without_resending_body(server):
    _Handler.script = {("POST", "/f"): (307, {"Location": ["/elsewhere"]}, b"")}
    with pytest.raises(ValueError, match="307/308"):
        PublicSession(allowed_url=_allow).post(f"http://{HOST_A}/f", {"a": "1"})
    assert [s["method"] for s in _Handler.seen] == ["POST"]


def test_get_redirect_followed_and_cookie_not_forwarded_cross_host(server):
    _Handler.script = {
        ("GET", "/start"): (302, {"Location": [f"http://{HOST_B}/dest"], "Set-Cookie": ["sid=a1"]}, b""),
    }
    session = PublicSession(allowed_url=_allow)
    assert session.get(f"http://{HOST_A}/start").text == "ok"
    assert _Handler.seen[1]["host"] == HOST_B and _Handler.seen[1]["cookie"] is None


def test_redirect_outside_allowlist_is_denied_before_connecting(server):
    _Handler.script = {("GET", "/start"): (302, {"Location": [f"http://{HOST_B}/dest"]}, b"")}
    with pytest.raises(ValueError, match="denied by source policy"):
        PublicSession(allowed_url=_only_a).get(f"http://{HOST_A}/start")
    assert len(_Handler.seen) == 1


def test_initial_url_outside_allowlist_is_denied(server):
    with pytest.raises(ValueError, match="denied by source policy"):
        PublicSession(allowed_url=_only_a).get(f"http://{HOST_B}/x")
    assert _Handler.seen == [] and server == []


@pytest.mark.parametrize(
    "location",
    ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/", "http://localhost:8000/admin"],
)
def test_redirect_to_internal_network_is_blocked(server, location):
    _Handler.script = {("GET", "/start"): (302, {"Location": [location]}, b"")}

    def allow_all(url: str) -> bool:
        return True

    with pytest.raises(ValueError):
        PublicSession(allowed_url=allow_all).get(f"http://{HOST_A}/start")
    assert set(server) == {PUBLIC_IP}


def test_too_many_redirects(server):
    _Handler.script = {("GET", "/loop"): (302, {"Location": ["/loop"]}, b"")}
    with pytest.raises(ValueError, match="Too many redirects"):
        PublicSession(allowed_url=_allow).get(f"http://{HOST_A}/loop")


def test_size_limit_by_stream_and_by_content_length(server):
    _Handler.script = {("GET", "/big"): (200, {}, b"x" * 50)}
    with pytest.raises(ValueError, match="exceeds"):
        PublicSession(allowed_url=_allow, max_bytes=10).get(f"http://{HOST_A}/big")
    _Handler.script = {("GET", "/big2"): (200, {"Content-Length": ["99999999"]}, b"x")}
    with pytest.raises(ValueError, match="exceeds"):
        PublicSession(allowed_url=_allow, max_bytes=1024).get(f"http://{HOST_A}/big2")


def test_http_error_status_is_returned_with_headers_not_raised(server):
    _Handler.script = {("GET", "/429"): (429, {"Retry-After": ["3600"]}, b"slow")}
    response = PublicSession(allowed_url=_allow).get(f"http://{HOST_A}/429")
    assert response.status_code == 429 and response.headers["retry-after"] == "3600"
    with pytest.raises(httpx.HTTPStatusError):
        response.raise_for_status()


def test_extra_headers_and_exit_clears_cookies(server):
    _Handler.script = {("GET", "/c"): (200, {"Set-Cookie": ["a=1"]}, b"")}
    with PublicSession(allowed_url=_allow, extra_headers={"Accept-Language": "es"}) as session:
        session.get(f"http://{HOST_A}/c")
        assert session._cookies
    assert session._cookies == {}


def test_redirect_without_location_is_error(server):
    _Handler.script = {("GET", "/nol"): (302, {}, b"")}
    with pytest.raises(ValueError, match="without a location"):
        PublicSession(allowed_url=_allow).get(f"http://{HOST_A}/nol")


def test_illegal_cookie_is_dropped_and_bad_max_age_is_a_session_cookie(server):
    _Handler.script = {
        ("GET", "/r"): (200, {"Set-Cookie": ["path=/x", "m=1; Max-Age=abc"]}, b""),
    }
    session = PublicSession(allowed_url=_allow)
    session.get(f"http://{HOST_A}/r")
    session.get(f"http://{HOST_A}/n")
    assert _Handler.seen[1]["cookie"] == "m=1"  # Max-Age ilegible: se trata como sesion
