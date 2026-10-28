"""Auditor de cobertura de cierres: reparto cerrado y causa verificable de cada hueco."""

import importlib.util
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice

_SPEC = importlib.util.spec_from_file_location(
    "audit_close_coverage", Path(__file__).resolve().parents[1] / "scripts" / "audit_close_coverage.py"
)
audit_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_mod)

S = date(2026, 10, 27)  # martes
PREV = date(2026, 10, 26)  # lunes


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker, exchange="NASDAQ", currency="USD"):
    row = Company(ticker=ticker, name=ticker, exchange=exchange, currency=currency, company_type="operating", valuation_model="unassigned")
    db.add(row)
    db.flush()
    return row


def _bar(db, company, day, unit="USD", source="yfinance"):
    db.add(MarketPrice(company_id=company.id, date=day, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(10), source=source, quote_currency=unit))


def _world(db):
    """US: 4 con cierre (una sin unidad declarada) + rezagada + nunca + abandonada.
    BME: 4 con S-1 y ninguna con S (festivo). Londres: 1 con unidad no verificable.
    Fuera de universo: bolsa sin sufijo, divisa sin bolsa, ticker vacio."""
    us_ok = [_company(db, f"US{i}") for i in range(4)]
    for i, c in enumerate(us_ok):
        _bar(db, c, S, unit=None if i == 0 else "USD")
        _bar(db, c, PREV)
    lagging = _company(db, "LAG")
    _bar(db, lagging, PREV)  # solo le falta S
    never = _company(db, "NEVER")
    gone = _company(db, "GONE")
    _bar(db, gone, S - timedelta(days=21))
    spot = _company(db, "SPOT")
    _bar(db, spot, S, source="finnhub")  # un spot NO es cierre oficial
    for i in range(4):
        _bar(db, _company(db, f"ES{i}", exchange="BME", currency="EUR"), PREV, unit="EUR")
    _company(db, "SHEL", exchange="LONDON STOCK EXCHANGE", currency="USD")
    _company(db, "ODD", exchange="BOLSA DE NARNIA", currency="EUR")
    _company(db, "NOEXCH", exchange="", currency="EUR")
    _company(db, "", exchange="NASDAQ", currency="USD")
    db.commit()


def _by_ticker(report):
    return {row["ticker"]: row for row in report["detail"]}


def test_partition_closes_and_every_company_has_one_category(db):
    _world(db)
    report = audit_mod.audit(db, session_day=S)
    assert report["total"] == db.scalar(select(func.count(Company.id)))
    cats = report["categories"]
    assert report["covered"] + report["missing"] + report["out_of_universe"] == report["total"]
    assert sum(sum(v.values()) for v in cats.values()) == report["total"]
    assert report["eligible"] == report["total"] - report["out_of_universe"]
    assert report["covered"] == 4
    assert report["coverage_pct_of_eligible"] == round(100 * 4 / report["eligible"], 2)


def test_out_of_universe_is_labelled_not_counted_as_missing(db):
    _world(db)
    d = _by_ticker(audit_mod.audit(db, session_day=S))
    assert d["ODD"]["category"] == "fuera_de_universo" and d["ODD"]["cause"] == "bolsa_sin_sufijo_mapeado"
    assert d["NOEXCH"]["cause"] == "divisa_no_usd_sin_bolsa"
    assert d[""]["cause"] == "sin_ticker"


def test_holiday_is_inferred_from_exchange_peers_not_a_calendar(db):
    _world(db)
    report = audit_mod.audit(db, session_day=S)
    d = _by_ticker(report)
    for i in range(4):
        row = d[f"ES{i}"]
        assert row["cause"] == "sesion_sin_barras_en_su_bolsa"
        assert row["evidence"]["inferred_from_peers"] is True and row["evidence"]["venue"] == ".MC"
    # La misma ausencia en una bolsa con cierres NO se llama festivo.
    assert d["LAG"]["cause"] == "rezagada" and d["LAG"]["evidence"]["sessions_behind"] == 1


def test_never_ingested_delisted_and_spot_are_distinguished(db):
    _world(db)
    d = _by_ticker(audit_mod.audit(db, session_day=S))
    assert d["NEVER"]["cause"] == "nunca_ingerida"
    assert d["GONE"]["cause"] == "sin_barras_desde" and d["GONE"]["evidence"]["last_close"] == (S - timedelta(days=21)).isoformat()
    assert d["SPOT"]["cause"] == "nunca_ingerida"  # barra spot no cuenta como cierre oficial


def test_unit_the_actor_would_drop_is_reported(db):
    _world(db)
    d = _by_ticker(audit_mod.audit(db, session_day=S))
    assert d["SHEL"]["cause"] == "unidad_no_verificable"


def test_covered_without_declared_unit_is_flagged(db):
    _world(db)
    report = audit_mod.audit(db, session_day=S)
    assert report["categories"]["cubierta"] == {"con_cierre": 3, "con_cierre_sin_unidad_declarada": 1}


def test_default_session_is_last_common_session_and_empty_db_is_honest(db):
    assert audit_mod.audit(db)["session"] is None
    _world(db)
    assert audit_mod.audit(db)["session"] in {S.isoformat(), PREV.isoformat()}


def test_reconcile_explains_the_change_by_identity(db):
    _world(db)
    before = audit_mod.audit(db, session_day=S)
    new = _company(db, "NEWCO")
    _bar(db, new, S)
    db.commit()
    after = audit_mod.audit(db, session_day=S)
    rec = audit_mod.reconcile(after, before)
    assert rec["universe"]["entered"] == [new.id] and rec["universe"]["left"] == []
    assert rec["covered"]["gained"] == [new.id] and rec["covered"]["lost"] == []
    assert rec["universe"]["closes"] and rec["covered"]["closes"]
    assert rec["covered"]["current"] == rec["covered"]["previous"] + 1


def test_audit_is_read_only(db):
    _world(db)
    before = db.scalar(select(func.count(MarketPrice.id)))
    audit_mod.audit(db, session_day=S)
    assert not db.new and not db.dirty and db.scalar(select(func.count(MarketPrice.id))) == before
