"""Public fetch transport contracts without opening external sockets."""

import socket

import anyio
import httpx
import pytest

from app.services import public_fetch as pf


def _dns(monkeypatch):
    calls = []

    def resolve(host, port, **kwargs):
        calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(pf.socket, "getaddrinfo", resolve)
    return calls


def test_sync_fetch_revalidates_redirect_preserves_host_sni_and_exact_cap(monkeypatch):
    resolutions = _dns(monkeypatch)
    requests = []

    def handle(self, request):
        requests.append(request)
        assert isinstance(self._pool._network_backend, pf._SyncPinnedNetworkBackend)
        assert self._pool._network_backend._target.address == "93.184.216.34"
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://second.example/report"})
        return httpx.Response(
            200, headers={"content-type": "application/pdf", "content-length": "4"}, content=b"PDF!"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    result = pf.fetch_public_url("https://first.example/start", max_bytes=4, user_agent="Test fetch/1")
    assert result == (b"PDF!", "application/pdf", "https://second.example/report")
    assert resolutions == [("first.example", 443), ("second.example", 443)]
    assert [str(r.url) for r in requests] == ["https://93.184.216.34/start", "https://93.184.216.34/report"]
    assert [r.headers["host"] for r in requests] == ["first.example", "second.example"]
    assert [r.extensions["sni_hostname"] for r in requests] == ["first.example", "second.example"]
    assert all(r.headers["user-agent"] == "Test fetch/1" for r in requests)


def test_sync_redirect_policy_denies_before_second_dns(monkeypatch):
    resolutions = _dns(monkeypatch)
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: httpx.Response(302, headers={"location": "https://denied.example/report"}),
    )
    with pytest.raises(ValueError, match="redirect denied by source policy"):
        pf.fetch_public_url("https://allowed.example/start", allowed_url=lambda url: "allowed.example" in url)
    assert resolutions == [("allowed.example", 443)]


@pytest.mark.parametrize("oversized_header", [True, False])
def test_sync_limit_aborts_and_closes_response(monkeypatch, oversized_header):
    _dns(monkeypatch)
    events = []

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            events.append("read")
            yield b"12345"
            raise AssertionError("must stop immediately after cap")

        def close(self):
            events.append("close")

    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: httpx.Response(
            200,
            headers={"content-length": "5" if oversized_header else "garbage"},
            stream=Chunks(),
        ),
    )
    with pytest.raises(ValueError, match="limit"):
        pf.fetch_public_url("https://allowed.example/report", max_bytes=4)
    assert events == (["close"] if oversized_header else ["read", "close"])


def test_sync_redirect_limit_is_bounded(monkeypatch):
    resolutions = _dns(monkeypatch)
    requests = []

    def handle(self, request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "/next"})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    with pytest.raises(ValueError, match="Too many redirects"):
        pf.fetch_public_url("https://allowed.example/start")
    assert len(requests) == pf.MAX_REDIRECTS + 1
    assert len(resolutions) == pf.MAX_REDIRECTS + 2


@pytest.mark.parametrize("addresses", [[None], [(0, 0, 0, "", ("invalid", 443))]])
def test_malformed_dns_answers_are_rejected(addresses):
    with pytest.raises(ValueError, match="invalid address"):
        pf._validated_addresses(addresses)


def test_ipv6_target_brackets_ip_and_host_with_standard_port():
    parsed, host, port = pf._parse_public_url("https://[2606:4700:4700::1111]:443/report")
    target = pf._build_target(parsed, host, port, [(socket.AF_INET6, 1, 6, "", (host, port, 0, 0))])
    assert target.request_url == "https://[2606:4700:4700::1111]/report"
    assert target.host_header == "[2606:4700:4700::1111]"
    assert target.sni_hostname is None


def test_wrong_transport_and_async_dns_fail_closed(monkeypatch):
    target = pf._PublicTarget(
        "https://example.com/", "https://93.184.216.34/", "93.184.216.34", "example.com", "example.com"
    )
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(RuntimeError, match="not using the HTTP transport"):
            pf._connect_pinned_httpcore(client=client, target=target)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ) as client:
            with pytest.raises(RuntimeError, match="not using the async HTTP transport"):
                await pf._connect_pinned_httpcore_async(client=client, target=target)

        async def bad_dns(*args, **kwargs):
            raise socket.gaierror("no DNS")

        monkeypatch.setattr(pf.anyio, "getaddrinfo", bad_dns)
        with pytest.raises(ValueError, match="could not be resolved"):
            await pf._resolve_public_url_async("https://example.com/")

    anyio.run(scenario)
