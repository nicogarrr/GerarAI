"""The pinned socket permits exactly the port validated for the public URL.

La politica publica solo admite 80/443 (_parse_public_url rechaza el resto, ver
test_public_fetch_port_policy.py), asi que el guard del socket se prueba con
puertos estandar: el validado pasa y cualquier otro, incluido el estandar del
OTRO esquema, se rechaza antes de abrir el socket.
"""

import socket

import anyio
import pytest

from app.services import public_fetch as pf


def _target(url):
    parsed, hostname, port = pf._parse_public_url(url)
    return pf._build_target(parsed, hostname, port, [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
    ])


CASES = [
    ('https://reports.example/report.pdf', 443, [80, 8443]),
    ('http://reports.example/report.pdf', 80, [443, 8080]),
]


@pytest.mark.parametrize('url,port,wrong_ports', CASES)
def test_sync_backend_uses_only_the_validated_port(monkeypatch, url, port, wrong_ports):
    target = _target(url)
    backend = pf._SyncPinnedNetworkBackend()
    backend._target = target
    calls = []

    def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return object()

    monkeypatch.setattr(pf.SyncBackend, 'connect_tcp', connect)
    assert backend.connect_tcp(target.address, port) is not None
    assert calls == [(target.address, port)]
    for wrong in wrong_ports:
        with pytest.raises(RuntimeError, match='unexpected port'):
            backend.connect_tcp(target.address, wrong)
    assert calls == [(target.address, port)]  # ningun intento erroneo llego al socket


@pytest.mark.parametrize('url,port,wrong_ports', CASES)
def test_async_backend_uses_only_the_validated_port(monkeypatch, url, port, wrong_ports):
    target = _target(url)
    backend = pf._AsyncPinnedNetworkBackend()
    backend._target = target
    calls = []

    async def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return object()

    monkeypatch.setattr(pf.AnyIOBackend, 'connect_tcp', connect)

    async def run():
        assert await backend.connect_tcp(target.address, port) is not None
        for wrong in wrong_ports:
            with pytest.raises(RuntimeError, match='unexpected port'):
                await backend.connect_tcp(target.address, wrong)

    anyio.run(run)
    assert calls == [(target.address, port)]


@pytest.mark.parametrize('backend_cls', [pf._SyncPinnedNetworkBackend, pf._AsyncPinnedNetworkBackend])
def test_backend_without_validated_target_refuses_to_connect(backend_cls):
    backend = backend_cls()
    with pytest.raises(RuntimeError, match='missing its validated target'):
        backend._pinned_target('reports.example', 443)


def test_validated_target_keeps_standard_port_out_of_url_and_header():
    target = _target('https://reports.example:443/report.pdf')
    assert target.request_url == 'https://93.184.216.34/report.pdf'
    assert target.host_header == 'reports.example'
    assert target.sni_hostname == 'reports.example'


@pytest.mark.parametrize('backend_cls', [pf._SyncPinnedNetworkBackend, pf._AsyncPinnedNetworkBackend])
def test_backend_rejects_an_address_other_than_the_validated_one(backend_cls):
    backend = backend_cls()
    backend._target = _target('https://reports.example/report.pdf')
    with pytest.raises(RuntimeError, match='unvalidated address'):
        backend._pinned_target('10.0.0.5', 443)
    assert backend._pinned_target('93.184.216.34', 443) is backend._target
