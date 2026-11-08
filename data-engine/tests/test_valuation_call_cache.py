"""Caché de lecturas acotada a una llamada de valoración (perf 4-nov-2026).

Medido antes del cambio: una ``value_company`` con cross-check de comparables
emitía 242 SELECTs (202 a financial_facts: revenue x21, free_cash_flow x20...)
porque cada puente y el cross-check repetían las mismas lecturas. La caché
vive en ``db.info`` solo durante la llamada: equivalencia bit a bit, borrado
al salir (éxito o error) y clave con tenant.

Conteos deterministas (listener de eventos), nunca reloj: el reloj rompe CI
bajo coverage.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, event
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company, FinancialFact, FXRate, MarketPrice, Tenant
from app.models.entities import Base
from app.services.valuation_service import ValuationService
from app.valuation.call_cache import _CACHE_KEY, valuation_call_cache
from app.valuation.fact_reference import latest_facts, latest_facts_multi

FY = 2025
TODAY = date(2026, 11, 4)


def _fact(company_id: int, metric: str, value: float, *, year: int = FY,
          source: str = "SEC", tenant: int = 1, unit: str = "USD") -> dict:
    return dict(company_id=company_id, metric=metric, value=value, unit=unit,
                period="FY", fiscal_year=year, source_type=source,
                is_reported=True, tenant_id=tenant,
                filed=date(year + 1, 2, 15))


def _fundamentals(company_id: int, scale: float, *, tenant: int = 1) -> list[dict]:
    rows = []
    for year in (FY - 1, FY):
        rows += [
            _fact(company_id, "revenue", 10e9 * scale * (1.1 ** (year - FY + 1)), year=year, tenant=tenant),
            _fact(company_id, "free_cash_flow", 1e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "operating_cash_flow", 1.5e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "capital_expenditure", -5e8 * scale, year=year, tenant=tenant),
            _fact(company_id, "net_income", 8e8 * scale, year=year, tenant=tenant),
            _fact(company_id, "ebitda", 1.4e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "net_debt", 2e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "shares_diluted", 1e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "total_debt", 3e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "cash_and_equivalents", 1e9 * scale, year=year, tenant=tenant),
            _fact(company_id, "market_cap", 20e9 * scale, year=year, tenant=tenant),
        ]
    return rows


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1", name="one"))
        session.add(Tenant(id=2, external_id="t2", name="two"))
        target = Company(id=1, ticker="TRG", name="Target", exchange="NYSE", currency="USD",
                         sector="Technology", industry="Software", company_type="asset_light",
                         valuation_model="dcf_standard", factor_tags=["software"])
        peers = [
            Company(id=2, ticker="PR1", name="Peer1", exchange="NASDAQ", currency="USD",
                    sector="Technology", industry="Software", company_type="asset_light",
                    valuation_model="dcf_standard", factor_tags=["software"]),
            Company(id=3, ticker="PR2", name="Peer2", exchange="XETRA", currency="EUR",
                    sector="Technology", industry="Software", company_type="asset_light",
                    valuation_model="dcf_standard", factor_tags=["software"]),
        ]
        session.add_all([target, *peers])
        session.flush()
        session.execute(FinancialFact.__table__.insert(), _fundamentals(1, 1.0))
        session.execute(FinancialFact.__table__.insert(), _fundamentals(2, 0.8))
        session.execute(FinancialFact.__table__.insert(), _fundamentals(3, 1.2))
        for i, cid in enumerate((1, 2, 3)):
            session.add(MarketPrice(company_id=cid, date=TODAY - timedelta(days=1),
                                    open=90, high=91, low=89, close=90.5 + i,
                                    quote_currency="USD", source="yfinance"))
        session.add(FXRate(base_currency="USD", quote_currency="EUR", rate=0.92,
                           rate_date=TODAY - timedelta(days=1), source="ecb", tenant_id=1))
        # CAPM requires a traceable discount rate. This fixture tests caching,
        # not the fallback-rate publication blocker; keep its assert status=ok.
        session.add(CalculatedMetric(
            tenant_id=1, company_id=1, metric="wacc", value=0.09, unit="decimal",
            period=f"{FY}-12-31:FY", fiscal_year=FY, status="ok",
            definition_version="WACC_STANDARD_V1",
            formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
            created_at=datetime(2026, 11, 3, tzinfo=UTC),
        ))
        session.commit()
        session.info["tenant_id"] = 1
        yield session


def _canon(result: dict) -> str:
    return json.dumps(result, sort_keys=True, default=str)


def _count_facts_selects(engine_session: Session, fn) -> int:
    count = {"n": 0}

    def _listener(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "financial_facts" in statement:
            count["n"] += 1

    event.listen(engine_session.get_bind(), "before_cursor_execute", _listener)
    try:
        fn()
    finally:
        event.remove(engine_session.get_bind(), "before_cursor_execute", _listener)
    return count["n"]


def test_results_bit_identical_with_and_without_cache(db, monkeypatch):
    company = db.get(Company, 1)
    cached_result = ValuationService().value_company(db, company)
    assert _CACHE_KEY not in db.info  # siempre se borra al salir
    db.expire_all()
    monkeypatch.setattr(
        "app.services.valuation_service.valuation_call_cache", contextlib.nullcontext
    )
    uncached_result = ValuationService().value_company(db, company)
    assert _canon(cached_result) == _canon(uncached_result)
    assert cached_result["status"] == "ok"
    assert cached_result["trace"]["wacc_source"] == "calculated_metric"


def test_missing_traceable_wacc_stays_partial_with_cache(db):
    db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == 1))
    db.commit()
    result = ValuationService().value_company(db, db.get(Company, 1))
    assert result["status"] == "partial"
    assert result["publishable"] is False
    assert "traceable_wacc" in result["trace"]["publication_blockers"]
    assert _CACHE_KEY not in db.info


def test_query_count_drops_with_cache(db, monkeypatch):
    company = db.get(Company, 1)
    with_cache = _count_facts_selects(
        db, lambda: ValuationService().value_company(db, company)
    )
    db.expire_all()
    monkeypatch.setattr(
        "app.services.valuation_service.valuation_call_cache", contextlib.nullcontext
    )
    without_cache = _count_facts_selects(
        db, lambda: ValuationService().value_company(db, company)
    )
    # Medido en este fixture: 39 sin caché, 22 con ella (con 2 peers; con los
    # 8 del cross-check real la distancia crece: 202 -> 34). Umbrales holgados
    # para fijar la regresión sin atar el test a un conteo exacto.
    assert with_cache <= 26
    assert without_cache >= with_cache + 10


def test_cache_cleared_on_error(db, monkeypatch):
    def _boom(self, context):
        raise RuntimeError("engine explota a mitad")

    monkeypatch.setattr(
        "app.valuation.engines.standard_dcf.StandardDCFEngine.value", _boom, raising=False
    )
    with pytest.raises(Exception):
        ValuationService().value_company(db, db.get(Company, 1))
    assert _CACHE_KEY not in db.info


def test_no_cross_tenant_reads_within_shared_cache(db):
    db.execute(
        FinancialFact.__table__.insert(),
        [_fact(1, "revenue", 999e9, tenant=2)],
    )
    db.commit()
    with valuation_call_cache(db):
        db.info["tenant_id"] = 1
        one = latest_facts(db, 1, ["revenue"])["revenue"].value
        db.info["tenant_id"] = 2
        two = latest_facts(db, 1, ["revenue"])["revenue"].value
    assert one == 11e9  # FY2025 del fixture (10e9 x 1.1)
    assert two == 999e9


def test_latest_facts_multi_matches_latest_facts(db):
    aliases = ["revenue", "free_cash_flow", "ebitda", "book_value", "cash", "net_income"]
    multi = latest_facts_multi(db, 1, aliases)
    for alias in aliases:
        single = latest_facts(db, 1, [alias]).get(alias)
        assert (alias in multi) == (single is not None)
        if single is not None:
            assert multi[alias].value == single.value
            assert multi[alias].fact_id == single.fact_id


def test_call_sees_fresh_facts_after_previous_call(db):
    first = ValuationService().value_company(db, db.get(Company, 1))
    db.execute(
        FinancialFact.__table__.insert(),
        [_fact(1, "revenue", 50e9, year=FY + 1)],
    )
    db.commit()
    second = ValuationService().value_company(db, db.get(Company, 1))
    # La caché murió con la primera llamada: la segunda ve el hecho nuevo.
    assert _canon(first) != _canon(second)
