"""Aislamiento de tenant de seis funciones de fondo (sin tenant propio en su firma).

Cada una se ejecuta con la sesion de un tenant y con filas del OTRO tenant
sembradas para la misma empresa/ticker/CIK: no debe leerlas, ni modificarlas,
ni borrarlas. ``_scope_tenant_queries``/``_scope_tenant_dml`` (database.py)
son quienes lo garantizan; estos tests fijan el contrato por funcion para
que un SQL crudo o un ``include_all_tenants`` nuevo no lo rompa en silencio.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.core.database  # noqa: F401 - registra los listeners de tenant
from app.models.entities import (
    AlertRule,
    Base,
    Company,
    DriverAssumptionVersion,
    FactRevision,
    FinancialFact,
    FundManager,
    InsiderFiling,
    InsiderTransaction,
    ManagementPromise,
    ManagerHolding,
    Tenant,
    ThesisVersion,
)

T1, T2 = 1, 2


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.commit()
        yield session
    engine.dispose()


def _as(db: Session, tenant_id: int) -> Session:
    db.info["tenant_id"] = tenant_id
    return db


def _all(db: Session, stmt):
    return db.scalars(stmt.execution_options(include_all_tenants=True)).all()


def _company(db: Session, ticker: str = "ACME") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _thesis(db: Session, company: Company, threshold: float) -> ThesisVersion:
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="final",
        thesis_markdown="# Tesis", executive_summary="Resumen", rating="watch",
        current_price=Decimal("300"), expected_value=Decimal("400"),
        invalidation_criteria=["x"],
        invalidation_rules=[{"metric": "precio", "operator": "<", "threshold": threshold}],
    )
    db.add(thesis)
    db.commit()
    return thesis


# --- sync_all_thesis_rules ------------------------------------------------

def test_sync_all_thesis_rules_only_touches_the_session_tenant(db):
    from app.services.thesis_invalidation_rules import RULE_TYPE, sync_all_thesis_rules

    shared = _company(db, "SHRD")
    only_other = _company(db, "OTHR")
    _as(db, T2)
    _thesis(db, shared, 100)
    _thesis(db, only_other, 50)
    sync_all_thesis_rules(db)
    db.commit()
    other_rules = {(r.company_id, r.name, r.active) for r in _all(db, select(AlertRule))}
    assert len(other_rules) == 2

    _as(db, T1)
    _thesis(db, shared, 200)
    sync_all_thesis_rules(db)
    db.commit()

    rows = _all(db, select(AlertRule))
    mine = [r for r in rows if r.tenant_id == T1]
    theirs = {(r.company_id, r.name, r.active) for r in rows if r.tenant_id == T2}
    # Solo la regla de MI tesis; ninguna para la empresa que solo tiene tesis ajena.
    assert [(r.company_id, r.rule_type, r.condition["value"]) for r in mine] == [
        (shared.id, RULE_TYPE, 200.0)
    ]
    # Las reglas del otro tenant siguen intactas (ni desactivadas ni duplicadas).
    assert theirs == other_rules


# --- delete_financial_facts -----------------------------------------------

def _fact(db: Session, company: Company, value: str) -> FinancialFact:
    fact = FinancialFact(
        company_id=company.id, metric="net_income", value=Decimal(value), unit="USD",
        period="FY2025", fiscal_year=2025, source_type="SEC", is_reported=False,
    )
    db.add(fact)
    db.flush()
    db.add(FactRevision(financial_fact_id=fact.id, previous_value=Decimal(value),
                        new_value=Decimal(value), reason="restated", canonical_version=1))
    db.add(ManagementPromise(company_id=company.id, promise="x", promise_date=date(2026, 1, 1),
                             expected_period="FY2026", actual_fact_id=fact.id))
    db.commit()
    return fact


def test_delete_financial_facts_never_deletes_or_detaches_another_tenant(db):
    from app.services.fact_deletion import delete_financial_facts

    company = _company(db)
    theirs = _fact(_as(db, T2), company, "2")
    mine = _fact(_as(db, T1), company, "1")

    deleted = delete_financial_facts(db, FinancialFact.company_id == company.id)
    db.commit()

    assert deleted == 1
    facts = {f.id: f.tenant_id for f in _all(db, select(FinancialFact))}
    assert facts == {theirs.id: T2}
    revisions = {r.financial_fact_id for r in _all(db, select(FactRevision))}
    assert revisions == {theirs.id}
    reviews = {(r.tenant_id, r.actual_fact_id) for r in _all(db, select(ManagementPromise))}
    assert reviews == {(T1, None), (T2, theirs.id)}
    assert mine.id not in facts


# --- insider_signal -------------------------------------------------------

def _insider(db: Session, ticker: str, insider: str, code: str, shares: float) -> None:
    filing = InsiderFiling(
        accession_number=f"acc-{db.info['tenant_id']}-{insider}", form="4",
        issuer_cik="0000000001", issuer_ticker=ticker, filing_date="2026-09-01",
        parser_version="test",
    )
    db.add(filing)
    db.flush()
    db.add(InsiderTransaction(
        fingerprint=f"fp-{db.info['tenant_id']}-{insider}", filing_id=filing.id,
        accession_number=filing.accession_number, form="4", issuer_ticker=ticker,
        insider=insider, role="Director", code=code, shares=shares, price=10.0,
        value=shares * 10.0, tx_date="2026-09-01", is_derivative=False,
        rule_10b5_1=False,
    ))
    db.commit()


def test_insider_signal_reads_only_the_session_tenant(db):
    from app.services.ticker_ownership_signals import insider_signal

    _insider(_as(db, T2), "UBER", "OTHER", "S", 9999)
    _as(db, T1)
    assert insider_signal(db, "UBER", as_of=date(2026, 10, 1))["status"] == "sin_datos"
    _insider(db, "UBER", "MINE", "P", 100)
    signal = insider_signal(db, "UBER", as_of=date(2026, 10, 1))
    assert signal["buys"]["trades"] == 1
    assert signal["sells"]["trades"] == 0


# --- active_overrides / _driver_overrides ---------------------------------

def _driver_with_version(db: Session, company: Company, key: str, value: str):
    from tests.test_driver_assumption_service import _driver

    driver = _driver(db, company, key)
    db.add(DriverAssumptionVersion(
        driver_id=driver.id, fiscal_year=2027, scenario="base", value=Decimal(value),
        source="user", user_override=True, confidence=Decimal("0.5"),
        rationale=f"tenant {db.info['tenant_id']}",
    ))
    db.commit()
    return driver


def test_active_overrides_reads_only_the_session_tenant(db):
    from app.services.driver_assumption_service import DriverAssumptionService

    company = _company(db)
    _driver_with_version(_as(db, T2), company, "revenue_growth", "0.90")
    _as(db, T1)
    assert DriverAssumptionService().active_overrides(db, company) == {}
    _driver_with_version(db, company, "operating_margin", "0.10")
    result = DriverAssumptionService().active_overrides(db, company)
    assert list(result) == ["operating_margin"]
    assert result["operating_margin"][2027]["base"]["value"] == 0.10


def test_driver_overrides_of_thesis_projection_read_only_the_session_tenant(db):
    from app.services.thesis_projection_service import GROWTH_KEY, ThesisProjectionService

    company = _company(db)
    _driver_with_version(_as(db, T2), company, GROWTH_KEY, "0.90")
    _as(db, T1)
    service = ThesisProjectionService.__new__(ThesisProjectionService)
    assert service._driver_overrides(db, company, date(2100, 1, 1)) == {}
    _driver_with_version(db, company, GROWTH_KEY, "0.05")
    out = service._driver_overrides(db, company, date(2100, 1, 1))
    assert out == {(GROWTH_KEY, 2027, "base"): {"value": pytest.approx(0.05), "source": "user",
                                                "user_override": True}}


# --- sync_manager ---------------------------------------------------------

def test_sync_manager_creates_its_own_manager_and_rows_per_tenant(db):
    from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService
    from tests.test_manager_holdings import CIK, _sec_client

    service = ManagerHoldingIngestionService(client=_sec_client())
    assert service.sync_manager(_as(db, T2), cik=CIK)["status"] == "ok"
    db.commit()
    other_rows = len(_all(db, select(ManagerHolding)))
    assert other_rows > 0

    result = service.sync_manager(_as(db, T1), cik=CIK)
    db.commit()
    # El tenant 1 no reutiliza el gestor ni las filas del 2: los suyos propios.
    assert result["status"] == "ok"
    assert result["ingested_rows"] == other_rows
    managers = {(m.tenant_id, m.cik) for m in _all(db, select(FundManager))}
    assert managers == {(T1, CIK), (T2, CIK)}
    holdings = _all(db, select(ManagerHolding))
    assert sum(h.tenant_id == T1 for h in holdings) == other_rows
    assert sum(h.tenant_id == T2 for h in holdings) == other_rows
    by_id = {m.id: m.tenant_id for m in _all(db, select(FundManager))}
    assert all(by_id[h.manager_id] == h.tenant_id for h in holdings)
