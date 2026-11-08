"""NAV por acción publicado (holdings) en el Informe, con su documento y cita.

Fixtures: extractos literales de dos RNS de Georgia Capital del NSM de la FCA
(https://data.fca.org.uk/artefacts/NSM/RNS/…): 1T 2021 (solo GEL) y 1S 2026
(GEL y GBP en la misma tabla).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, DocumentChunk, MarketPrice
from app.services.analyst_report import build_company_report

FIX = Path(__file__).parent / "fixtures"
H1_2026 = (FIX / "cgeo_rns_half_year_2026.txt").read_text("utf-8")
Q1_2021 = (FIX / "cgeo_rns_1q_2021.txt").read_text("utf-8")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _holding(db):
    company = Company(
        ticker="CGEO.L", name="Georgia Capital", exchange="LSE", currency="GBp",
        sector="Financials", industry="Holding", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _doc(db, company, text, *, published, url, title):
    doc = Document(company_id=company.id, title=title, source_type="FCA_NSM", source_url=url,
                   published_at=datetime.combine(published, datetime.min.time(), tzinfo=UTC),
                   metadata_={"report_date": None})
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text=text, token_count=len(text.split())))
    db.commit()
    return doc


def _price(db, company, close_pence, day):
    db.add(MarketPrice(company_id=company.id, date=day, open=close_pence, high=close_pence, low=close_pence,
                       close=Decimal(str(close_pence)), volume=1000, quote_currency="GBp", source="test"))
    db.commit()


def test_extracts_table_form_only():
    from app.services.holding_nav import extract_nav_per_share

    hits = extract_nav_per_share(H1_2026)
    assert [(h["value"], h["currency"]) for h in hits[:2]] == [(175.12, "GEL"), (50.10, "GBP")]
    # una frase con la divisa entre paréntesis y un % no es una cifra de NAV
    assert extract_nav_per_share("NAV per share (GEL) was down 2.7% in 1Q21 to GEL 46.80.") == []
    assert extract_nav_per_share("NAV per share was 12 here") == []
    hits = extract_nav_per_share("Net asset value per share £12.34; NAV per ordinary share (pence) 1,234.5")
    assert [(h["value"], h["currency"]) for h in hits] == [(12.34, "GBP"), (1234.5, "GBp")]


def test_informe_has_published_nav_and_discount_in_price_currency(db):
    company = _holding(db)
    _doc(db, company, Q1_2021, published=date(2021, 5, 18), title="1st Quarter Results",
         url="https://data.fca.org.uk/artefacts/NSM/RNS/3977489.html")
    _doc(db, company, H1_2026, published=date(2026, 8, 4), title="Half-year Financial Report",
         url="https://data.fca.org.uk/artefacts/NSM/RNS/h1-2026.html")
    _price(db, company, 4200, date(2026, 11, 6))  # 42,00 £
    nav = build_company_report(db, company, today=date(2026, 11, 8))["nav"]
    assert nav is not None
    assert nav["nav_per_share"] == pytest.approx(50.10) and nav["currency"] == "GBP"
    assert nav["price"] == pytest.approx(42.0) and nav["price_currency"] == "GBP"
    assert nav["discount"] == pytest.approx(42.0 / 50.10 - 1)
    assert nav["source"]["url"].endswith("h1-2026.html")
    assert nav["source"]["published"] == date(2026, 8, 4)
    assert "NAV per share, GBP 50.10" in nav["source"]["quote"]
    assert {"value": 175.12, "currency": "GEL"} in nav["other_currencies"]


def test_point_in_time_and_currency_mismatch(db):
    company = _holding(db)
    _doc(db, company, Q1_2021, published=date(2021, 5, 18), title="1st Quarter Results",
         url="https://data.fca.org.uk/artefacts/NSM/RNS/3977489.html")
    _doc(db, company, H1_2026, published=date(2026, 8, 4), title="Half-year Financial Report",
         url="https://data.fca.org.uk/artefacts/NSM/RNS/h1-2026.html")
    _price(db, company, 1500, date(2021, 6, 30))
    # A 30-jun-2021 el informe de 2026 no existía: manda el de 2021, solo en GEL.
    nav = build_company_report(db, company, today=date(2021, 6, 30))["nav"]
    assert nav is not None and nav["nav_per_share"] == pytest.approx(46.80) and nav["currency"] == "GEL"
    assert nav["discount"] is None and nav["discount_reason"] == "currency_mismatch"
    assert nav["source"]["published"] <= date(2021, 6, 30)


def test_company_without_nav_documents_has_none(db):
    company = _holding(db)
    _doc(db, company, "Revenue was GBP 12 million.", published=date(2026, 1, 2) - timedelta(days=1),
         title="Annual report", url="https://example.com/ar.pdf")
    assert build_company_report(db, company, today=date(2026, 11, 8))["nav"] is None
