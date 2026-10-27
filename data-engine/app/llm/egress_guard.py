"""Salida HTTPS solo hacia IPs publicas para proveedores LLM de URL libre.

El proveedor ``custom`` deja que un usuario autenticado elija la URL a la que
el backend conecta. Validar el texto de la URL no basta (``127.1``, ``0x7f.1``
o un nombre DNS que resuelve a loopback pasan una comprobacion textual), asi
que la comprobacion real ocurre al conectar: el backend de red resuelve el
nombre, exige que TODAS las direcciones sean globales y conecta a una IP ya
validada. Host y SNI siguen siendo el nombre original (TLS valida el
certificado igual), y no hay una segunda resolucion entre comprobar y conectar
(sin DNS rebinding). Los redirects se desactivan y ``trust_env=False`` evita
que un proxy de entorno resuelva el destino por su cuenta.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import anyio
import httpcore
import httpx

PUBLIC_ONLY_MESSAGE = "La URL del proveedor apunta a una direccion no publica."


class NonPublicAddressError(httpcore.ConnectError):
    """El destino resuelve a una IP privada, loopback o reservada."""


Resolver = Callable[..., Awaitable[Iterable[Any]]]


async def _default_resolver(host: str, port: int) -> Iterable[Any]:
    return await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)


# Sustituible en tests: nunca resuelve DNS real ahi.
_resolver: Resolver = _default_resolver


_BLOCKED_V6 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "::/96",  # IPv4-compatible (obsoleto) y ::, ::1
        "::ffff:0:0:0/96",  # SIIT
        "64:ff9b:1::/48",  # NAT64 de uso local
        "100::/64",  # discard-only
        "fec0::/10",  # site-local (obsoleto)
        "ff00::/8",  # multicast
    )
)


def is_public_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True solo para unicast global; mira tambien IPv4 embebida en IPv6."""
    try:
        ip = ipaddress.ip_address(value) if isinstance(value, str) else value
    except ValueError:
        return False
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
        return False
    if ip.is_private or ip.is_reserved or not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip != ipaddress.IPv4Address("255.255.255.255")
    if any(ip in net for net in _BLOCKED_V6):
        return False
    embedded = ip.ipv4_mapped or ip.sixtofour
    if embedded is None and ip.teredo is not None:
        embedded = ip.teredo[1]
    if embedded is None and ip in ipaddress.ip_network("64:ff9b::/96"):
        embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if embedded is not None and not is_public_ip(embedded):
        return False
    return True


def validated_addresses(infos: Iterable[Any]) -> list[str]:
    """Direcciones del getaddrinfo; ``NonPublicAddressError`` si alguna no es global."""
    found: list[str] = []
    for item in infos:
        try:
            address = str(item[4][0]).split("%", 1)[0]
        except (IndexError, TypeError):
            raise NonPublicAddressError(PUBLIC_ONLY_MESSAGE) from None
        if not is_public_ip(address):
            raise NonPublicAddressError(PUBLIC_ONLY_MESSAGE)
        if address not in found:
            found.append(address)
    if not found:
        raise NonPublicAddressError(PUBLIC_ONLY_MESSAGE)
    return found


class PublicOnlyBackend(httpcore.AnyIOBackend):
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ):
        try:
            infos = await _resolver(host, port)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        addresses = validated_addresses(infos)
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await super().connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


def public_only_transport() -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    pool = getattr(transport, "_pool", None)
    if pool is None or not hasattr(pool, "_network_backend"):  # pragma: no cover
        # Un upgrade de httpcore/httpx que cambie esto debe fallar cerrado.
        raise RuntimeError("httpx transport no admite el backend de red restringido")
    pool._network_backend = PublicOnlyBackend()
    return transport


def public_only_client(timeout: httpx.Timeout | float | None = None) -> httpx.AsyncClient:
    """Cliente sin redirects, sin proxy de entorno y solo hacia IPs publicas."""
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        transport=public_only_transport(),
    )
