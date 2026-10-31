"""Persistencia, alcance y prueba del proveedor LLM propio de un tenant."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.llm_settings_crypto import (
    LLMSettingsCryptoError,
    decrypt_api_key,
    encrypt_api_key,
    encryption_available,
    last4,
    needs_reencryption,
)
from app.llm.egress_guard import (
    PUBLIC_ONLY_MESSAGE,
    NonPublicAddressError,
    public_only_client,
)
from app.llm.tenant_config import (
    PROVIDER_CATALOG,
    PROVIDER_CUSTOM,
    TenantLLMConfig,
    current_tenant_llm_config,
    models_endpoint,
    normalize_model,
    normalize_provider,
    normalize_reasoning_effort,
    provider_catalog,
    reset_tenant_llm_config,
    set_tenant_llm_config,
    validate_base_url,
)
from app.models import TenantLLMSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TenantLLMUpdate:
    provider: str
    model: str
    base_url: str | None = None
    fallback_model: str | None = None
    reasoning_effort: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    enabled: bool = True


def read_tenant_row(db: Session, tenant_id: int | None = None) -> TenantLLMSettings | None:
    tenant_id = tenant_id if tenant_id is not None else db.info.get("tenant_id")
    if tenant_id is None:
        return None
    return db.scalar(
        select(TenantLLMSettings)
        .where(TenantLLMSettings.tenant_id == tenant_id)
        .execution_options(include_all_tenants=True)
    )


def config_from_row(
    row: TenantLLMSettings, settings: Settings | None = None
) -> TenantLLMConfig:
    settings = settings or get_settings()
    error: str | None = None
    provider = (row.provider or "").strip().lower()
    try:
        provider = normalize_provider(provider)
    except ValueError:
        error = "tenant_llm_provider_invalid"
        provider = provider or "custom"
    base_url = ""
    try:
        base_url = validate_base_url(provider, row.base_url)
    except ValueError:
        error = error or "tenant_llm_base_url_invalid"
        base_url = (row.base_url or "").strip()
    model = (row.model or "").strip()
    try:
        model = normalize_model(model)
    except ValueError:
        error = error or "tenant_llm_model_invalid"
    fallback_model = (row.fallback_model or "").strip() or None
    if fallback_model:
        try:
            fallback_model = normalize_model(fallback_model, field_name="fallback_model")
        except ValueError:
            error = error or "tenant_llm_fallback_model_invalid"
    try:
        reasoning_effort = normalize_reasoning_effort(row.reasoning_effort)
    except ValueError:
        error = error or "tenant_llm_reasoning_effort_invalid"
        reasoning_effort = None
    api_key: str | None = None
    if row.api_key_ciphertext:
        if not encryption_available(settings):
            error = "llm_settings_encryption_not_configured"
        else:
            try:
                api_key = decrypt_api_key(row.api_key_ciphertext, settings)
            except LLMSettingsCryptoError:
                error = "tenant_llm_settings_corrupt"
    return TenantLLMConfig(
        provider=provider,
        base_url=base_url,
        model=model,
        fallback_model=fallback_model,
        reasoning_effort=reasoning_effort,
        api_key=api_key,
        api_key_last4=row.api_key_last4,
        enabled=bool(row.enabled),
        billing_scope="tenant",
        error=error,
    )


def load_config_for_tenant(
    db: Session, tenant_id: int, settings: Settings | None = None
) -> TenantLLMConfig | None:
    try:
        row = read_tenant_row(db, tenant_id)
    except SQLAlchemyError:
        logger.warning("tenant LLM settings table unavailable", exc_info=True)
        # None means a confirmed absence of tenant settings and permits the
        # platform provider. A failed read cannot establish that absence.
        return TenantLLMConfig(
            provider=PROVIDER_CUSTOM,
            base_url="",
            model="",
            error="tenant_llm_settings_unavailable",
        )
    return config_from_row(row, settings) if row is not None else None


async def bind_tenant_llm_settings(
    db: Session = Depends(get_db),
) -> AsyncIterator[None]:
    """Fija el proveedor del tenant firmado durante todo el request."""
    token = set_tenant_llm_config(None)
    try:
        tenant_id = db.info.get("tenant_id")
        config = load_config_for_tenant(db, tenant_id) if tenant_id is not None else None
        reset_tenant_llm_config(token)
        token = set_tenant_llm_config(config)
        yield
    finally:
        reset_tenant_llm_config(token)


def _validated(
    update: TenantLLMUpdate,
) -> tuple[str, str, str, str | None, str | None]:
    provider = normalize_provider(update.provider)
    model = normalize_model(update.model)
    base_url = validate_base_url(provider, update.base_url)
    fallback_model = (update.fallback_model or "").strip() or None
    if fallback_model:
        fallback_model = normalize_model(fallback_model, field_name="fallback_model")
    reasoning_effort = normalize_reasoning_effort(update.reasoning_effort)
    return provider, model, base_url, fallback_model, reasoning_effort


class StoredKeyEndpointMismatch(ValueError):
    """La clave guardada pertenece a otro proveedor o URL."""


def _key_endpoint(provider: str | None, base_url: str | None) -> tuple[str, str] | None:
    """(proveedor, URL efectiva) a la que se envia la clave; None si no es valido."""
    try:
        normalized = normalize_provider(provider or "")
        return normalized, validate_base_url(normalized, base_url)
    except (KeyError, ValueError):
        return None


def _same_key_endpoint(row: TenantLLMSettings, provider: str, base_url: str | None) -> bool:
    stored = _key_endpoint(row.provider, row.base_url)
    return stored is not None and stored == _key_endpoint(provider, base_url)


def save_tenant_settings(
    db: Session,
    update: TenantLLMUpdate,
    settings: Settings | None = None,
) -> TenantLLMSettings:
    settings = settings or get_settings()
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Se requiere el contexto del tenant.")
    provider, model, base_url, fallback_model, reasoning_effort = _validated(update)
    row = read_tenant_row(db, tenant_id)
    new_key = update.api_key is not None and bool(update.api_key.strip())
    if (
        row is not None
        and row.api_key_ciphertext
        and not new_key
        and not update.clear_api_key
        and not _same_key_endpoint(row, provider, base_url)
    ):
        # La clave guardada solo vale para el proveedor/URL con que se guardo:
        # conservarla al cambiar de destino la enviaria a otro host.
        raise ValueError(
            "Has cambiado de proveedor o de URL: introduce la API key para el nuevo "
            "destino (la clave guardada no se envia a otro sitio)."
        )
    if row is None:
        row = TenantLLMSettings(tenant_id=tenant_id)
        db.add(row)
    row.provider = provider
    row.model = model
    row.base_url = base_url if provider == PROVIDER_CUSTOM else None
    row.fallback_model = fallback_model
    row.reasoning_effort = reasoning_effort
    row.enabled = bool(update.enabled)
    if update.clear_api_key:
        row.api_key_ciphertext = None
        row.api_key_last4 = None
    elif update.api_key is not None and update.api_key.strip():
        plaintext = update.api_key.strip()
        row.api_key_ciphertext = encrypt_api_key(plaintext, settings)
        row.api_key_last4 = last4(plaintext)
        row.key_version = 1
    elif row.api_key_ciphertext and needs_reencryption(row.api_key_ciphertext, settings):
        # Clave cifrada con una clave anterior (rotacion): se recifra con la
        # actual al guardar, para poder retirar la antigua despues.
        try:
            plaintext = decrypt_api_key(row.api_key_ciphertext, settings)
        except LLMSettingsCryptoError:
            plaintext = None
        if plaintext is not None:
            row.api_key_ciphertext = encrypt_api_key(plaintext, settings)
    db.flush()
    return row


def _platform_view(settings: Settings, db: Session) -> dict:
    del db
    from app.llm.readiness import llm_configuration_issue

    configured = llm_configuration_issue(settings) is None
    key_configured = bool((settings.opencode_go_api_key or "").strip())
    return {
        "source": "platform",
        "status": "platform" if configured else "disabled",
        "provider": settings.llm_provider or "opencode-go",
        "base_url": None,
        "model": settings.opencode_go_model if configured else None,
        "fallback_model": settings.opencode_go_fallback_model or None,
        "reasoning_effort": settings.opencode_go_reasoning_effort,
        "enabled": configured,
        "configured": configured,
        "api_key_configured": key_configured,
        "api_key_last4": None,
        "key_version": None,
        "billing_scope": "platform",
        "message": (
            "Estas usando el proveedor de GerarAI."
            if configured
            else "El proveedor de GerarAI no esta configurado."
        ),
    }


def settings_view(db: Session, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    view = _platform_view(settings, db)
    row = read_tenant_row(db)
    if row is None:
        view["encryption_available"] = encryption_available(settings)
        view["providers"] = provider_catalog()
        return view
    config = config_from_row(row, settings)
    if config.error or not row.enabled:
        status = "disabled"
    elif not config.has_api_key:
        status = "missing_key"
    else:
        status = "tenant"
    message = {
        "tenant": "Configurado con tu clave. El coste lo paga tu proveedor.",
        "missing_key": "Falta la clave del proveedor: la IA esta desactivada.",
        "disabled": "La IA propia esta desactivada o la configuracion es invalida.",
    }[status]
    view.update(
        {
            "source": "tenant",
            "status": status,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "fallback_model": config.fallback_model,
            "reasoning_effort": config.reasoning_effort,
            "enabled": bool(row.enabled),
            "configured": status == "tenant",
            "api_key_configured": bool(row.api_key_ciphertext),
            "api_key_last4": row.api_key_last4,
            "key_version": row.key_version,
            "billing_scope": "tenant",
            "error": config.error,
            "message": message,
        }
    )
    view["encryption_available"] = encryption_available(settings)
    view["providers"] = provider_catalog()
    return view


def stored_api_key(
    db: Session,
    settings: Settings | None = None,
    *,
    provider: str | None = None,
    base_url: str | None = None,
) -> str | None:
    """Clave guardada del tenant, descifrada.

    Con ``provider`` solo se devuelve si el destino (proveedor + URL efectiva)
    coincide con el guardado; si no, ``StoredKeyEndpointMismatch``.
    """
    row = read_tenant_row(db)
    if row is None or not row.api_key_ciphertext:
        return None
    if provider is not None and not _same_key_endpoint(row, provider, base_url):
        raise StoredKeyEndpointMismatch(
            "La clave guardada es de otro proveedor o URL; introduce la API key para probar este."
        )
    try:
        return decrypt_api_key(row.api_key_ciphertext, settings)
    except LLMSettingsCryptoError as exc:
        raise ValueError("No se pudo descifrar la clave guardada.") from exc


def _probe_client(provider: str) -> httpx.AsyncClient:
    """Cliente de la prueba: ``custom`` solo conecta a IPs publicas ya resueltas."""
    if PROVIDER_CATALOG[provider].requires_custom_url:
        return public_only_client(httpx.Timeout(5.0))
    return httpx.AsyncClient(
        timeout=httpx.Timeout(5.0), follow_redirects=False, trust_env=False
    )


# Cota de lectura del /models de la prueba: el listado real de cualquier
# proveedor cabe en decenas de KB, pero la base_url custom la define el
# tenant y un endpoint roto o malicioso podria responder un cuerpo infinito:
# sin cota, cada prueba de conexion bufferizaria todo en memoria del backend.
_PROBE_MAX_BODY_BYTES = 512 * 1024


async def _bounded_get(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> httpx.Response:
    """GET que nunca bufferiza mas de ``_PROBE_MAX_BODY_BYTES``.

    Lee en streaming y corta al llegar a la cota; el cuerpo truncado hace
    fallar el parseo despues (la prueba queda "no verificable", honesta) en
    vez de inflar la memoria del worker.
    """
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url, headers=headers) as response:
        status = response.status_code
        async for chunk in response.aiter_bytes(64 * 1024):
            chunks.append(chunk)
            total += len(chunk)
            if total >= _PROBE_MAX_BODY_BYTES:
                break
    return httpx.Response(status, content=b"".join(chunks))


def _model_ids(response: httpx.Response) -> set[str] | None:
    """Ids del listado /models (forma OpenAI {"data": [{"id": ...}]}).

    None = la respuesta no es una lista de modelos legible: la prueba falla
    honesta en vez de dar por bueno un modelo quizas inexistente.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    ids = {item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}
    return ids if ids or not data else None


async def probe_connection(
    *, provider: str, base_url: str | None, api_key: str, model: str
) -> dict:
    """GET {base_url}/models con 5 s y sin reintentos; nunca devuelve la clave."""
    provider = normalize_provider(provider)
    url = validate_base_url(provider, base_url)
    normalize_model(model)
    endpoint = models_endpoint(url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "gerarai/1.0",
    }
    try:
        async with _probe_client(provider) as client:
            response = await _bounded_get(client, endpoint, headers)
    except httpx.TimeoutException:
        return {
            "ok": False,
            "status_code": None,
            "provider": provider,
            "base_url": url,
            "model": model,
            "message": "El proveedor no respondio en 5 segundos.",
        }
    except httpx.HTTPError as exc:
        non_public = isinstance(exc.__cause__, NonPublicAddressError)
        return {
            "ok": False,
            "status_code": None,
            "provider": provider,
            "base_url": url,
            "model": model,
            "message": (
                PUBLIC_ONLY_MESSAGE
                if non_public
                else "No se pudo conectar con el proveedor."
            ),
        }
    if not (200 <= response.status_code < 300):
        return {
            "ok": False,
            "status_code": response.status_code,
            "provider": provider,
            "base_url": url,
            "model": model,
            "message": f"El proveedor respondio HTTP {response.status_code}.",
        }
    # La conexion responde, pero la prueba tambien exige que el MODELO pedido
    # exista en el proveedor: un "Conexion correcta" con un modelo inventado
    # romperia cada llamada real despues (hallazgo front, medido en prod con
    # model="modelo-inventado-123"). No gasta tokens: solo lee /models.
    model_ids = _model_ids(response)
    if model_ids is None:
        return {
            "ok": False,
            "status_code": response.status_code,
            "provider": provider,
            "base_url": url,
            "model": model,
            "message": "El proveedor respondio, pero sin una lista de modelos legible: no se pudo verificar el modelo.",
        }
    if model not in model_ids:
        return {
            "ok": False,
            "status_code": response.status_code,
            "provider": provider,
            "base_url": url,
            "model": model,
            "message": f"El modelo '{model}' no existe en este proveedor. Revisa el nombre exacto en su lista de modelos.",
        }
    return {
        "ok": True,
        "status_code": response.status_code,
        "provider": provider,
        "base_url": url,
        "model": model,
        "message": "Conexion correcta.",
    }


def catalog_defaults(provider: str) -> tuple[str, str]:
    provider = normalize_provider(provider)
    spec = PROVIDER_CATALOG[provider]
    return spec.base_url, spec.default_model


def current_config_is_tenant() -> bool:
    return current_tenant_llm_config() is not None
