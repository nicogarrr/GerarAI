"""La variacion % de una sesion no se calcula a traves de sesiones que faltan.

``price_change_percent`` comparaba los dos ultimos cierres guardados sin mirar
las fechas: si faltaba el martes, lunes -> miercoles (+10 % en dos sesiones)
salia como variacion diaria y disparaba una regla «> 5 %». Valores esperados
calculados a mano (100 -> 110 = +10 %).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, ResearchAlert
from app.services import alert_rule_service as ars
from app.services.alert_rule_service import AlertRuleService
from app.services.trading_sessions import missing_sessions, weekdays_between


@pytest.fixture
def db(monkeypatch):
    # Fechas fijas de calendario: la frescura no es lo que se prueba aqui.
    monkeypatch.setattr(ars, "close_is_stale", lambda *_a, **_k: False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, exchange: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _closes(db: Session, company: Company, closes: dict[date, str]) -> None:
    for day, close in closes.items():
        db.add(MarketPrice(
            company_id=company.id, date=day, open=Decimal(close), high=Decimal(close),
            low=Decimal(close), close=Decimal(close), adj_close=Decimal(close), source="yfinance",
        ))
    db.commit()


MON, TUE, WED = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)


def _rise_rule(db: Session, company: Company):
    service = AlertRuleService()
    return service, service.create(db, company, rule_type="price_change", operator=">", value=5)


def test_missing_session_is_not_a_one_day_move(db):
    company = _company(db, "GAP", "NASDAQ")
    _closes(db, company, {MON: "100", WED: "110"})  # falta el martes
    service, rule = _rise_rule(db, company)

    result = service.evaluate(db, rule)

    assert result["status"] == "skipped_session_gap"
    assert result["matched"] is False
    assert result["observed"] is None
    assert result["observation"]["missing_sessions"] == ["2026-10-20"]
    assert db.query(ResearchAlert).count() == 0


def test_peer_close_proves_the_session_existed(db):
    company = _company(db, "GAP", "NASDAQ")
    peer = _company(db, "PEER", "NYSE")  # mismo calendario de EE. UU.
    _closes(db, peer, {MON: "50", TUE: "51", WED: "52"})
    _closes(db, company, {MON: "100", WED: "110"})
    service, rule = _rise_rule(db, company)

    result = service.evaluate(db, rule)

    assert result["status"] == "skipped_session_gap"
    assert result["observation"]["missing_sessions"] == ["2026-10-20"]


def test_exchange_holiday_is_consecutive_sessions(db):
    # Semana Santa 2026 en Londres: cerrado Viernes Santo (3 abr) y Lunes de
    # Pascua (6 abr). Jueves 2 -> martes 7 son dos sesiones consecutivas.
    thu, tue = date(2026, 4, 2), date(2026, 4, 7)
    company = _company(db, "HOL", "LSE")
    peer = _company(db, "PEER", "LSE")
    _closes(db, peer, {thu: "10", tue: "10.2"})
    _closes(db, company, {thu: "100", tue: "110"})
    service, rule = _rise_rule(db, company)

    result = service.evaluate(db, rule)

    assert result["status"] == "triggered"
    assert Decimal(result["observed"]) == Decimal("10")


def test_weekend_is_not_a_gap(db):
    fri, mon = date(2026, 10, 16), MON
    company = _company(db, "WKD", "NASDAQ")
    _closes(db, company, {fri: "100", mon: "110"})
    service, rule = _rise_rule(db, company)

    result = service.evaluate(db, rule)

    assert result["status"] == "triggered"
    assert Decimal(result["observed"]) == Decimal("10")


def test_long_market_wide_hole_is_a_gap_not_a_holiday(db):
    # Ningun valor de la bolsa tiene cierres de martes a viernes: 4 dias
    # laborables sin datos es un hueco de carga, no un festivo.
    nxt_mon = date(2026, 10, 26)
    company = _company(db, "GAP", "BME")
    peer = _company(db, "PEER", "BME")
    _closes(db, peer, {MON: "10", nxt_mon: "11"})
    _closes(db, company, {MON: "100", nxt_mon: "110"})
    service, rule = _rise_rule(db, company)

    result = service.evaluate(db, rule)

    assert result["status"] == "skipped_session_gap"
    assert len(result["observation"]["missing_sessions"]) == 4


def test_weekdays_between_and_no_exchange(db):
    assert weekdays_between(date(2026, 10, 16), MON) == []
    assert weekdays_between(MON, WED) == [TUE]
    company = _company(db, "NOEX", "")
    assert missing_sessions(db, company, MON, WED) == [TUE]
