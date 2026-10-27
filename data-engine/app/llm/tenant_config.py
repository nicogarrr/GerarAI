"""Catalogo y alcance (ContextVar) del proveedor LLM propio de cada tenant.

El ContextVar se fija por request firmado (``bind_tenant_llm_settings``) y por
mensaje de Dramatiq (middleware). Las factorias consultan SIEMPRE este alcanze:
sin fila se conserva el camino global de OpenCode Go; con una fila invalida o
sin clave se devuelve ``DisabledProvider`` y jamas se usa la clave de la
plataforma.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from app.llm.egress_guard import is_public_ip

PROVIDER_CUSTOM = "custom"

CUSTOM_HOST_BLOCKLIST = frozenset(
    {
        "localhost",
        "host.docker.internal",
        "metadata.google.internal",
    }
)
CUSTOM_HOST_SUFFIX_BLOCKLIST = (".local", ".internal", ".localhost", ".localdomain")

_NUMERIC_LAST_LABEL = re.compile(r"^(\d+|0x[0-9a-f]*)$")
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

REASONING_EFFORTS: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "max")


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str
    label: str
    base_url: str
    default_model: str
    requires_custom_url: bool = False


PROVIDER_CATALOG: dict[str, ProviderSpec] = {
    "opencode-go": ProviderSpec(
        "opencode-go", "OpenCode Go", "https://opencode.ai/zen/go/v1", "deepseek-v4.1-flash"
    ),
    "openrouter": ProviderSpec(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "google/gemma-4-31b-it:free",
    ),
    "gemini": ProviderSpec(
        "gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.5-flash-lite",
    ),
    "openai": ProviderSpec(
        "openai", "OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"
    ),
    "groq": ProviderSpec(
        "groq", "Groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b"
    ),
    "custom": ProviderSpec(
        "custom",
        "Otro compatible con OpenAI",
        "",
        "",
        requires_custom_url=True,
    ),
}


def provider_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "base_url": spec.base_url,
            "default_model": spec.default_model,
            "requires_custom_url": spec.requires_custom_url,
        }
        for spec in PROVIDER_CATALOG.values()
    ]


def normalize_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    if not _PROVIDER_PATTERN.match(provider) or provider not in PROVIDER_CATALOG:
        raise ValueError("El proveedor no esta en el catalogo.")
    return provider


def normalize_model(value: str, *, field_name: str = "model") -> str:
    model = (value or "").strip()
    if not model:
        raise ValueError(f"El campo {field_name} es obligatorio.")
    if not _MODEL_PATTERN.match(model):
        raise ValueError(f"El campo {field_name} no es un identificador de modelo valido.")
    return model


def normalize_reasoning_effort(value: str | None) -> str | None:
    effort = (value or "").strip().lower()
    if not effort:
        return None
    if effort not in REASONING_EFFORTS:
        raise ValueError("El nivel de razonamiento no es valido.")
    return effort


def validate_base_url(provider: str, value: str | None) -> str:
    """URL efectiva del proveedor; ``custom`` exige HTTPS publico.

    Se rechazan credenciales en la URL, loopback/privadas/reservadas,
    nombres internos y hosts de un solo nivel. Los proveedores conocidos usan
    siempre la URL del catalogo (una URL alternativa podria cobrar como otro).
    """
    spec = PROVIDER_CATALOG[provider]
    if not spec.requires_custom_url:
        return spec.base_url
    raw = (value or "").strip()
    if not raw:
        raise ValueError("El proveedor personalizado exige una base_url.")
    if len(raw) > 500:
        raise ValueError("La base_url es demasiado larga.")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise ValueError("La base_url no es valida.") from exc
    if parts.scheme != "https":
        raise ValueError("La base_url debe usar HTTPS.")
    if not parts.hostname:
        raise ValueError("La base_url debe incluir un host.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("La base_url no puede incluir credenciales.")
    if parts.query or parts.fragment:
        raise ValueError("La base_url no puede incluir query ni fragmento.")
    host = parts.hostname.strip().lower().rstrip(".")
    if not host.isascii():
        raise ValueError("La base_url debe usar un host ASCII (punycode).")
    if (
        host in CUSTOM_HOST_BLOCKLIST
        or host.endswith(CUSTOM_HOST_SUFFIX_BLOCKLIST)
        or "." not in host
    ):
        raise ValueError("La base_url debe apuntar a un host publico.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not is_public_ip(address):
        raise ValueError("La base_url no puede apuntar a una IP privada o reservada.")
    if address is None and _NUMERIC_LAST_LABEL.match(host.rsplit(".", 1)[-1]):
        # 127.1, 0x7f.1, 2130706433...: formas numericas que el sistema operativo
        # interpreta como IPv4 pero ``ipaddress`` no. Solo se admite la forma canonica.
        raise ValueError("La base_url debe usar un nombre de host o una IP en forma canonica.")
    # Esto es solo texto: la resolucion DNS y la IP real se comprueban al conectar
    # (app.llm.egress_guard), tambien en la prueba de conexion.
    path = parts.path.rstrip("/")
    return urlunsplit(("https", parts.netloc, path, "", ""))


def models_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


@dataclass(frozen=True, slots=True)
class TenantLLMConfig:
    provider: str
    base_url: str
    model: str
    fallback_model: str | None = None
    reasoning_effort: str | None = None
    api_key: str | None = field(default=None, repr=False)
    api_key_last4: str | None = None
    enabled: bool = True
    billing_scope: str = "tenant"
    error: str | None = None

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key and self.api_key.strip())


_current_config: ContextVar[TenantLLMConfig | None] = ContextVar(
    "tenant_llm_config", default=None
)


def current_tenant_llm_config() -> TenantLLMConfig | None:
    return _current_config.get()


def set_tenant_llm_config(config: TenantLLMConfig | None) -> Token:
    return _current_config.set(config)


def reset_tenant_llm_config(token: Token) -> None:
    _current_config.reset(token)


@contextmanager
def tenant_llm_config_scope(config: TenantLLMConfig | None) -> Iterator[None]:
    token = set_tenant_llm_config(config)
    try:
        yield
    finally:
        reset_tenant_llm_config(token)
