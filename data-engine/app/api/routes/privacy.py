"""Autoservicio de privacidad: export completo y borrado de la cuenta."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.privacy_service import DELETE_CONFIRMATION, PrivacyService

logger = logging.getLogger(__name__)

router = APIRouter()


class DeleteAccountRequest(BaseModel):
    model_config = {"extra": "forbid"}

    # Frase literal exigida por el backend. La UI pide ademas el email de la
    # sesion y lo valida en el servidor de Next antes de llegar aqui.
    confirmation: str = Field(min_length=1, max_length=80)


@router.get("/export")
def export_account(db: Session = Depends(get_db)) -> dict:
    """JSON completo del tenant firmado: perfil, cartera, tesis, alertas y
    conocimiento. No incluye secretos ni identificadores de otros tenants."""
    return PrivacyService().export_account(db)


@router.delete("/account")
def delete_account(
    payload: DeleteAccountRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Borra todos los datos del tenant firmado.

    El 200 solo se devuelve despues de limpiar Postgres y el almacen/indice
    externo. Un fallo externo devuelve 502 y no elimina filas: se puede
    reintentar.
    """
    if payload.confirmation.strip().upper() != DELETE_CONFIRMATION:
        raise HTTPException(status_code=400, detail="Confirmation does not match")
    try:
        return PrivacyService().delete_account(
            db, confirmation=payload.confirmation
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - no filtrar internos al cliente
        logger.error("account deletion failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Account deletion could not complete; no partial success was reported",
        ) from exc
