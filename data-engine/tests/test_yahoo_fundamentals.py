"""Fundamentales Yahoo no oficiales: identidad, no pisar SEC/ESEF, origen visible."""

from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.yahoo_fundamentals_service import refresh_from_yahoo


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="KRKNF", name="Kraken Robotics Inc (OTC)"):
    c = Company(
        ticker=ticker, name=name, exchange="OTC PINK", currency="USD", sector="S",
        industry="I", company_type="growth", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


def _fetcher(name="Kraken Robotics Inc.", currency="CAD"):
    cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    income = pd.DataFrame(
        {cols[0]: [102.21e6, 8.555e6, 0.01], cols[1]: [float("nan"), 5e6, 0.02]},
        index=["Total Revenue", "Operating Income", "Diluted EPS"],
    )
    cash = pd.DataFrame({cols[0]: [-9e6]}, index=["Capital Expenditure"])
    return lambda symbol: {
        "name": name, "currency": currency, "income": income,
        "balance": pd.DataFrame(), "cashflow": cash,
    }


def test_writes_labelled_unofficial_facts(db):
    company = _company(db)
    out = refresh_from_yahoo(db, company, fetcher=_fetcher())
    assert out["official"] is False and out["symbol"] == "PNG.V"
    facts = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)).all()
    assert {f.source_type for f in facts} == {"YAHOO_FUNDAMENTALS"}
    rev = [f for f in facts if f.metric == "revenue"]
    assert len(rev) == 1  # el NaN no se inventa
    assert rev[0].unit == "CAD" and rev[0].value == Decimal("102210000.0")
    assert rev[0].period == "2025-12-31:FY"
    eps = [f for f in facts if f.metric == "eps_diluted"]
    assert {f.unit for f in eps} == {"CAD/share"}
    capex = [f for f in facts if f.metric == "capital_expenditure"][0]
    assert capex.value < 0
    doc = db.get(Document, rev[0].source_id)
    assert "fuente no oficial" in doc.title
    assert "finance.yahoo.com/quote/PNG.V" in doc.source_url
    assert doc.metadata_["official"] is False and doc.metadata_["currency"] == "CAD"


def test_refresh_is_idempotent(db):
    company = _company(db)
    refresh_from_yahoo(db, company, fetcher=_fetcher())
    n1 = len(db.scalars(select(FinancialFact)).all())
    refresh_from_yahoo(db, company, fetcher=_fetcher())
    assert len(db.scalars(select(FinancialFact)).all()) == n1


def test_refuses_when_official_facts_exist(db):
    company = _company(db)
    db.add(Document(company_id=company.id, title="d", source_type="SEC"))
    db.flush()
    doc = db.scalars(select(Document)).first()
    db.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal(1), unit="USD",
                         period="2024-12-31:FY", fiscal_year=2024, fiscal_quarter="FY",
                         source_id=doc.id, source_type="SEC", is_reported=True,
                         confidence=Decimal("0.95")))
    db.commit()
    with pytest.raises(RuntimeError, match="SEC/ESEF"):
        refresh_from_yahoo(db, company, fetcher=_fetcher())


def test_identity_mismatch_rejected(db):
    company = _company(db)
    with pytest.raises(RuntimeError, match="company_mismatch"):
        refresh_from_yahoo(db, company, fetcher=_fetcher(name="Kerry Group plc"))
    assert db.scalars(select(FinancialFact)).all() == []


def test_currency_mismatch_rejected(db):
    company = _company(db)
    with pytest.raises(RuntimeError, match="currency_mismatch"):
        refresh_from_yahoo(db, company, fetcher=_fetcher(currency="USD"))


def test_unmapped_ticker_rejected(db):
    company = _company(db, ticker="ZZZZ", name="Zeta Corp")
    with pytest.raises(RuntimeError, match="mapa Yahoo"):
        refresh_from_yahoo(db, company, fetcher=_fetcher())
