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
        {cols[0]: [102.21e6, 8.555e6, 0.01, 294.2e6], cols[1]: [float("nan"), 5e6, 0.02, 290e6]},
        index=["Total Revenue", "Operating Income", "Diluted EPS", "Diluted Average Shares"],
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
    assert rev[0].is_reported is False
    assert rev[0].period == "2025-12-31:FY"
    eps = [f for f in facts if f.metric == "eps_diluted"]
    assert {f.unit for f in eps} == {"CAD/share"}
    shares = [f for f in facts if f.metric == "shares_diluted"]
    assert {f.unit for f in shares} == {"shares"}
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


def _official_fact(db, company, metric, year):
    doc = db.scalars(select(Document).where(Document.company_id == company.id, Document.source_type == "SEC")).first()
    if doc is None:
        doc = Document(company_id=company.id, title="d", source_type="SEC")
        db.add(doc)
        db.flush()
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(1), unit="USD",
                         period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
                         source_id=doc.id, source_type="SEC", is_reported=True,
                         confidence=Decimal("0.95")))
    db.commit()


def test_complements_partial_official_coverage_without_touching_it(db):
    """BN: el 40-F aporta unos pocos hechos; Yahoo completa el resto."""
    company = _company(db)
    _official_fact(db, company, "revenue", 2025)
    out = refresh_from_yahoo(db, company, fetcher=_fetcher())
    assert out["facts_skipped_official"] == 1
    assert out["facts_imported"] > 0
    facts = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)).all()
    # El hecho oficial sigue intacto y es el unico revenue 2025.
    rev = [f for f in facts if f.metric == "revenue"]
    assert len(rev) == 1 and rev[0].source_type == "SEC" and rev[0].value == Decimal(1)
    # El resto de metricas llegan de Yahoo, marcadas como no oficiales.
    yahoo = [f for f in facts if f.source_type == "YAHOO_FUNDAMENTALS"]
    assert yahoo and all(f.is_reported is False for f in yahoo)
    assert {f.metric for f in yahoo} >= {"operating_income", "capital_expenditure"}


def test_refuses_when_official_coverage_is_complete(db):
    company = _company(db)
    for metric, year in [
        ("revenue", 2025),
        ("operating_income", 2025), ("operating_income", 2024),
        ("eps_diluted", 2025), ("eps_diluted", 2024),
        ("shares_diluted", 2025), ("shares_diluted", 2024),
        ("capital_expenditure", 2025),
    ]:
        _official_fact(db, company, metric, year)
    with pytest.raises(RuntimeError, match="nada que complementar"):
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


def test_bn_reviewed_map_entry_and_identity():
    from app.services.yahoo_fundamentals_service import REVIEWED_MAP, _name_identity_ok

    entry = REVIEWED_MAP["BN"]
    assert entry["symbol"] == "BN" and entry["currency"] == "USD"
    yname = "Brookfield Corporation"
    assert _name_identity_ok("Brookfield Corporation", yname)
    assert any(_name_identity_ok(n, yname) for n in entry["names"])


def test_bn_ingests_in_usd_with_unofficial_label(db):
    company = _company(db, ticker="BN", name="Brookfield Corporation")
    out = refresh_from_yahoo(db, company, fetcher=_fetcher(name="Brookfield Corporation", currency="USD"))
    assert out["symbol"] == "BN" and out["currency"] == "USD" and out["official"] is False
    facts = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)).all()
    assert facts and {f.source_type for f in facts} == {"YAHOO_FUNDAMENTALS"}
    assert {f.unit for f in facts if f.metric == "revenue"} == {"USD"}
