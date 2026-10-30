"""Criterios de tesis en % tras un split posterior a la tesis.

La tesis guarda su precio y su valor esperado por accion en la base de su
fecha. Tras un split 10:1 el cierre nuevo esta en la base nueva: comparar
105 con un precio de tesis de 1000 daba «-89,5 % desde la tesis» y disparaba
el criterio de invalidacion; el margen salia 93 % en vez de 30 %.

Derivado a mano (split 10:1 el 1-jun-2026, tesis del 10-ene-2026):
  precio de tesis 1000 -> 100 en la base nueva; valor esperado 1500 -> 150.
  variacion desde tesis = 105 / 100 - 1 = +5 %.
  margen (V - P) / V = (150 - 105) / 150 = 30 %.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AlertRule
from app.models.entities import Base, Company, CorporateAction, MarketPrice, ThesisVersion
from app.services.thesis_invalidation_rules import RULE_TYPE, observe

TODAY = date.today()
SPLIT_DAY = TODAY - timedelta(days=60)
THESIS_AT = datetime.combine(TODAY - timedelta(days=200), datetime.min.time(), tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _setup(db: Session, *, split_day: date = SPLIT_DAY, close_day: date = TODAY, close: str = "105"):
    company = Company(
        ticker="SPLT", name="SPLT", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Software", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(CorporateAction(company_id=company.id, action_type="split", effective_date=split_day, ratio=Decimal("10")))
    value = Decimal(close)
    db.add(MarketPrice(company_id=company.id, date=close_day, open=value, high=value, low=value,
                       close=value, adj_close=value, source="test"))
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="final", thesis_markdown="# Tesis",
        executive_summary="Resumen", rating="watch", current_price=Decimal("1000"),
        expected_value=Decimal("1500"), invalidation_criteria=[], invalidation_rules=None,
    )
    thesis.created_at = THESIS_AT
    db.add(thesis)
    db.commit()
    return company, thesis


def _observe(db, company, thesis, metric):
    rule = AlertRule(company_id=company.id, name="criterio", rule_type=RULE_TYPE,
                     target={"metric": metric, "thesis_version_id": thesis.id})
    return observe(db, rule)


def test_change_since_thesis_uses_the_post_split_basis(db):
    company, thesis = _setup(db)
    value, info = _observe(db, company, thesis, "variacion_desde_tesis_pct")
    assert value is not None
    assert value == pytest.approx(Decimal("5"))
    assert Decimal(info["reference"]) == Decimal("100")


def test_margin_of_safety_uses_the_post_split_basis(db):
    company, thesis = _setup(db)
    value, _info = _observe(db, company, thesis, "margen_seguridad_pct")
    assert value is not None
    assert value == pytest.approx(Decimal("30"))


def test_split_after_the_last_close_is_not_compared(db):
    # El ultimo cierre es anterior al split ya efectivo: base desconocida, N/D.
    company, thesis = _setup(db, split_day=TODAY - timedelta(days=1), close_day=TODAY - timedelta(days=3))
    value, info = _observe(db, company, thesis, "variacion_desde_tesis_pct")
    assert value is None
    assert info["missing"] == "precio_anterior_a_split"


def test_split_before_the_thesis_changes_nothing(db):
    company, thesis = _setup(db, split_day=THESIS_AT.date() - timedelta(days=30), close="1050")
    value, _info = _observe(db, company, thesis, "variacion_desde_tesis_pct")
    assert value == pytest.approx(Decimal("5"))
