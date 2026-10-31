"""Guardas del fetch publico (anti-SSRF): parseo de URL, validacion de
direcciones (loopback/privadas/NAT64 fuera), pinning del destino, limite de
bytes y resolucion de redirects.

Estas guardas son la barrera contra SSRF en la ingesta de documentos
publicos: los tests fijan que una URL con credenciales, puerto invalido o
resolucion a una IP no publica se rechaza, y que el pinning exige el host y
puerto validados.
"""

import ipaddress
import socket

import pytest

from app.services import public_fetch
from app.services.public_fetch import (
    _PinnedConnectionMixin,
    _PublicTarget,
    _build_target,
    _parse_content_length,
    _parse_public_url,
    _read_limited,
    _redirect_target,
    _resolve_public_url,
    _validated_addresses,
    fetch_public_url,
    validate_public_url,
)


def _addrinfo(*ips: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]


# -- _parse_content_length ---------------------------------------------------


def test_content_length_basura_y_negativo_es_none():
    assert _parse_content_length(None) is None
    assert _parse_content_length("no-numero") is None
    assert _parse_content_length("-5") is None
    assert _parse_content_length(" 1024 ") == 1024
    assert _parse_content_length(2048) == 2048


# -- _parse_public_url --------------------------------------------------------


def test_parse_public_url_rechaza_esquema_credenciales_y_puerto_invalido():
    with pytest.raises(ValueError, match="http"):
        _parse_public_url("ftp://example.com/x")
    with pytest.raises(ValueError, match="credentials"):
        _parse_public_url("https://user:pass@example.com/x")
    with pytest.raises(ValueError, match="hostname"):
        _parse_public_url("https://")
    with pytest.raises(ValueError, match="port"):
        _parse_public_url("https://example.com:99999/x")
    _, host, port = _parse_public_url("https://example.com/x")
    assert (host, port) == ("example.com", 443)
    _, host, port = _parse_public_url("http://example.com:8080/x")
    assert (host, port) == ("example.com", 8080)


# -- _validated_addresses -----------------------------------------------------


def test_validated_addresses_rechaza_privadas_y_nats():
    with pytest.raises(ValueError, match="not allowed"):
        _validated_addresses(_addrinfo("127.0.0.1"))
    with pytest.raises(ValueError, match="not allowed"):
        _validated_addresses(_addrinfo("169.254.169.254"))  # metadata cloud
    with pytest.raises(ValueError, match="no usable address"):
        _validated_addresses([])


def test_validated_addresses_dedup_y_orden():
    out = _validated_addresses(_addrinfo("8.8.8.8", "1.1.1.1", "8.8.8.8"))
    assert out == ("1.1.1.1", "8.8.8.8")


# -- _build_target ------------------------------------------------------------


def test_build_target_puerto_no_estandar_y_sni():
    parsed, host, port = _parse_public_url("http://example.com:8080/doc.pdf")
    target = _build_target(parsed, host, port, _addrinfo("93.184.216.34"))
    assert target.address == "93.184.216.34"
    assert target.request_url == "http://93.184.216.34:8080/doc.pdf"
    assert target.host_header == "example.com:8080"
    assert target.sni_hostname == "example.com"


def test_build_target_ip_literal_debe_coincidir():
    parsed, host, port = _parse_public_url("http://93.184.216.34/doc.pdf")
    with pytest.raises(ValueError, match="do not match"):
        _build_target(parsed, host, port, _addrinfo("1.1.1.1"))
    target = _build_target(parsed, host, port, _addrinfo("93.184.216.34"))
    assert target.sni_hostname is None  # sin SNI para IP literal


# -- pinning ------------------------------------------------------------------


def _target(port_https: bool = True) -> _PublicTarget:
    scheme = "https" if port_https else "http"
    port = 443 if port_https else 80
    return _PublicTarget(
        url=f"{scheme}://example.com/x", request_url=f"{scheme}://93.184.216.34/x",
        address="93.184.216.34", host_header="example.com", sni_hostname="example.com",
    )


def test_pinned_target_exige_host_y_puerto_validados():
    mixin = _PinnedConnectionMixin()
    with pytest.raises(RuntimeError, match="missing its validated target"):
        mixin._pinned_target("93.184.216.34", 443)
    mixin._target = _target(port_https=True)
    with pytest.raises(RuntimeError, match="unexpected port"):
        mixin._pinned_target("93.184.216.34", 80)   # https fijado -> solo 443
    with pytest.raises(RuntimeError, match="unvalidated address"):
        mixin._pinned_target("1.1.1.1", 443)        # otra IP -> fuera
    assert mixin._pinned_target("93.184.216.34", 443) is mixin._target


# -- resolucion y redirects ---------------------------------------------------


def test_resolve_public_url_dns_fallido_es_valueerror(monkeypatch):
    def boom(*args, **kwargs):
        raise socket.gaierror("no resuelve")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="could not be resolved"):
        _resolve_public_url("https://no-existe.example/x")


def test_validate_public_url_devuelve_la_url_parseada(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34"))
    assert validate_public_url("https://example.com/doc.pdf") == "https://example.com/doc.pdf"


def test_redirect_target_solo_redirecciones_y_location_obligatoria():
    import httpx

    no_redirect = httpx.Response(200, request=httpx.Request("GET", "https://example.com/x"))
    assert _redirect_target(no_redirect, "https://example.com/x") is None
    sin_location = httpx.Response(302, request=httpx.Request("GET", "https://example.com/x"))
    with pytest.raises(ValueError, match="without a location"):
        _redirect_target(sin_location, "https://example.com/x")
    rel = httpx.Response(
        301, headers={"location": "/nuevo"}, request=httpx.Request("GET", "https://example.com/viejo")
    )
    assert _redirect_target(rel, "https://example.com/viejo") == "https://example.com/nuevo"


# -- limites y politica --------------------------------------------------------


def test_read_limited_corta_al_superar_el_limite():
    assert _read_limited([b"ab", b"cd"], 10) == b"abcd"
    with pytest.raises(ValueError, match="limit"):
        _read_limited([b"x" * 5, b"y" * 6], 10)


def test_fetch_public_url_denegada_por_politica_no_resuelve(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no debe resolver DNS si la politica deniega")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="denied by source policy"):
        fetch_public_url("https://example.com/x", allowed_url=lambda url: False)
