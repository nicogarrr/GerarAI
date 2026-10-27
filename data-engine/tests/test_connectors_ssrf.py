"""SSRF: los conectores RSS e IR deben pasar por public_fetch.

Un feed «público» que redirige a 169.254.169.254 o a localhost no debe seguirse.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anyio
import pytest

from app.services import public_fetch
from app.services.connectors.ir import IRConnector
from app.services.connectors.rss import RSSConnector

PUBLIC_IP = "93.184.216.34"
FEED_HOST = "feed.example"

RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>Resultados 3T</title><link>https://feed.example/a</link><guid>a</guid></item>
</channel></rss>"""

IR_BODY = b"""<html><body>
<a href="/press-release/q3-results">Press release: Q3 results</a>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    redirects: dict[str, str] = {}

    def do_GET(self):  # noqa: N802
        target = self.redirects.get(self.path)
        if target is not None:
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        body = RSS_BODY if self.path.startswith("/feed") else IR_BODY
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def fake_public_host(monkeypatch):
    """FEED_HOST resuelve a una IP pública, pero la conexión va a un servidor local."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connected: list[str] = []

    real_getaddrinfo = anyio.getaddrinfo

    async def fake_getaddrinfo(host, port_, **kwargs):
        if host == FEED_HOST:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port_))]
        if host == "localhost":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_))]
        return await real_getaddrinfo(host, port_, **kwargs)

    monkeypatch.setattr(anyio, "getaddrinfo", fake_getaddrinfo)

    original_connect = public_fetch.AnyIOBackend.connect_tcp

    async def recording_connect(self, host, port_, *args, **kwargs):
        connected.append(host)
        if host in {FEED_HOST, PUBLIC_IP}:
            return await original_connect(self, "127.0.0.1", port, *args, **kwargs)
        raise OSError(f"conexión bloqueada en el test hacia {host}")

    monkeypatch.setattr(public_fetch.AnyIOBackend, "connect_tcp", recording_connect)
    try:
        yield port, connected
    finally:
        _Handler.redirects = {}
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
    ],
)
def test_rss_no_sigue_redireccion_a_red_interna(fake_public_host, location):
    _port, connected = fake_public_host
    _Handler.redirects = {"/feed": location}

    result = asyncio.run(RSSConnector(timeout=5).poll(f"http://{FEED_HOST}/feed"))

    assert result.items == []
    assert result.errors, "el sondeo debe fallar"
    assert "Private, loopback, link-local, or reserved" in " ".join(result.errors)
    assert connected, "la primera petición debe llegar al host público"
    assert not any(h in {"169.254.169.254", "localhost", "127.0.0.1"} for h in connected)


def test_rss_publico_sigue_funcionando(fake_public_host):
    _port, connected = fake_public_host
    _Handler.redirects = {"/old-feed": f"http://{FEED_HOST}/feed"}

    result = asyncio.run(RSSConnector(timeout=5).poll(f"http://{FEED_HOST}/old-feed"))

    assert not result.errors
    assert [item.title for item in result.items] == ["Resultados 3T"]
    assert set(connected) == {PUBLIC_IP}


def test_ir_no_sigue_redireccion_a_metadata(fake_public_host):
    _port, connected = fake_public_host
    _Handler.redirects = {"/ir": "http://169.254.169.254/latest/meta-data/"}

    result = asyncio.run(IRConnector(timeout=5).poll(f"http://{FEED_HOST}/ir"))

    assert result.items == []
    assert "Private, loopback, link-local, or reserved" in " ".join(result.errors)
    assert "169.254.169.254" not in connected


def test_ir_publico_sigue_funcionando(fake_public_host):
    _port, connected = fake_public_host

    result = asyncio.run(IRConnector(timeout=5).poll(f"http://{FEED_HOST}/ir", ticker="abc"))

    assert not result.errors
    assert [item.url for item in result.items] == [
        f"http://{FEED_HOST}/press-release/q3-results"
    ]
    assert set(connected) == {PUBLIC_IP}
