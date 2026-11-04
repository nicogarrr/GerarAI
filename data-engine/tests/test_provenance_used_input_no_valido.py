"""Inputs INFERIDO consumidos que hoy no pasan la validación: se declaran.

La re-validación contra las reglas actuales (ALLOWED_KEYS, rangos) antes
omitía en silencio el input del registro: la tesis parecía no haber consumido
nada. Ahora se conserva marcado «consumido (hoy no válido)» (payload
`validez` + etiqueta visible en el memo).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.thesis_service import latest_inputs_provenance


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Telecom", industry="Satellites", company_type="growth",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


BASE = "Objetivo de margen declarado por el equipo en carta a accionistas"
URLS = ["https://example.com/carta"]


def _basis(value):
    return {
        "inferred_inputs_used": [
            {
                "inferred_input_id": 42,
                "input_key": "fcf_margin",
                "value": value,
                "base_inferencia": BASE,
                "urls_inferencia": URLS,
            }
        ]
    }


def test_consumido_hoy_no_valido_se_conserva_marcado(db):
    """Valor fuera del rango actual: antes desaparecía; ahora queda marcado."""
    company = _company(db)
    items = latest_inputs_provenance(db, company.id, _basis(0.99))
    assert [i["key"] for i in items] == ["fcf_margin_usado_en_valoracion"]
    item = items[0]
    assert item["validez"] == "consumido_hoy_no_valido"
    # El historico se conserva completo: valor, base y URLs de cuando se uso.
    assert item["value"] == 0.99
    assert item["base_inferencia"] == BASE and item["urls_inferencia"] == URLS
    assert item["origen"] == "INFERIDO" and item["inferred_input_id"] == 42


def test_consumido_vigente_se_conserva_como_vigente(db):
    company = _company(db)
    items = latest_inputs_provenance(db, company.id, _basis(0.25))
    assert [i["key"] for i in items] == ["fcf_margin_usado_en_valoracion"]
    assert items[0]["validez"] == "vigente"


def test_memo_etiqueta_consumido_hoy_no_valido():
    """La tabla de procedencia del memo lo hace visible al usuario."""
    from app.services.thesis_service import ThesisService

    items = [
        {
            "key": "fcf_margin_usado_en_valoracion", "label": "estimacion_llm",
            "value": 0.99, "unit": "decimal", "method": BASE,
            "source_fact_ids": [], "validez": "consumido_hoy_no_valido",
        }
    ]
    md = ThesisService._provenance_markdown(items)
    assert "estimacion_llm (consumido, hoy no válido)" in md


def test_memo_sin_marca_cuando_vigente():
    from app.services.thesis_service import ThesisService

    items = [
        {
            "key": "fcf_margin_usado_en_valoracion", "label": "estimacion_llm",
            "value": 0.25, "unit": "decimal", "method": BASE,
            "source_fact_ids": [], "validez": "vigente",
        }
    ]
    md = ThesisService._provenance_markdown(items)
    assert "consumido, hoy no válido" not in md
