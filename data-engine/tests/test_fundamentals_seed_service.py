"""Fundamentals seed contract tests (cobertura cartera+watchlist por tenant).

FinancialFact es por tenant: un tenant nuevo no ve los hechos de otro. La
siembra automatica debe elegir la via con datos declarados (mercado/sufijo,
CIK, snapshot ESEF revisado), ser idempotente cuando ya hay hechos y nunca
inventar.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services import fundamentals_seed_service as seed
from app.services.fundamentals_seed_service import (
    enqueue_fundamentals_seed,
    fundamentals_lane,
    seed_company_fundamentals,
    tenant_has_facts,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, **overrides) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    for key, value in overrides.items():
        setattr(company, key, value)
    db.add(company)
    db.commit()
    return company


def _fact(db: Session, company: Company) -> FinancialFact:
    fact = FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("100"),
        unit="USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    )
    db.add(fact)
    db.commit()
    return fact


def test_lane_esef_by_suffix_and_exchange(db):
    assert fundamentals_lane(_company(db, "AENA.MC", cik="123")) == "esef"
    assert fundamentals_lane(_company(db, "ASML", exchange="EURONEXT AMSTERDAM", cik="999")) == "esef"
    # Nomenclatura historica de Finnhub: NO es NYSE.
    assert fundamentals_lane(_company(db, "NN", exchange="NYSE EURONEXT - AMSTERDAM", cik="999")) == "esef"


def test_lane_sec_by_cik_and_default(db):
    assert fundamentals_lane(_company(db, "UNH", cik="731766")) == "sec"
    assert fundamentals_lane(_company(db, "KO", cik="21344")) == "sec"


def test_lane_esef_by_local_snapshot_without_cik(db, monkeypatch):
    company = _company(db, "KRKNF", exchange="OTC", cik=None)
    monkeypatch.setattr(
        seed.esef_connector, "read_esef_snapshot", lambda ticker: {"facts": {}}
    )
    assert fundamentals_lane(company) == "esef"


def test_tenant_has_facts_is_tenant_scoped(db):
    company = _company(db, "UNH")
    assert tenant_has_facts(db, company) is False
    _fact(db, company)
    assert tenant_has_facts(db, company) is True


def test_seed_is_idempotent_with_existing_facts(db, monkeypatch):
    company = _company(db, "UNH", cik="731766")
    _fact(db, company)

    def _boom(*args, **kwargs):  # no debe ni intentar la ingesta
        raise AssertionError("refresh llamado con hechos presentes")

    monkeypatch.setattr(seed, "FinancialIngestionService", _boom, raising=False)
    result = seed_company_fundamentals(db, company)
    assert result["status"] == "ya_tiene_hechos"


class _FakeIngestion:
    def __init__(self):
        self.calls = []

    async def refresh_from_sec(self, db, company):
        self.calls.append(("sec", company.ticker))
        return {"facts_imported": 12}

    async def refresh_from_esef(self, db, company):
        self.calls.append(("esef", company.ticker))
        return {"facts_imported": 9}


def test_seed_uses_declared_lane_and_reports(monkeypatch, db):
    fake = _FakeIngestion()
    monkeypatch.setattr(
        "app.services.financial_ingestion_service.FinancialIngestionService",
        lambda: fake,
    )
    unh = _company(db, "UNH", cik="731766")
    result = seed_company_fundamentals(db, unh)
    assert result["status"] == "sembrado"
    assert result["via"] == "sec"
    assert result["facts_imported"] == 12
    assert fake.calls == [("sec", "UNH")]


def test_enqueue_without_tenant_context_is_a_noop(db):
    db.info.pop("tenant_id", None)
    db.info.pop("user_id", None)
    assert enqueue_fundamentals_seed(db, "UNH") is False
