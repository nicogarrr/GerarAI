"""Comparables del motor relativo sin calcular métricas que nadie lee (perf r5, 11-nov-2026).

``relative_multiples._peer_set`` pedía ``PeerComparisonService.compare()``
solo para saber QUIÉNES son los comparables (tickers, base y traza), pero
``compare()`` calcula además las 23 métricas de cada comparable
(``calculate_all``): 36 % del tiempo de ``GET /api/valuation/{ticker}``.
Ahora pide la selección al selector (``_find_peers``): mismo grupo, misma
base, misma traza, cero cálculos de métricas. Conteos deterministas.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company, FinancialFact, MarketPrice, Tenant
from app.models.entities import Base
from app.services.metric_calculation_service import MetricCalculationService
from app.services.peer_comparison_service import PeerComparisonService
from app.services.valuation_service import ValuationService
from app.valuation.engines import relative_multiples

FY = 2025
TODAY = date(2026, 11, 11)


def _rows(company_id: int, scale: float) -> list[dict]:
    out = []
    for year in (FY - 1, FY):
        for metric, value in (("revenue", 10e9), ("free_cash_flow", 1e9), ("operating_cash_flow", 1.5e9),
                              ("capital_expenditure", -5e8), ("net_income", 8e8), ("ebitda", 1.4e9),
                              ("net_debt", 2e9), ("shares_diluted", 1e9), ("total_debt", 3e9),
                              ("cash_and_equivalents", 1e9), ("market_cap", 20e9), ("eps_diluted", 0.8),
                              ("total_equity", 6e9), ("gross_profit", 5e9), ("operating_income", 2e9)):
            out.append(dict(company_id=company_id, metric=metric, value=value * scale, unit="USD",
                            period="FY", fiscal_year=year, source_type="SEC", is_reported=True,
                            tenant_id=1, filed=date(year + 1, 2, 15)))
    return out


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1", name="one"))
        common = dict(exchange="NYSE", currency="USD", sector="Technology", industry="Software",
                      company_type="asset_light", valuation_model="dcf_standard", factor_tags=["software"])
        session.add_all([Company(id=1, ticker="TRG", name="Target", **common),
                         Company(id=2, ticker="PR1", name="Peer1", **common),
                         Company(id=3, ticker="PR2", name="Peer2", **common),
                         Company(id=4, ticker="PR3", name="Peer3", **common)])
        session.flush()
        for cid, scale in ((1, 1.0), (2, 0.8), (3, 1.2), (4, 0.9)):
            session.execute(FinancialFact.__table__.insert(), _rows(cid, scale))
            session.add(MarketPrice(company_id=cid, date=TODAY - timedelta(days=1), open=19, high=21, low=18,
                                    close=20 + cid, quote_currency="USD", source="yfinance"))
        session.add(CalculatedMetric(tenant_id=1, company_id=1, metric="wacc", value=0.09, unit="decimal",
                                     period=f"{FY}-12-31:FY", fiscal_year=FY, status="ok",
                                     definition_version="WACC_STANDARD_V1",
                                     formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
                                     created_at=datetime(2026, 11, 3, tzinfo=UTC)))
        session.commit()
        session.info["tenant_id"] = 1
        yield session


class _Ctx:
    def __init__(self, db, company):
        self.db = db
        self.company = company


def test_peer_set_matches_compare_selection(db):
    company = db.get(Company, 1)
    comparison = PeerComparisonService().compare(db, company, limit=relative_multiples.PEER_LIMIT, refresh=False)
    expected = sorted(row["ticker"] for row in comparison["companies"] if not row["is_target"])
    assert expected, "el fixture debe tener comparables"
    peers, meta = relative_multiples._peer_set(_Ctx(db, company))
    assert [peer.ticker for peer in peers] == expected
    assert meta["basis"] == comparison["basis"]
    assert meta["trace"] == comparison["selection_trace"]
    assert meta["method"] == (comparison["selection_trace"] or {}).get("method")
    assert meta["fallback_only"] is (comparison["basis"] != "manual_then_multifactor")


def test_peer_set_computes_no_peer_metrics(db, monkeypatch):
    calls = {"n": 0}
    original = MetricCalculationService.calculate_all

    def _counting(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MetricCalculationService, "calculate_all", _counting)
    peers, _meta = relative_multiples._peer_set(_Ctx(db, db.get(Company, 1)))
    assert peers
    # Antes: un calculate_all por participante (objetivo + comparables).
    assert calls["n"] == 0


def test_value_company_same_result_as_with_compare(db, monkeypatch):
    company = db.get(Company, 1)
    fast = ValuationService().value_company(db, company)
    db.expire_all()

    def _old_peer_set(context):
        comparison = PeerComparisonService().compare(context.db, context.company,
                                                     limit=relative_multiples.PEER_LIMIT, refresh=False)
        ids = {row["ticker"]: None for row in comparison.get("companies", []) if not row.get("is_target")}
        basis = comparison.get("basis")
        fallback_only = basis != "manual_then_multifactor"
        if not ids:
            return [], {"basis": basis, "fallback_only": fallback_only,
                        "trace": comparison.get("selection_trace", {})}
        rows = sorted(context.db.query(Company).filter(Company.ticker.in_(list(ids))).all(),
                      key=lambda c: c.ticker)
        return rows, {"basis": basis, "fallback_only": fallback_only,
                      "method": (comparison.get("selection_trace") or {}).get("method"),
                      "trace": comparison.get("selection_trace", {}), "limit": relative_multiples.PEER_LIMIT}

    monkeypatch.setattr(relative_multiples, "_peer_set", _old_peer_set)
    slow = ValuationService().value_company(db, company)
    assert json.dumps(fast, sort_keys=True, default=str) == json.dumps(slow, sort_keys=True, default=str)
