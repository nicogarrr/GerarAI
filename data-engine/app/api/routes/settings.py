from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import MSG_IDENTITY_REQUIRED
from app.core.config import get_settings
from app.core.database import get_db
from app.core.llm_settings_crypto import (
    LLMSettingsCryptoError,
    encryption_available,
)
from app.core.rate_limit import enforce_llm_test_rate_limit
from app.llm.factory import create_llm_provider
from app.llm.tenant_config import current_tenant_llm_config
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
            detail=(
                "El cifrado de claves no esta configurado "
                "(LLM_SETTINGS_ENCRYPTION_KEY); no se ha guardado nada."
            ),
        )
    try:
        save_tenant_settings(db, update, app_settings)
        db.commit()
    except LLMSettingsCryptoError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="El cifrado de claves no esta disponible; no se ha guardado nada.",
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
                detail="No se pudo leer la clave guardada; vuelve a introducirla.",
            ) from exc
    if not key:
        raise HTTPException(
            status_code=422,
            detail="Introduce una API key para probar la conexion.",
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
        raise HTTPException(status_code=503, detail="El cifrado no está disponible. No se ha guardado el token.")
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
        receipt_id = await run_in_threadpool(ibkr.start_receipt, db, revision=revision)
        xml = await ibkr.download(token, query_id)
        return await run_in_threadpool(ibkr.import_report, db, xml, account_id, revision, receipt_id=receipt_id)
    except ibkr.SyncBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        await run_in_threadpool(ibkr.record_failure, db, revision=revision, receipt_id=receipt_id)
        detail = str(exc) if isinstance(exc, ibkr.ConnectionError) else "No se pudo sincronizar IBKR. Conservamos los datos anteriores."
        raise HTTPException(status_code=422, detail=detail) from None
    finally:
        if entered:
            await run_in_threadpool(lease.__exit__, None, None, None)
