"""Dos criterios de invalidación cuyo umbral se ve igual (8 decimales como mucho).

«precio < 0,075» y «precio < 0,0750000001» (o «1e-9» y «2e-9», que se ven
«0,00») pasaban la validación como criterios distintos, pero la regla de aviso
se nombra con el texto que se ve: los dos daban el mismo nombre y guardar
fallaba con un 500 (uq_alert_rule_name). Se tratan como el mismo criterio,
igual que los repetidos exactos: se queda el primero."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import AlertRule, Base, Company, ThesisVersion
from app.services.thesis_invalidation_rules import (
    RULE_TYPE,
    describe_rule,
    normalize_rules,
    sync_thesis_rules,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db):
    company = Company(
        ticker="ACME", name="ACME", exchange="NASDAQ", currency="USD", sector="S", industry="I",
        company_type="holding", valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


@pytest.mark.parametrize(
    ("first", "second"),
    [("0.075", "0.0750000001"), ("100", "100.000000001"), ("1e-9", "2e-9")],
)
def test_umbrales_que_se_ven_iguales_son_un_solo_criterio(first, second):
    rules = normalize_rules([
        {"metric": "precio", "operator": "<", "threshold": first},
        {"metric": "precio", "operator": "<", "threshold": second},
    ])
    assert len(rules) == 1
    assert rules[0]["threshold"] == float(Decimal(first))


def test_guardar_dos_umbrales_que_se_ven_iguales_no_rompe(db):
    company = _company(db)
    rules = normalize_rules([
        {"metric": "precio", "operator": "<", "threshold": "0.075"},
        {"metric": "precio", "operator": "<", "threshold": "0.0750000001"},
        {"metric": "precio", "operator": "<", "threshold": "0.08"},
    ])
    db.add(ThesisVersion(
        company_id=company.id, version=1, status="final", thesis_markdown="# Tesis",
        executive_summary="Resumen", rating="watch", current_price=Decimal("10"),
        expected_value=Decimal("12"), invalidation_criteria=[], invalidation_rules=rules,
    ))
    db.flush()
    active = sync_thesis_rules(db, company)
    assert len(active) == 2
    stored = db.scalars(select(AlertRule).where(AlertRule.rule_type == RULE_TYPE)).all()
    assert sorted(r.condition["value"] for r in stored if r.active) == [0.075, 0.08]


def test_criterios_distintos_siguen_siendo_distintos():
    rules = normalize_rules([
        {"metric": "precio", "operator": "<", "threshold": "0.075"},
        {"metric": "precio", "operator": "<=", "threshold": "0.075"},
        {"metric": "margen_seguridad_pct", "operator": "<", "threshold": "0.075"},
        {"metric": "precio", "operator": "<", "threshold": "0.07500001"},
    ])
    assert len({describe_rule(rule) for rule in rules}) == 4
