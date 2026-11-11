"""Splits leídos una vez por llamada de valoración (perf r5, 11-nov-2026).

Antes, ``value_company`` pedía a ``corporate_actions`` los splits de la MISMA
empresa por cada hecho ajustado (``split_factor_for_fact``): 16-33 SELECT
iguales por llamada en la base local (QCOM 142 -> 115 consultas en total).
Ahora la lectura entra en la caché acotada a la llamada
(``app/valuation/call_cache.py``): una por conjunto de compañías, resultado
idéntico, y fuera de la llamada todo sigue consulta a consulta.

Conteos deterministas con un listener de eventos, nunca reloj.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import Company, CorporateAction, FinancialFact, MarketPrice, Tenant
from app.models.entities import Base
from app.services.split_adjustment import split_events_by_company
from app.services.valuation_service import ValuationService
from app.valuation.call_cache import _CACHE_KEY, valuation_call_cache

TODAY = date(2026, 11, 11)


def _facts(company_id: int) -> list[dict]:
    rows = []
    for year in (2023, 2024, 2025):
        for metric, value in (("revenue", 10e9), ("free_cash_flow", 1e9), ("operating_cash_flow", 1.5e9),
                              ("capital_expenditure", -5e8), ("net_income", 8e8), ("ebitda", 1.4e9),
                              ("net_debt", 2e9), ("shares_diluted", 1e9), ("eps_diluted", 0.8),
                              ("cash_and_equivalents", 1e9), ("total_debt", 3e9)):
            rows.append(dict(company_id=company_id, metric=metric, value=value, unit="USD",
                             period=f"{year}-12-31:FY", fiscal_year=year, source_type="SEC",
                             is_reported=True, tenant_id=1, filed=date(year + 1, 2, 15)))
    return rows


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1", name="one"))
        session.add(Company(id=1, ticker="SPL", name="Split Co", exchange="NYSE", currency="USD",
                            sector="Technology", industry="Software", company_type="asset_light",
                            valuation_model="dcf_standard", factor_tags=["software"]))
        session.flush()
        session.execute(FinancialFact.__table__.insert(), _facts(1))
        # Un split 4:1 en mitad de la serie: los hechos anteriores se ajustan.
        session.add(CorporateAction(company_id=1, tenant_id=1, action_type="split", ratio=4,
                                    effective_date=date(2025, 6, 2)))
        session.add(MarketPrice(company_id=1, date=TODAY - timedelta(days=1), open=20, high=21,
                                low=19, close=20.5, quote_currency="USD", source="yfinance"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session


def _count_split_selects(session: Session, fn) -> int:
    count = {"n": 0}

    def _listener(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "corporate_actions" in statement:
            count["n"] += 1

    event.listen(session.get_bind(), "before_cursor_execute", _listener)
    try:
        fn()
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", _listener)
    return count["n"]


def test_value_company_reads_each_company_splits_once(db):
    company = db.get(Company, 1)
    n = _count_split_selects(db, lambda: ValuationService().value_company(db, company))
    # Antes de este cambio: una lectura por hecho ajustado (>1). Ahora una.
    assert n == 1
    assert _CACHE_KEY not in db.info


def test_value_company_identical_with_and_without_cache(db, monkeypatch):
    company = db.get(Company, 1)
    with_cache = ValuationService().value_company(db, company)
    db.expire_all()
    monkeypatch.setattr("app.services.valuation_service.valuation_call_cache", contextlib.nullcontext)
    without = ValuationService().value_company(db, company)
    assert json.dumps(with_cache, sort_keys=True, default=str) == json.dumps(without, sort_keys=True, default=str)


def test_outside_valuation_call_every_read_hits_the_db(db):
    n = _count_split_selects(db, lambda: [split_events_by_company(db, [1]) for _ in range(3)])
    assert n == 3


def test_cached_events_cannot_be_mutated_by_a_caller(db):
    with valuation_call_cache(db):
        first = split_events_by_company(db, [1])
        first[1].clear()
        first[99] = []
        again = split_events_by_company(db, [1])
    assert set(again) == {1}
    assert [(day, float(ratio)) for day, ratio in again[1]] == [(date(2025, 6, 2), 4.0)]


def test_key_ignores_order_and_duplicates(db):
    with valuation_call_cache(db):
        n = _count_split_selects(db, lambda: (split_events_by_company(db, [1, 1]),
                                              split_events_by_company(db, [1])))
    assert n == 1
