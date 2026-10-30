"""Autoservicio de privacidad: export completo y borrado de la cuenta."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.privacy_service import (
    PrivacyConfirmationError,
    PrivacyPartialFailure,
    PrivacyService,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class DeleteAccountRequest(BaseModel):
    model_config = {"extra": "forbid"}

    # Frase literal exigida por el backend. La UI pide ademas el email de la
    # sesion y lo valida en el servidor de Next antes de llegar aqui.
    confirmation: str = Field(min_length=1, max_length=80)


class PrivacyExportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int
    generated_at: str
    profile: dict[str, Any]
    settings: dict[str, Any]


class DeleteAccountResponse(BaseModel):
    status: Literal["deleted"]
    already_deleted: bool
    tables: dict[str, int] = Field(default_factory=dict)
    external_objects_removed: int = 0
    knowledge_vector_collections_cleared: int = 0
    llm_cache_entries_purged: int = 0


class PrivacyErrorResponse(BaseModel):
    detail: str


@router.get(
    "/export",
    response_model=PrivacyExportResponse,
    responses={
        502: {"model": PrivacyErrorResponse, "description": "Exportación no disponible"},
    },
)
def export_account(db: Session = Depends(get_db)) -> dict:
    """JSON completo del tenant firmado: perfil, cartera, tesis, alertas,
    conocimiento, paper trading y telemetría del tenant. No incluye secretos
    ni identificadores de otros tenants."""
    try:
        return PrivacyService().export_account(db)
    except Exception as exc:  # noqa: BLE001 - no filtrar internos al cliente
        logger.error("account export failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=ui_error(502, "export_failed").detail,
        ) from exc


@router.delete(
    "/account",
    response_model=DeleteAccountResponse,
    responses={
        400: {"model": PrivacyErrorResponse, "description": "Confirmación no válida"},
        502: {
            "model": PrivacyErrorResponse,
            "description": "Borrado incompleto o no confirmado",
        },
    },
)
def delete_account(
    payload: DeleteAccountRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Borra todos los datos del tenant firmado.

    El 200 solo se devuelve despues de limpiar Postgres y el almacen/indice
    externo. Un fallo externo devuelve 502 y no elimina filas: se puede
    reintentar. La fila del tenant queda como tombstone ``deleted``.
    """
    try:
        return PrivacyService().delete_account(
            db, confirmation=payload.confirmation
        )
    except PrivacyConfirmationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PrivacyPartialFailure as exc:
        logger.error(
            "account deletion left external residue failures=%s", exc.failures
        )
        raise HTTPException(
            status_code=502,
            detail=ui_error(502, "deletion_residue").detail,
        ) from exc
    except ValueError:
        logger.warning("account deletion rejected")
        raise HTTPException(
            status_code=400,
            detail=ui_error(502, "deletion_request_failed").detail,
        ) from None
    except Exception as exc:  # noqa: BLE001 - no filtrar internos al cliente
        logger.error("account deletion failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=ui_error(502, "deletion_failed").detail,
        ) from exc
