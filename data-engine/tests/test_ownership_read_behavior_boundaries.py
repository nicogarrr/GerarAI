"""Persisted ownership evidence: real numbers are not N/D, missing stays missing.
NAV uses only a published, parseable source and never invents a discount.
"""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, DocumentChunk, Schedule13DGFiling
from app.services.holding_nav import extract_nav_per_share, latest_published_nav
from app.services.schedule13dg_service import filings_for_ticker


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_13dg_known_zero_and_positive_numbers_keep_wire_values_and_source(db):
    db.add(Schedule13DGFiling(tenant_id=1, accession_number="0001-26-000001", form="SC 13G",
        issuer_ticker="LOCAL", issuer_cik="1", filer_cik="2", holder_name="Local holder",
        aggregate_shares=1234567, percent_of_class=5.25, filing_date="2026-01-02",
        source_url="https://example.com/filing", index_url="https://example.com/index",
        parser_version="test-v1", status="parsed", is_amendment=False))
    db.add(Schedule13DGFiling(tenant_id=1, accession_number="0001-26-000002", form="SC 13G/A",
        issuer_ticker="LOCAL", issuer_cik="1", filer_cik="2", holder_name=None,
        aggregate_shares=0, percent_of_class=0, filing_date="2026-01-03",
        source_url="https://example.com/amendment", parser_version="test-v1", status="parsed",
        is_amendment=True))
    db.commit()
    out = filings_for_ticker(db, " local ")
    assert out["ticker"] == "LOCAL" and out["count"] == 2
    newest, original = out["filings"]
    assert newest["is_amendment"] is True
    assert newest["aggregate_shares"] == 0 and newest["percent_of_class"] == 0
    assert newest["display"] == {"holder": "N/D", "aggregate_shares": "0", "percent_of_class": "0,0 %", "snapshot_date": "N/D"}
    assert original["display"]["aggregate_shares"] == "1.234.567"
    assert original["display"]["percent_of_class"] == "5,2 %"
    assert original["source_url"] == "https://example.com/filing"
    assert original["index_url"] == "https://example.com/index"
    assert original["parser_version"] == "test-v1"
    assert filings_for_ticker(db, "LOCAL", limit=1)["filings"] == [newest]


def company(db):
    row = Company(ticker="LOCAL", name="Local holding", exchange="LSE", currency="GBp", company_type="holding", valuation_model="unassigned")
    db.add(row)
    db.commit()
    return row


def document(db, company, text, *, published, title):
    row = Document(company_id=company.id, title=title, source_type="test",
        source_url="https://example.com/" + title, published_at=published)
    db.add(row)
    db.flush()
    db.add(DocumentChunk(document_id=row.id, chunk_index=0, text=text, token_count=len(text.split())))
    db.commit()
    return row


def test_nav_rejects_zero_and_accepts_repeated_currency_symbol():
    hits = extract_nav_per_share("NAV per share GBP 0; NAV per share GBP £50.10")
    assert [(h["value"], h["currency"]) for h in hits] == [(50.10, "GBP")]
    assert "GBP £50.10" in hits[0]["quote"]


@pytest.mark.parametrize("price", [None, 0, -1])
def test_nav_no_price_has_cited_value_but_never_discount(db, price):
    c = company(db)
    document(db, c, "NAV per share GBP 50", published=datetime(2026, 1, 1, tzinfo=UTC), title="annual")
    out = latest_published_nav(db, c, price=price, price_currency="GBp", price_date=None, today=date(2026, 2, 1))
    assert out is not None
    assert out["nav_per_share"] == 50 and out["currency"] == "GBP"
    assert out["discount"] is None and out["discount_reason"] == "no_price"
    assert out["source"]["url"] == "https://example.com/annual"


def test_nav_newer_unparseable_chunk_does_not_hide_older_published_value(db):
    c = company(db)
    document(db, c, "NAV per share GBP 40", published=datetime(2026, 1, 1, tzinfo=UTC), title="old")
    document(db, c, "NAV per share (GBP) was down 5%", published=datetime(2026, 1, 2, tzinfo=UTC), title="new")
    out = latest_published_nav(db, c, price=2000, price_currency="GBp", price_date=date(2026, 2, 1), today=date(2026, 2, 1))
    assert out is not None
    assert out["source"]["title"] == "old"
    assert out["discount"] == pytest.approx(-0.5)


def test_nav_no_published_document_is_absent_not_zero(db):
    c = company(db)
    document(db, c, "NAV per share GBP 40", published=None, title="undated")
    assert latest_published_nav(db, c, price=2000, price_currency="GBp", price_date=None, today=date(2026, 2, 1)) is None
