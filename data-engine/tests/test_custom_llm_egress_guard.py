"""Proveedor LLM ``custom``: sin SSRF por formas numericas, DNS a IP privada ni redirects.

Sin red real: el resolver DNS se sustituye y la conexion TCP subyacente se
registra sin abrirse. Nada toca infraestructura privada ni produccion.
"""

from __future__ import annotations

import asyncio
import socket

import httpcore
import httpx
import pytest

from app.core.config import Settings
from app.llm import egress_guard
from app.llm.contracts import LLMRequest, Message
from app.llm.factory import create_llm_provider
from app.llm.tenant_config import (
    TenantLLMConfig,
    tenant_llm_config_scope,
    validate_base_url,
)
from app.services.tenant_llm_settings_service import probe_connection

KEY = "sk-egress-test-key-1234"
PUBLIC = "93.184.216.34"


def _infos(*addresses: str):
    return [
        (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443))
        for a in addresses
    ]


@pytest.fixture
def net(monkeypatch):
    """Resolver sintetico + registro de conexiones TCP que se habrian abierto."""
    table: dict[str, list[str]] = {}
    connects: list[tuple[str, int]] = []

    async def resolver(host, port):
        if host not in table:
            raise socket.gaierror("synthetic: unknown host")
        return _infos(*table[host])

    async def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        connects.append((host, port))
        raise httpcore.ConnectError("synthetic: no real socket")

    monkeypatch.setattr(egress_guard, "_resolver", resolver)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fake_connect)
    return table, connects


@pytest.mark.parametrize(
    "url",
    [
        "https://127.1/v1",
        "https://0x7f.1/v1",
        "https://2130706433/v1",
        "https://0177.0.0.1/v1",
        "https://017700000001/v1",
        "https://10.0.0.1/v1",
        "https://169.254.169.254/v1",
        "https://[::ffff:127.0.0.1]/v1",
        "https://[2002:7f00:1::]/v1",
        "https://[::1]/v1",
        "https://localhost/v1",
        "https://\uff11\uff12\uff17.0.0.1/v1",
    ],
)
def test_validator_rejects_loopback_private_and_noncanonical_numeric_hosts(url) -> None:
    with pytest.raises(ValueError):
        validate_base_url("custom", url)


@pytest.mark.parametrize(
    "url", ["https://llm.example.com/v1", "https://api.my-provider.ai/openai/v1/", "https://93.184.216.34/v1"]
)
def test_validator_keeps_legitimate_public_hosts(url) -> None:
    assert validate_base_url("custom", url).startswith("https://")


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.1.2.3"],
        ["192.168.0.5"],
        ["169.254.169.254"],
        ["100.64.0.1"],
        ["::1"],
        ["::ffff:127.0.0.1"],
        [PUBLIC, "10.0.0.8"],  # una sola direccion privada basta para rechazar
    ],
)
def test_backend_blocks_hosts_resolving_to_non_public_before_any_socket(net, addresses) -> None:
    table, connects = net
    table["rebind.example.com"] = addresses
    with pytest.raises(egress_guard.NonPublicAddressError):
        asyncio.run(egress_guard.PublicOnlyBackend().connect_tcp("rebind.example.com", 443))
    assert connects == []


def test_backend_connects_to_validated_ip_not_the_name(net) -> None:
    table, connects = net
    table["llm.example.com"] = [PUBLIC]
    with pytest.raises(httpcore.ConnectError):
        asyncio.run(egress_guard.PublicOnlyBackend().connect_tcp("llm.example.com", 443))
    assert connects == [(PUBLIC, 443)]  # IP fijada: sin segunda resolucion por nombre


def test_probe_blocks_dns_to_loopback_and_does_not_send_the_key(net) -> None:
    table, connects = net
    table["sneaky.example.com"] = ["127.0.0.1"]
    result = asyncio.run(
        probe_connection(
            provider="custom", base_url="https://sneaky.example.com/v1", api_key=KEY, model="m"
        )
    )
    assert result["ok"] is False
    assert result["message"] == egress_guard.PUBLIC_ONLY_MESSAGE
    assert connects == []
    assert KEY not in str(result)


def test_probe_public_host_connects_to_resolved_public_ip(net) -> None:
    table, connects = net
    table["llm.example.com"] = [PUBLIC]
    result = asyncio.run(
        probe_connection(
            provider="custom", base_url="https://llm.example.com/v1", api_key=KEY, model="m"
        )
    )
    assert connects == [(PUBLIC, 443)]
    assert result["message"] == "No se pudo conectar con el proveedor."  # fallo sintetico de socket


def test_runtime_custom_provider_is_guarded_and_ignores_injected_client(net) -> None:
    table, connects = net
    table["sneaky.example.com"] = ["10.0.0.9"]
    injected_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        injected_calls.append(str(request.url))
        return httpx.Response(200, json={})

    injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = TenantLLMConfig(
        provider="custom",
        base_url="https://sneaky.example.com/v1",
        model="m",
        api_key=KEY,
    )
    settings = Settings(_env_file=None, app_env="test")
    with tenant_llm_config_scope(config):
        provider = create_llm_provider(settings, client=injected)
    assert provider.public_only is True
    with pytest.raises(Exception):
        asyncio.run(provider.complete(LLMRequest([Message("user", "hola")], task="chat", cache=False)))
    assert connects == []
    assert injected_calls == []


def test_known_catalog_providers_are_not_restricted() -> None:
    config = TenantLLMConfig(provider="openai", base_url="https://api.openai.com/v1", model="m", api_key=KEY)
    settings = Settings(_env_file=None, app_env="test")
    with tenant_llm_config_scope(config):
        provider = create_llm_provider(settings)
    assert provider.public_only is False


def test_guarded_client_never_follows_redirects_or_reads_proxy_env() -> None:
    client = egress_guard.public_only_client(5.0)
    try:
        assert client.follow_redirects is False
        assert client.trust_env is False
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "address",
    [
        "224.0.0.1",
        "239.255.255.250",
        "255.255.255.255",
        "0.0.0.0",
        "ff02::1",
        "fec0::1",
        "::127.0.0.1",
        "::8.8.8.8",
        "::ffff:0:127.0.0.1",
        "::ffff:0:8.8.8.8",
        "64:ff9b:1::1",
        "::",
        "::1",
        "fe80::1",
        "fc00::1",
        "2001:db8::1",
    ],
)
def test_is_public_ip_rejects_special_prefixes(address) -> None:
    assert egress_guard.is_public_ip(address) is False


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "93.184.216.34", "::ffff:8.8.8.8", "2001:4860:4860::8888"],
)
def test_is_public_ip_keeps_public_addresses(address) -> None:
    assert egress_guard.is_public_ip(address) is True


def test_public_literal_validator_and_backend_still_pass_public_host(net) -> None:
    table, connects = net
    table["llm.example.com"] = ["2001:4860:4860::8888"]
    assert validate_base_url("custom", "https://llm.example.com/v1")
    with pytest.raises(httpcore.ConnectError):
        asyncio.run(egress_guard.PublicOnlyBackend().connect_tcp("llm.example.com", 443))
    assert connects == [("2001:4860:4860::8888", 443)]


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:127.0.0.1", "::127.0.0.1", "::ffff:169.254.169.254", "::169.254.169.254",
        "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "64:ff9b:1::a00:1",
        "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:80ff:fffe",
    ],
)
def test_is_public_ip_rejects_ipv4_embedded_in_ipv6(address):
    from app.llm.egress_guard import is_public_ip

    assert is_public_ip(address) is False
