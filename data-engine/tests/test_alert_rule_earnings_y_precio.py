"""Reglas de alerta «earnings», «price_above» y «price_below» de punta a punta.

Las reglas de cambio de precio y de noticias tienen sus propios ficheros. Aquí
se fija el contrato de los otros tipos que la API deja crear:
- «earnings» avisa una vez por cada resultado (EarningsRun) nuevo de SU empresa
  y nunca por uno anterior a la regla;
- «price_above»/«price_below» respetan el límite exacto de >= y <= con el
  último cierre fresco y no avisan dos veces dentro del cooldown.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, EarningsRun, MarketPrice, ResearchAlert
from app.services.alert_rule_service import AlertRuleService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
            yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _run(db: Session, company: Company, *, created_at: datetime, quarter: str = "Q3") -> EarningsRun:
    run = EarningsRun(company_id=company.id, fiscal_year=2026, fiscal_quarter=quarter,
                      status="completed", created_at=created_at)
    db.add(run)
    db.commit()
    return run


def _price(db: Session, company: Company, close: str) -> None:
    value = Decimal(close)
    db.add(MarketPrice(company_id=company.id, date=date.today(), open=value, high=value,
                       low=value, close=value, adj_close=value, source="Finnhub"))
    db.commit()


def _alerts(db: Session, alert_type: str) -> list[ResearchAlert]:
    return list(db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == alert_type)))


def _rule(db: Session, company: Company, rule_type: str, operator: str = ">", value: float = 0,
          cooldown_seconds: int = 0):
    rule = AlertRuleService().create(db, company, rule_type=rule_type, operator=operator,
                                     value=value, cooldown_seconds=cooldown_seconds)
    # La regla se creó hace una hora: los eventos posteriores a esa hora son nuevos.
    rule.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    return rule


def test_earnings_se_normaliza_a_existencia_y_apunta_a_los_resultados(db):
    company = _company(db)
    rule = AlertRuleService().create(db, company, rule_type="earnings", operator="<", value=99)

    assert rule.condition == {"operator": ">", "value": 0}
    assert rule.target == {"kind": "earnings_run"}


def test_earnings_anterior_a_la_regla_no_avisa(db):
    company = _company(db)
    _run(db, company, created_at=datetime.now(UTC) - timedelta(days=30))
    rule = _rule(db, company, "earnings")

    result = AlertRuleService().evaluate(db, rule)

    assert result["matched"] is False
    assert _alerts(db, "earnings") == []


def test_earnings_nuevo_avisa_una_sola_vez(db):
    company = _company(db)
    rule = _rule(db, company, "earnings")
    run = _run(db, company, created_at=datetime.now(UTC) - timedelta(minutes=5))
    service = AlertRuleService()

    first = service.evaluate(db, rule)
    second = service.evaluate(db, rule)

    assert first["status"] == "triggered"
    assert first["observation"]["earnings_run_id"] == run.id
    assert second["matched"] is False
    alerts = _alerts(db, "earnings")
    assert len(alerts) == 1
    assert alerts[0].company_id == company.id


def test_earnings_de_otra_empresa_no_avisa(db):
    mine = _company(db, "AAPL")
    other = _company(db, "MSFT")
    rule = _rule(db, mine, "earnings")
    _run(db, other, created_at=datetime.now(UTC) - timedelta(minutes=5))

    result = AlertRuleService().evaluate(db, rule)

    assert result["matched"] is False
    assert _alerts(db, "earnings") == []


def test_dos_resultados_nuevos_entre_pasadas_dan_dos_avisos(db):
    company = _company(db)
    rule = _rule(db, company, "earnings")
    service = AlertRuleService()
    _run(db, company, created_at=datetime.now(UTC) - timedelta(minutes=5), quarter="Q2")
    assert service.evaluate(db, rule)["status"] == "triggered"

    _run(db, company, created_at=datetime.now(UTC) + timedelta(seconds=1), quarter="Q3")
    assert service.evaluate(db, rule)["status"] == "triggered"

    assert len(_alerts(db, "earnings")) == 2


@pytest.mark.parametrize(
    ("rule_type", "operator", "threshold", "close", "fires"),
    [
        ("price_above", ">=", 150, "150", True),
        ("price_above", ">", 150, "150", False),
        ("price_above", ">", 150, "150.01", True),
        ("price_below", "<=", 150, "150", True),
        ("price_below", "<", 150, "150", False),
        ("price_below", "<", 150, "149.99", True),
    ],
)
def test_precio_respeta_el_limite_exacto(db, rule_type, operator, threshold, close, fires):
    company = _company(db)
    _price(db, company, close)
    rule = _rule(db, company, rule_type, operator, threshold)

    result = AlertRuleService().evaluate(db, rule)

    assert result["matched"] is fires
    assert result["status"] == ("triggered" if fires else "evaluated")
    assert len(_alerts(db, rule_type)) == (1 if fires else 0)


def test_precio_no_repite_aviso_dentro_del_cooldown(db):
    company = _company(db)
    _price(db, company, "90")
    rule = _rule(db, company, "price_below", "<", 100, cooldown_seconds=3600)
    service = AlertRuleService()

    first = service.evaluate(db, rule)
    second = service.evaluate(db, rule)

    assert first["status"] == "triggered"
    assert second["matched"] is True
    assert second["cooldown_active"] is True
    assert len(_alerts(db, "price_below")) == 1
