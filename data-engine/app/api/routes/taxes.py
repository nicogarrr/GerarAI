"""Fiscal-year tax reports (IRPF-style) for the private portfolio."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import tax_declarant_service
from app.services.tax_modelo720_file import Modelo720FileService
from app.services.tax_modelo720_service import Modelo720Service
from app.services.tax_report_service import TaxReportService, build_tax_summary_rows

router = APIRouter()


@router.get("/report/{fiscal_year}")
def tax_report(
    fiscal_year: int,
    db: Session = Depends(get_db),
) -> dict:
    """Informe fiscal de un ejercicio. Solo lectura.

    Antes aceptaba `?regenerate=true`, que ademas de persistir un TaxReport
    (una escritura) hacia que un GET tuviera efectos de estado: no idempotente,
    imposible de cachear y capaz de devolver 500 en un camino de lectura. El
    calculo forzado vive en POST /report/{fiscal_year}/regenerate, que ya
    existe; este handler usa `get_report`, que devuelve el informe persistido
    o lo calcula EN MEMORIA sin escribir (`persisted=False`).
    """
    _validate_year(fiscal_year)
    try:
        return TaxReportService().get_report(db, fiscal_year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_year(fiscal_year: int) -> None:
    if fiscal_year < 2000 or fiscal_year > 2200:
        raise HTTPException(
            status_code=400, detail="fiscal_year must be between 2000 and 2200"
        )


@router.get("/holdings")
def tax_holdings(db: Session = Depends(get_db)) -> list[dict]:
    return build_tax_summary_rows(db)


@router.post("/report/{fiscal_year}/regenerate")
def regenerate_tax_report(fiscal_year: int, db: Session = Depends(get_db)) -> dict:
    _validate_year(fiscal_year)
    try:
        return TaxReportService().regenerate_report(db, fiscal_year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/modelo720/{fiscal_year}/thresholds")
def modelo720_thresholds(fiscal_year: int, db: Session = Depends(get_db)) -> dict:
    """Chequeo de umbrales del Modelo 720 (50.000 EUR por categoria).

    Solo lectura. Chequeo orientativo con estados sin-datos honestos; no es
    la declaracion ni prueba la obligacion por si solo.
    """
    _validate_year(fiscal_year)
    return Modelo720Service().check_thresholds(db, fiscal_year)


@router.get("/modelo720/{fiscal_year}/file")
def modelo720_file(fiscal_year: int, db: Session = Depends(get_db)) -> dict:
    """Fichero del Modelo 720 (500 bytes/registro, spec oficial AEAT).

    Solo lectura. Requiere los datos del declarante en la metadata del
    tenant (clave 'tax_declarant'); sin ellos devuelve available=false con
    el motivo. AYUDA DE CÓMPUTO: revisar antes de presentar por TGVI Online.
    """
    _validate_year(fiscal_year)
    return Modelo720FileService().generate(db, fiscal_year)


class FilingPreviewInput(BaseModel):
    # TME copiado del borrador del usuario, en porcentaje (19,00 -> 0,19).
    # No se persiste ni se aplica a otro ejercicio/tenant.
    tme_percent: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


@router.post("/report/{fiscal_year}/preview")
def preview_tax_filing(
    fiscal_year: int,
    inputs: FilingPreviewInput,
    db: Session = Depends(get_db),
) -> dict:
    """Vista previa IRPF con TME manual. Solo cálculo, sin guardar datos."""
    _validate_year(fiscal_year)
    try:
        return TaxReportService().get_report(
            db, fiscal_year, tme=inputs.tme_percent / Decimal("100")
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class DeclarantInput(BaseModel):
    model_config = {"extra": "forbid"}

    # La validez de formato (DNI/NIE/CIF con dígito de control) se avisa en
    # cliente sin bloquear: puede ser un identificador fiscal extranjero.
    # Aquí solo se rechaza lo absurdo: longitud desmesurada o caracteres de
    # control, que nunca son un identificador y suelen ser pegado corrupto.
    nif: str | None = Field(default=None, max_length=32)
    apellidos_nombre: str | None = None
    numero_declaracion: str | None = None
    telefono: str | None = None
    filed_720_before: bool | None = None
    custody: dict[str, str | None] | None = None
    custody_entities: dict[str, dict[str, str | None] | None] | None = None
    first_acquisition_dates: dict[str, str | None] | None = None

    @field_validator("nif")
    @classmethod
    def _nif_sin_caracteres_de_control(cls, value: str | None) -> str | None:
        if value is not None and any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("El NIF contiene caracteres de control no imprimibles.")
        return value


@router.get("/declarant")
def get_declarant(db: Session = Depends(get_db)) -> dict:
    try:
        return tax_declarant_service.read(db)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("/declarant")
def put_declarant(body: DeclarantInput, db: Session = Depends(get_db)) -> dict:
    try:
        return tax_declarant_service.write(db, body.model_dump(exclude_unset=True))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
