"""Criterio de invalidación con más de 2 decimales («ROIC < 0,075»).

El nombre de la regla de aviso, la etiqueta y el mensaje redondeaban el umbral a
2 decimales: «< 0,075» salía «< 0,08», y dos criterios distintos (0,075 y 0,08)
daban el mismo nombre, así que se sincronizaban en UNA sola regla de aviso y uno
de los dos no se vigilaba. Los umbrales de hasta 2 decimales no cambian (ni su
nombre ni su texto)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import AlertRule, Base, Company, ThesisVersion
from app.services.thesis_invalidation_rules import (
    RULE_TYPE,
    _describe_rule_en,
    alert_message,
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


def _rule(metric, operator, threshold):
    return normalize_rules([{"metric": metric, "operator": operator, "threshold": threshold}])[0]


def test_umbral_con_tres_decimales_se_muestra_entero():
    rule = _rule("metrica:roic", "<", "0,075")
    assert describe_rule(rule) == "roic < 0,075"
    assert _describe_rule_en(rule) == "roic < 0.075"
    alerta = SimpleNamespace(target={"metric": "metrica:roic"}, condition={"operator": "<", "value": 0.075})
    assert "roic < 0,075" in alert_message(SimpleNamespace(ticker="ACME"), alerta, 0.07)


@pytest.mark.parametrize(
    ("metric", "threshold", "es", "en"),
    [
        ("precio", "1234.5", "precio < 1.234,50", "price < 1,234.50"),
        ("precio", 20, "precio < 20,00", "price < 20.00"),
        ("margen_seguridad_pct", "10", "margen de seguridad < 10,00 %", "margin of safety < 10.00%"),
        ("metrica:roic", "0.08", "roic < 0,08", "roic < 0.08"),
        ("precio", 0.1 + 0.2, "precio < 0,30", "price < 0.30"),
    ],
)
def test_umbrales_de_hasta_dos_decimales_no_cambian(metric, threshold, es, en):
    rule = _rule(metric, "<", threshold)
    assert describe_rule(rule) == es
    assert _describe_rule_en(rule) == en


def test_dos_criterios_casi_iguales_son_dos_reglas_de_aviso(db):
    company = Company(
        ticker="ACME", name="ACME", exchange="NASDAQ", currency="USD", sector="S", industry="I",
        company_type="holding", valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    rules = normalize_rules([
        {"metric": "metrica:roic", "operator": "<", "threshold": "0.075"},
        {"metric": "metrica:roic", "operator": "<", "threshold": "0.08"},
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
