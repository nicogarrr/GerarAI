from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import MSG_IDENTITY_REQUIRED
from app.core.config import get_settings
from app.core.database import get_db
from app.core.llm_settings_crypto import (
    LLMSettingsCryptoError,
    encryption_available,
)
from app.core.rate_limit import enforce_llm_test_rate_limit
from app.core.ui_errors import ui_error
from app.llm.base import breaker_snapshot
from app.llm.chat_provider import (
    GEMINI_MODEL,
    GEMINI_MODEL_2,
    GO_SUBSCRIPTION_PROVIDER,
    OPENCODE_FREE_PROVIDER,
)
from app.llm.factory import create_llm_provider
from app.llm.opencode_usage import fetch_go_usage
from app.llm.tenant_config import current_tenant_llm_config
from app.models.entities import BudgetUsage
from app.services.budget import BudgetController
from app.services.jev_availability import credit_status
from app.services.llm_router import route_table
from app.services.tenant_llm_settings_service import (
    StoredKeyEndpointMismatch,
    TenantLLMUpdate,
    probe_connection,
    save_tenant_settings,
    settings_view,
    stored_api_key,
)

router = APIRouter()


class LLMProviderEntry(BaseModel):
    id: str
    label: str
    base_url: str
    default_model: str
    requires_custom_url: bool


class LLMSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: Literal["platform", "tenant"]
    status: str
    provider: str
    base_url: str | None = None
    model: str | None = None
    fallback_model: str | None = None
    reasoning_effort: str | None = None
    enabled: bool
    configured: bool
    api_key_configured: bool
    api_key_last4: str | None = None
    key_version: int | None = None
    billing_scope: str
    encryption_available: bool
    message: str
    error: str | None = None
    providers: list[LLMProviderEntry]


class LLMSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    fallback_model: str | None = Field(default=None, max_length=200)
    reasoning_effort: str | None = Field(default=None, max_length=20)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    enabled: bool = True


class LLMTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class LLMTestResponse(BaseModel):
    ok: bool
    status_code: int | None
    provider: str
    base_url: str
    model: str
    message: str


def _require_tenant(db: Session) -> int:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(
            status_code=401, detail=MSG_IDENTITY_REQUIRED
        )
    return tenant_id


def maf_version() -> str:
    """Versión MAF real desde metadata del paquete (nunca hardcodeada)."""
    try:
        return f"agent-framework-core=={_pkg_version('agent-framework-core')}"
    except PackageNotFoundError:
        return "agent-framework-core==unknown"


@router.get("/llm", response_model=LLMSettingsResponse)
def get_llm_settings(db: Session = Depends(get_db)) -> dict:
    return settings_view(db, get_settings())


# Topes publicados del nivel gratuito de AI Studio (medidos 2026-11-01):
# RPM/RPD/TPM por modelo. El consumo real no lo expone Google por API; el
# panel lo estima con los contadores propios.
GEMINI_FREE_PUBLISHED_LIMITS = {
    GEMINI_MODEL: {"rpm": 15, "rpd": 500, "tpm": 250_000},
    GEMINI_MODEL_2: {"rpm": 5, "rpd": 20},
}


class LlmUsageLeg(BaseModel):
    id: str
    label: str
    provider: str
    model: str | None = None
    active: bool
    state: str  # ok | limited | off
    estimated: bool
    limited_until: str | None = None
    quota: dict | None = None
    today: dict | None = None
    published_limits: dict | None = None


class LlmUsageResponse(BaseModel):
    source: Literal["platform", "tenant"]
    generated_at: str
    legs: list[LlmUsageLeg]
    message: str | None = None


def _platform_usage_today(db: Session, models: list[str]) -> dict:
    """Llamadas y tokens de hoy registrados para esos modelos (toda la plataforma).

    La clave Go/Gemini de GerarAI sirve a todos los tenants, asi que el
    agregado es global a proposito: lectura de operacion del panel de uso,
    por eso ``include_all_tenants``. Son contadores PROPIOS (BudgetUsage),
    la base de las cifras estimadas cuando el proveedor no expone su cuota.
    """
    today = date.today()
    calls, tokens = db.execute(
        select(
            func.count(BudgetUsage.id),
            func.coalesce(func.sum(BudgetUsage.token_count), 0),
        )
        .where(BudgetUsage.usage_date == today, BudgetUsage.model.in_(models))
        .execution_options(include_all_tenants=True)
    ).one()
    return {"date": today.isoformat(), "calls": int(calls or 0), "tokens": int(tokens or 0)}


@router.get("/llm/usage", response_model=LlmUsageResponse)
async def get_llm_usage(db: Session = Depends(get_db)) -> dict:
    """Panel de uso de la cadena de plataforma (Ajustes).

    Go: cuota REAL del proveedor (GET /zen/go/v1/usage, verificado
    2026-11-01). OpenCode free y Gemini: sin API de cuota publica, se
    muestran los contadores propios marcados como estimados y el estado del
    breaker de cuota (abierto hasta el reset/Retry-After del proveedor).
    Tenants con clave propia (BYOK): su consumo es cosa de su proveedor.
    """
    app_settings = get_settings()
    if current_tenant_llm_config() is not None:
        return {
            "source": "tenant",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "legs": [],
            "message": "tenant_byok",
        }
    snapshot = breaker_snapshot()

    def limited_until(provider: str) -> str | None:
        entries = [b for b in snapshot if b["provider"] == provider]
        if not entries:
            return None
        until = max(float(b["until"]) for b in entries)
        return datetime.fromtimestamp(until, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    legs: list[dict] = []

    go_active = bool(
        app_settings.chat_go_subscription_enabled
        and (app_settings.opencode_go_api_key or "").strip()
    )
    quota = None
    if go_active:
        raw = await fetch_go_usage(
            app_settings.chat_go_subscription_base_url,
            app_settings.opencode_go_api_key or "",
            session=app_settings.opencode_go_session,
        )
        if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
            quota = raw["usage"]
    go_until = limited_until(GO_SUBSCRIPTION_PROVIDER)
    weekly = (quota or {}).get("weekly") or {}
    go_state = "off"
    if go_active:
        go_state = (
            "limited"
            if go_until
            or weekly.get("status") == "rate-limited"
            or (weekly.get("percent") or 0) >= 100
            else "ok"
        )
    legs.append({
        "id": "opencode-go",
        "label": "OpenCode Go",
        "provider": GO_SUBSCRIPTION_PROVIDER,
        "model": app_settings.opencode_go_model,
        "active": go_active,
        "state": go_state,
        "estimated": False,
        "limited_until": go_until,
        "quota": quota,
        "today": _platform_usage_today(db, [app_settings.opencode_go_model]),
    })

    free_active = app_settings.opencode_free_chat_fallback_active
    free_model = (app_settings.opencode_free_model or "").strip()
    free_until = limited_until(OPENCODE_FREE_PROVIDER)
    legs.append({
        "id": "opencode-free",
        "label": "OpenCode free",
        "provider": OPENCODE_FREE_PROVIDER,
        "model": free_model,
        "active": free_active,
        "state": "off" if not free_active else ("limited" if free_until else "ok"),
        "estimated": True,
        "limited_until": free_until,
        "today": _platform_usage_today(db, [free_model]) if free_model else None,
    })

    gemini_active = app_settings.gemini_chat_fallback_active
    gemini_until = limited_until("gemini")
    legs.append({
        "id": "gemini",
        "label": "Gemini (AI Studio)",
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "active": gemini_active,
        "state": "off" if not gemini_active else ("limited" if gemini_until else "ok"),
        "estimated": True,
        "limited_until": gemini_until,
        "today": _platform_usage_today(db, [GEMINI_MODEL, GEMINI_MODEL_2]),
        "published_limits": GEMINI_FREE_PUBLISHED_LIMITS,
    })

    return {
        "source": "platform",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "legs": legs,
        "message": None,
    }


@router.put("/llm", response_model=LLMSettingsResponse)
def update_llm_settings(
    payload: LLMSettingsUpdateRequest,
    db: Session = Depends(get_db),
) -> dict:
    _require_tenant(db)
    app_settings = get_settings()
    update = TenantLLMUpdate(
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        fallback_model=payload.fallback_model,
        reasoning_effort=payload.reasoning_effort,
        api_key=payload.api_key,
        clear_api_key=payload.clear_api_key,
        enabled=payload.enabled,
    )
    if update.api_key and update.api_key.strip() and not encryption_available(app_settings):
        raise HTTPException(
            status_code=503,
            detail=ui_error(503, "encryption_keys_not_configured").detail,
        )
    try:
        save_tenant_settings(db, update, app_settings)
        db.commit()
    except LLMSettingsCryptoError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=ui_error(503, "encryption_keys_unavailable").detail,
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return settings_view(db, app_settings)


@router.post(
    "/llm/test",
    response_model=LLMTestResponse,
    dependencies=[Depends(enforce_llm_test_rate_limit)],
)
async def test_llm_settings(
    payload: LLMTestRequest,
    db: Session = Depends(get_db),
) -> dict:
    _require_tenant(db)
    app_settings = get_settings()
    key = (payload.api_key or "").strip()
    if not key:
        try:
            key = (
                stored_api_key(
                    db,
                    app_settings,
                    provider=payload.provider,
                    base_url=payload.base_url,
                )
                or ""
            )
        except StoredKeyEndpointMismatch as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=ui_error(502, "saved_key_unreadable").detail,
            ) from exc
    if not key:
        raise HTTPException(
            status_code=422,
            detail="Introduce una API key para probar la conexión.",
        )
    try:
        return await probe_connection(
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=key,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def settings(db: Session = Depends(get_db)) -> dict:
    app_settings = get_settings()
    provider = create_llm_provider(app_settings)
    tenant = current_tenant_llm_config()
    llm_status: dict = {
        "provider": provider.name,
        "configured": provider.name != "disabled",
        # Model only when active; the API key is never exposed here.
        "model": app_settings.opencode_go_model if provider.name != "disabled" else None,
    }
    if tenant is not None:
        llm_status.update(
            {
                "provider": tenant.provider,
                "configured": provider.name != "disabled",
                "model": tenant.model,
                "source": "tenant",
                "billing_scope": "tenant",
                "api_key_configured": tenant.has_api_key,
                "api_key_last4": tenant.api_key_last4,
            }
        )
        if provider.name == "disabled":
            llm_status["reason"] = getattr(provider, "reason", "disabled")
        return {
            "app_env": app_settings.app_env,
            "maf_version": maf_version(),
            "budget": BudgetController().current_usage(
                db, admin=db.info.get("tenant_id") is None
            ),
            "routes": route_table(),
            "llm": llm_status,
            "connectors": {
                "typesafe": credit_status(),
                "fmp": bool(app_settings.fmp_api_key),
                "ibkr": bool(app_settings.ibkr_flex_token and app_settings.ibkr_flex_query_id),
                "fred": bool(app_settings.fred_api_key),
                "manual_transcript_import": "available",
                "langfuse": app_settings.langfuse_enabled,
                "qdrant_url": bool(app_settings.qdrant_url),
            },
        }
    # Cascada gratuita: el modelo depende del miembro que responda; se listan
    # los miembros en orden (sin claves ni URLs).
    members = getattr(provider, "member_names", None)
    if members:
        llm_status["model"] = None
        llm_status["members"] = members
    if provider.name == "disabled":
        llm_status["reason"] = getattr(provider, "reason", "disabled")
    return {
        "app_env": app_settings.app_env,
        "maf_version": maf_version(),
        # Vista de operacion: con sesion autenticada muestra el consumo del
        # tenant; sin contexto (sesion anonima), el agregado global es el
        # contexto admin y se pide explicitamente.
        "budget": BudgetController().current_usage(
            db, admin=db.info.get("tenant_id") is None
        ),
        "routes": route_table(),
        "llm": llm_status,
        "connectors": {
            "typesafe": credit_status(),
            "fmp": bool(app_settings.fmp_api_key),
            "ibkr": bool(app_settings.ibkr_flex_token and app_settings.ibkr_flex_query_id),
            "fred": bool(app_settings.fred_api_key),
            "manual_transcript_import": "available",
            "langfuse": app_settings.langfuse_enabled,
            # Booleano de presencia: la URL (posible secreto de red) jamás
            # sale por la API.
            "qdrant_url": bool(app_settings.qdrant_url),
        },
    }


class IBKRConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(repr=False)
    query_id: str = Field(min_length=1, max_length=32)
    account_id: str = Field(min_length=3, max_length=64)
    complete_query: bool = False


@router.get("/ibkr")
def get_ibkr_connection(db: Session = Depends(get_db)) -> dict:
    from app.services import ibkr_connection_service as ibkr
    _require_tenant(db)
    return ibkr.view(db)


@router.put("/ibkr", dependencies=[Depends(enforce_llm_test_rate_limit)])
async def connect_ibkr(payload: IBKRConnectRequest, db: Session = Depends(get_db)) -> dict:
    from starlette.concurrency import run_in_threadpool

    from app.services import ibkr_connection_service as ibkr
    _require_tenant(db)
    settings = get_settings()
    if not encryption_available(settings):
        raise HTTPException(status_code=503, detail=ui_error(503, "encryption_unavailable_token").detail)
    try:
        token, query_id, account_id = ibkr.validate_input(payload.token, payload.query_id, payload.account_id)
        # Release the auth read transaction before waiting for IBKR.
        await run_in_threadpool(db.commit)
        xml = await ibkr.download(token, query_id)
        statement_date = ibkr.check_report(xml, account_id)
        return await run_in_threadpool(
            ibkr.save_connection, db, settings, token=token, query_id=query_id,
            account_id=account_id, complete_query=payload.complete_query,
            statement_date=statement_date,
        )
    except ibkr.SyncBusy as exc:
        await run_in_threadpool(db.rollback)
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (ibkr.ConnectionError, LLMSettingsCryptoError) as exc:
        await run_in_threadpool(db.rollback)
        detail = str(exc) if isinstance(exc, ibkr.ConnectionError) else "El cifrado no está disponible. No se ha guardado el token."
        raise HTTPException(status_code=422, detail=detail) from None


@router.delete("/ibkr")
def disconnect_ibkr(db: Session = Depends(get_db)) -> dict:
    from app.services import ibkr_connection_service as ibkr
    _require_tenant(db)
    try:
        return ibkr.disconnect(db)
    except ibkr.SyncBusy as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/ibkr/sync", dependencies=[Depends(enforce_llm_test_rate_limit)])
async def sync_ibkr_connection(db: Session = Depends(get_db)) -> dict:
    from starlette.concurrency import run_in_threadpool

    from app.services import ibkr_connection_service as ibkr
    _require_tenant(db)
    revision: int | None = None
    receipt_id: int | None = None
    lease = ibkr.sync_lease(db)
    entered = False
    try:
        await run_in_threadpool(lease.__enter__)
        entered = True
        token, query_id, account_id, revision = await run_in_threadpool(ibkr.credentials, db, get_settings())
        receipt_id = await run_in_threadpool(ibkr.start_receipt, db, revision=revision, origin="manual")
        xml = await ibkr.download(token, query_id)
        return await run_in_threadpool(ibkr.import_report, db, xml, account_id, revision, receipt_id=receipt_id)
    except ibkr.SyncBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        await run_in_threadpool(ibkr.record_failure, db, revision=revision, receipt_id=receipt_id,
                                error_code=ibkr.error_kind(exc))
        detail = str(exc) if isinstance(exc, ibkr.ConnectionError) else "No se pudo sincronizar IBKR. Conservamos los datos anteriores."
        raise HTTPException(status_code=422, detail=detail) from None
    finally:
        if entered:
            await run_in_threadpool(lease.__exit__, None, None, None)

# No service-wide env mutation: these settings belong to the signed tenant.
from app.api.routes.dca_settings import router as dca_settings_router

router.include_router(dca_settings_router, prefix="/dca", tags=["settings"])
