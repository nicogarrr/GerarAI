"""Preferencia de idioma de generacion del tenant (i18n B).

El idioma elegido en Ajustes (cookie gerarai_locale en el frontend) se
persiste aqui para que lo usen TAMBIEN los flujos sin peticion: trabajos de
fondo (tesis programadas, narrativas de noticias) y cualquier llamada al
motor que no traiga la cabecera X-GerarAI-Language.

Con I18N_GENERATION_ENABLED apagado la preferencia se guarda pero no cambia
nada: todo se sigue generando en espanol (ver app/core/i18n.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import MSG_IDENTITY_REQUIRED
from app.core.database import get_db
from app.core.i18n import SUPPORTED_LANGUAGES, resolve_language, tenant_stored_language
from app.core.ui_errors import ui_error
from app.models import Tenant

router = APIRouter()


class LanguageOut(BaseModel):
    language: str
    supported: list[str]
    # Honestidad de despliegue: con el flag apagado la eleccion se guarda
    # pero la generacion sigue en espanol hasta que el operador lo encienda.
    generation_enabled: bool


class LanguageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str


def _tenant_or_401(db: Session) -> Tenant:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=401, detail=MSG_IDENTITY_REQUIRED)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise HTTPException(status_code=401, detail=MSG_IDENTITY_REQUIRED)
    return tenant


@router.get("/language", response_model=LanguageOut)
def read_language(db: Session = Depends(get_db)) -> dict:
    from app.core.i18n import language_enabled

    _tenant_or_401(db)
    return {
        "language": tenant_stored_language(db) or "es",
        "supported": list(SUPPORTED_LANGUAGES),
        "generation_enabled": language_enabled(),
    }


@router.put("/language", response_model=LanguageOut)
def update_language(payload: LanguageUpdate, db: Session = Depends(get_db)) -> dict:
    from app.core.i18n import language_enabled

    tenant = _tenant_or_401(db)
    requested = payload.language.strip().lower().replace("_", "-").split("-", 1)[0]
    if requested not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=ui_error(422, "unsupported_language", language=payload.language, supported=", ".join(SUPPORTED_LANGUAGES)).detail,
        )
    language = resolve_language(payload.language)
    meta = dict(tenant.metadata_ or {})
    meta["language"] = language
    tenant.metadata_ = meta
    db.commit()
    # La sesion en curso tambien genera ya en el nuevo idioma.
    db.info["language"] = language
    return {
        "language": language,
        "supported": list(SUPPORTED_LANGUAGES),
        "generation_enabled": language_enabled(),
    }
