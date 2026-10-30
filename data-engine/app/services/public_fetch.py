"""Bounded HTTP fetching for user-supplied public URLs.

Redirects are followed manually and every hop is resolved and validated. The
validated IP is then pinned into the HTTP connection: Host remains the original
hostname for virtual hosting and TLS SNI, while the socket backend can connect
only to the already-approved address. Responses are streamed with a hard byte
limit so a remote server cannot force an unbounded allocation.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass

try:
    # API privada de httpcore (no hay equivalente publico en httpx para
    # conectar a una IP fijada manteniendo Host/SNI). Si un upgrade la mueve,
    # falla cerrado y en voz alta en vez de romperse en silencio.
    from httpcore._backends.anyio import AnyIOBackend
    from httpcore._backends.base import AsyncNetworkStream
    from httpcore._backends.sync import SyncBackend
except ImportError as exc:  # pragma: no cover - defensa ante upgrades
    raise RuntimeError(
        "httpcore internal backend modules moved; public_fetch IP pinning "
        "requires the httpcore 1.x private backends. Pin httpcore or update "
        "the pinning code."
    ) from exc
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import anyio
import httpx

from app.llm.egress_guard import is_public_ip

MAX_REDIRECTS = 3
DEFAULT_MAX_BYTES = 15 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
USER_AGENT = "GerarAI Public Document Fetcher/1.0"


def _parse_content_length(value: object) -> int | None:
    """Content-Length con try/default: un header ausente o basura devuelve
    None (el límite duro del stream sigue protegiendo) en vez de romper."""
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


@dataclass(frozen=True)
class _PublicTarget:
    url: str
    request_url: str
    address: str
    host_header: str
    sni_hostname: str | None


class _PinnedConnectionMixin:
    _target: _PublicTarget | None = None

    def _pinned_target(self, host: str, port: int) -> _PublicTarget:
        if self._target is None:
            raise RuntimeError("Public fetch transport is missing its validated target")
        expected_port = 443 if self._target.url.lower().startswith("https:") else 80
        if port != expected_port:
            raise RuntimeError("Public fetch transport attempted an unexpected port")
        if host != self._target.address:
            raise RuntimeError("Public fetch transport attempted an unvalidated address")
        return self._target


class _SyncPinnedNetworkBackend(_PinnedConnectionMixin, SyncBackend):
    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        super().__exit__(exc_type, exc_value, traceback)

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ):
        target = self._pinned_target(host, port)
        return super().connect_tcp(
            target.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _AsyncPinnedNetworkBackend(_PinnedConnectionMixin, AnyIOBackend):
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> AsyncNetworkStream:
        target = self._pinned_target(host, port)
        return await super().connect_tcp(
            target.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


def _parse_public_url(url: str) -> tuple[Any, str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) URLs can be fetched")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc
    return parsed, hostname, port


def _validated_addresses(addresses: Iterable[Any]) -> tuple[str, ...]:
    unique: set[str] = set()
    for item in addresses:
        try:
            address = str(item[4][0]).split("%", 1)[0]
            parsed_ip = ipaddress.ip_address(address)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("URL resolved to an invalid address") from exc
        # is_global solo no basta: ``::127.0.0.1`` (IPv4-compatible, ::/96) y
        # ``64:ff9b::a9fe:a9fe`` (NAT64 -> 169.254.169.254) son "globales" para
        # ipaddress y apuntan a loopback/metadata. Mismo criterio que el egress
        # del LLM (IPv4 embebida en mapped/compatible/6to4/Teredo/NAT64).
        if not is_public_ip(parsed_ip):
            raise ValueError("Private, loopback, link-local, or reserved URLs are not allowed")
        unique.add(str(parsed_ip))
    if not unique:
        raise ValueError("URL hostname has no usable address")
    return tuple(sorted(unique, key=lambda value: (ipaddress.ip_address(value).version, value)))


def _build_target(
    parsed: Any,
    hostname: str,
    port: int,
    addresses: Iterable[Any],
) -> _PublicTarget:
    validated = _validated_addresses(addresses)
    request_netloc = validated[0]
    if ":" in request_netloc:
        request_netloc = f"[{request_netloc}]"
    if port != (443 if parsed.scheme == "https" else 80):
        request_netloc = f"{request_netloc}:{port}"
    request_url = urlunparse(parsed._replace(netloc=request_netloc))

    url_host = hostname
    if ":" in url_host:
        url_host = f"[{url_host}]"
    if port != (443 if parsed.scheme == "https" else 80):
        url_host = f"{url_host}:{port}"
    host_header = url_host
    sni_hostname = None
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        sni_hostname = hostname
    else:
        if literal != ipaddress.ip_address(validated[0]):
            raise ValueError("URL hostname and resolved address do not match")

    return _PublicTarget(
        url=parsed.geturl(),
        request_url=request_url,
        address=validated[0],
        host_header=host_header,
        sni_hostname=sni_hostname,
    )


def _resolve_public_url(url: str) -> _PublicTarget:
    parsed, hostname, port = _parse_public_url(url)
    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc
    return _build_target(parsed, hostname, port, addresses)


async def _resolve_public_url_async(url: str) -> _PublicTarget:
    parsed, hostname, port = _parse_public_url(url)
    try:
        addresses = await anyio.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc
    return _build_target(parsed, hostname, port, addresses)


def validate_public_url(url: str) -> str:
    return _resolve_public_url(url).url


def _connect_pinned_httpcore(*, client: httpx.Client, target: _PublicTarget) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    if not isinstance(transport, httpx.HTTPTransport):
        raise RuntimeError("Public fetch client is not using the HTTP transport")
    backend = _SyncPinnedNetworkBackend()
    backend._target = target
    transport._pool._network_backend = backend  # type: ignore[attr-defined]


async def _connect_pinned_httpcore_async(
    *, client: httpx.AsyncClient, target: _PublicTarget
) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    if not isinstance(transport, httpx.AsyncHTTPTransport):
        raise RuntimeError("Public fetch client is not using the async HTTP transport")
    backend = _AsyncPinnedNetworkBackend()
    backend._target = target
    transport._pool._network_backend = backend  # type: ignore[attr-defined]


def _read_limited(chunks: Iterable[bytes], max_bytes: int) -> bytes:
    content = bytearray()
    for chunk in chunks:
        content.extend(chunk)
        if len(content) > max_bytes:
            raise ValueError(f"Remote document exceeds {max_bytes // (1024 * 1024)}MB limit")
    return bytes(content)


def _redirect_target(response: httpx.Response, current_url: str) -> str | None:
    if response.status_code not in {301, 302, 303, 307, 308}:
        return None
    location = response.headers.get("location")
    if not location:
        raise ValueError("Remote server returned a redirect without a location")
    return urljoin(current_url, location)


def fetch_public_url(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allowed_url: Callable[[str], bool] | None = None,
) -> tuple[bytes, str | None, str]:
    if allowed_url is not None and not allowed_url(url):
        raise ValueError("Public fetch URL denied by source policy")
    target = _resolve_public_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        transport=httpx.HTTPTransport(trust_env=False),
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _connect_pinned_httpcore(client=client, target=target)
            with client.stream(
                "GET",
                target.request_url,
                headers={"Host": target.host_header},
                extensions={"sni_hostname": target.sni_hostname},
            ) as response:
                target_value = _redirect_target(response, target.url)
                if target_value is not None:
                    if allowed_url is not None and not allowed_url(target_value):
                        raise ValueError("Public fetch redirect denied by source policy")
                    target = _resolve_public_url(target_value)
                    continue
                response.raise_for_status()
                content_length = _parse_content_length(response.headers.get("content-length"))
                if content_length is not None and content_length > max_bytes:
                    raise ValueError(
                        f"Remote document exceeds {max_bytes // (1024 * 1024)}MB limit"
                    )
                content = _read_limited(response.iter_bytes(), max_bytes)
                return content, response.headers.get("content-type"), target.url
    raise ValueError(f"Too many redirects (maximum {MAX_REDIRECTS})")


async def fetch_public_url_async(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str | None, str]:
    target = await _resolve_public_url_async(url)
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    headers = request_headers
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        transport=httpx.AsyncHTTPTransport(trust_env=False),
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _connect_pinned_httpcore_async(client=client, target=target)
            async with client.stream(
                "GET",
                target.request_url,
                headers={"Host": target.host_header},
                extensions={"sni_hostname": target.sni_hostname},
            ) as response:
                target_value = _redirect_target(response, target.url)
                if target_value is not None:
                    target = await _resolve_public_url_async(target_value)
                    continue
                response.raise_for_status()
                content_length = _parse_content_length(response.headers.get("content-length"))
                if content_length is not None and content_length > max_bytes:
                    raise ValueError(
                        f"Remote document exceeds {max_bytes // (1024 * 1024)}MB limit"
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError(
                            f"Remote document exceeds {max_bytes // (1024 * 1024)}MB limit"
                        )
                return bytes(content), response.headers.get("content-type"), target.url
    raise ValueError(f"Too many redirects (maximum {MAX_REDIRECTS})")
