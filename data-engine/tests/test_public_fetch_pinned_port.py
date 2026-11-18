"""The pinned socket permits exactly the port validated for the public URL."""

import socket

import anyio
import pytest

from app.services import public_fetch as pf


@pytest.mark.parametrize('url,port,wrong', [
    ('https://reports.example:8443/report.pdf', 8443, 443),
    ('http://reports.example:8080/report.pdf', 8080, 80),
])
def test_sync_backend_uses_validated_nondefault_port(monkeypatch, url, port, wrong):
    parsed, hostname, parsed_port = pf._parse_public_url(url)
    target = pf._build_target(parsed, hostname, parsed_port, [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
    ])
    backend = pf._SyncPinnedNetworkBackend()
    backend._target = target
    calls = []

    def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return object()

    monkeypatch.setattr(pf.SyncBackend, 'connect_tcp', connect)
    assert backend.connect_tcp(target.address, port) is not None
    assert calls == [(target.address, port)]
    with pytest.raises(RuntimeError, match='unexpected port'):
        backend.connect_tcp(target.address, wrong)
    assert calls == [(target.address, port)]


def test_async_backend_uses_validated_nondefault_port(monkeypatch):
    parsed, hostname, port = pf._parse_public_url('https://reports.example:8443/report.pdf')
    target = pf._build_target(parsed, hostname, port, [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
    ])
    backend = pf._AsyncPinnedNetworkBackend()
    backend._target = target
    calls = []

    async def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return object()

    monkeypatch.setattr(pf.AnyIOBackend, 'connect_tcp', connect)

    async def run():
        assert await backend.connect_tcp(target.address, 8443) is not None
        with pytest.raises(RuntimeError, match='unexpected port'):
            await backend.connect_tcp(target.address, 443)

    anyio.run(run)
    assert calls == [(target.address, 8443)]
