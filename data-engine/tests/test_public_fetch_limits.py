"""Contratos de seguridad y límites del fetch público.

La resolución queda fijada por conexión: cada destino se valida una sola vez y
el transporte conecta exactamente a la IP aprobada, conservando el hostname
original para HTTP Host y SNI/TLS.
"""

import socket

import anyio
import httpx
import pytest

from app.services import public_fetch
from app.services.public_fetch import _read_limited, _redirect_target


def test_read_limited_accepts_within_cap():
    chunks = [b"a" * 100, b"b" * 100]
    assert _read_limited(iter(chunks), 200) == b"a" * 100 + b"b" * 100


def test_read_limited_aborts_the_moment_cap_is_exceeded():
    chunks = [b"a" * 150, b"b" * 150, b"c" * 150]

    def gen():
        yield from chunks
        raise AssertionError("stream must not be consumed past the cap")

    with pytest.raises(ValueError, match="limit"):
        _read_limited(gen(), 200)


def test_redirect_target_only_for_redirect_statuses():
    for status in (301, 302, 303, 307, 308):
        response = httpx.Response(status, headers={"location": "https://ok.example/next"})
        assert _redirect_target(response, "https://ok.example/start") == "https://ok.example/next"
    response = httpx.Response(200, headers={"location": "https://ok.example/next"})
    assert _redirect_target(response, "https://ok.example/start") is None


def test_redirect_without_location_is_rejected():
    response = httpx.Response(302)
    with pytest.raises(ValueError, match="without a location"):
        _redirect_target(response, "https://ok.example/start")


def test_relative_redirect_resolved_against_current_url():
    response = httpx.Response(302, headers={"location": "/docs/file.pdf"})
    assert _redirect_target(response, "https://ok.example/a/b") == "https://ok.example/docs/file.pdf"


def test_sync_pinned_backend_uses_validated_address(monkeypatch):
    resolutions = iter(
        [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ]
    )
    monkeypatch.setattr(public_fetch.socket, "getaddrinfo", lambda *args, **kwargs: next(resolutions))

    target = public_fetch._resolve_public_url("https://rebind.example/document")
    backend = public_fetch._SyncPinnedNetworkBackend()
    backend._target = target
    connect_hosts = []

    def backend_connect(self, host, port, **kwargs):
        connect_hosts.append(host)
        return object()

    monkeypatch.setattr(public_fetch.SyncBackend, "connect_tcp", backend_connect)

    assert target.address == "93.184.216.34"
    assert target.request_url == "https://93.184.216.34/document"
    assert target.host_header == "rebind.example"
    assert target.sni_hostname == "rebind.example"
    assert backend.connect_tcp("93.184.216.34", 443) is not None
    assert connect_hosts == ["93.184.216.34"]
    with pytest.raises(RuntimeError, match="unvalidated address"):
        backend.connect_tcp("127.0.0.1", 443)
    with pytest.raises(ValueError, match="Private"):
        public_fetch._resolve_public_url("https://rebind.example/document")


def test_resolution_fails_closed_if_any_address_is_not_public(monkeypatch):
    monkeypatch.setattr(
        public_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
        ],
    )

    with pytest.raises(ValueError, match="Private"):
        public_fetch._resolve_public_url("https://mixed.example/document")


def test_async_resolution_uses_same_pinned_address(monkeypatch):
    async def fake_resolve(*args, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(anyio, "getaddrinfo", lambda host, port, **kwargs: fake_resolve(host, port))

    async def scenario():
        target = await public_fetch._resolve_public_url_async("https://rebind.example/document")
        backend = public_fetch._AsyncPinnedNetworkBackend()
        backend._target = target
        connect_hosts = []

        async def backend_connect(self, host, port, **kwargs):
            connect_hosts.append(host)
            return object()

        monkeypatch.setattr(public_fetch.AnyIOBackend, "connect_tcp", backend_connect)
        assert target.address == "93.184.216.34"
        assert target.request_url == "https://93.184.216.34/document"
        assert target.host_header == "rebind.example"
        assert target.sni_hostname == "rebind.example"
        assert await backend.connect_tcp("93.184.216.34", 443) is not None
        assert connect_hosts == ["93.184.216.34"]
        with pytest.raises(RuntimeError, match="unvalidated address"):
            await backend.connect_tcp("127.0.0.1", 443)

    anyio.run(scenario)


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::127.0.0.1",  # IPv4-compatible (obsoleto) loopback
        "::ffff:169.254.169.254",  # IPv4-mapped metadata
        "::169.254.169.254",  # IPv4-compatible metadata
        "64:ff9b::7f00:1",  # NAT64 -> 127.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 -> 169.254.169.254
        "64:ff9b::a00:1",  # NAT64 -> 10.0.0.1
        "64:ff9b:1::a00:1",  # NAT64 local
        "2002:7f00:1::",  # 6to4 de 127.0.0.1
    ],
)
def test_resolution_rejects_ipv4_embedded_in_ipv6(monkeypatch, address):
    monkeypatch.setattr(
        public_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0))],
    )

    with pytest.raises(ValueError, match="Private"):
        public_fetch._resolve_public_url("https://embedded.example/document")


@pytest.mark.parametrize("address", ["::127.0.0.1", "64:ff9b::a9fe:a9fe", "::ffff:127.0.0.1"])
def test_ip_literal_url_with_embedded_ipv4_is_rejected(address):
    with pytest.raises(ValueError):
        public_fetch.validate_public_url(f"http://[{address}]/latest/meta-data/")
