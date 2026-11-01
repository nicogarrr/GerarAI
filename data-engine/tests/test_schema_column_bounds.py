"""Cotas de schema = ancho de columna en las escrituras de routes/memory.py.

SQLite traga strings de cualquier largo en una String(N), pero Postgres rompe
con DataError: el handler global lo convierte en 422 generico ("value out of
range") DESPUES de llegar a la BD. La cota en el schema rechaza en el borde
con un 422 por campo, antes de tocar la BD, y hace que el contrato sea el
mismo en dev/test (SQLite) y en prod (Postgres).

Campos acotados (ancho de la columna entre parentesis):
* ClaimCreate.claim_type (80), .status (40), .source_quality (40), .created_by (80)
* ClaimEvidenceCreate.source_url (1000)  [source_tier NO: el backend lo pisa
  con classify_source, nunca se persiste el del payload]
* ThesisChangeCreate.change_type (80)
* ThesisSectionCreate.status (40)

Los enums cerrados por la ruta (MemoryItem, ResearchSession.status) ya no
pueden traer valores largos; statement/summary/body/quote/content son Text.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.api import (
    ClaimCreate,
    ClaimEvidenceCreate,
    ThesisChangeCreate,
    ThesisSectionCreate,
)


def _claim_base() -> dict:
    return {"statement": "claim de prueba con suficiente largo"}


@pytest.mark.parametrize(
    ("field", "width"),
    [("claim_type", 80), ("status", 40), ("source_quality", 40), ("created_by", 80)],
)
def test_claim_create_cota_columna(field: str, width: int):
    ClaimCreate(**_claim_base(), **{field: "x" * width})  # justo en el ancho: vale
    with pytest.raises(ValidationError):
        ClaimCreate(**_claim_base(), **{field: "x" * (width + 1)})


def test_claim_evidence_source_url_cota_1000():
    ClaimEvidenceCreate(summary="evidencia valida", source_url="https://e.co/" + "a" * 987)
    with pytest.raises(ValidationError):
        ClaimEvidenceCreate(summary="evidencia valida", source_url="https://e.co/" + "a" * 988)


def test_thesis_change_type_cota_80():
    ThesisChangeCreate(change_type="x" * 80, summary="cambio de tesis valido")
    with pytest.raises(ValidationError):
        ThesisChangeCreate(change_type="x" * 81, summary="cambio de tesis valido")


def test_thesis_section_status_cota_40():
    ThesisSectionCreate(section_key="k", title="t", status="x" * 40)
    with pytest.raises(ValidationError):
        ThesisSectionCreate(section_key="k", title="t", status="x" * 41)
