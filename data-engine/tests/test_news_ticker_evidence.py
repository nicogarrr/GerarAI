"""Un ticker corto solo vincula una noticia con evidencia (cashtag, bolsa o nombre)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.news_service import NewsService, _ticker_evidence


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker, name=name, exchange="NYSE", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_acronym_and_article_do_not_match_short_tickers():
    assert not _ticker_evidence("AAP", "Advance Auto Parts Inc", "AAP names four candidates for Bihar council polls")
    assert not _ticker_evidence("A", "Agilent Technologies Inc", "A Targeted News Service")
    assert not _ticker_evidence("A", "Agilent Technologies Inc", "Shares of a company rose")


def test_short_ticker_with_evidence_matches():
    assert _ticker_evidence("AAP", "Advance Auto Parts Inc", "Advance Auto Parts (AAP) cuts guidance")
    assert _ticker_evidence("ADI", "Analog Devices Inc", "ADI Analog Devices , Inc . $ADI Shares Sold")
    assert _ticker_evidence("JPM", "JPMorgan Chase & Co", "JPM JPMorgan Chase & Co . ( NYSE : JPM ) Stock Price Down")
    assert _ticker_evidence("AAP", "Advance Auto Parts Inc", "Stock $aap jumps")


def test_short_ticker_with_nearby_financial_context_matches():
    assert _ticker_evidence("AMD", "Advanced Micro Devices Inc", "AMD stock jumps after guidance")
    assert _ticker_evidence("IBM", "International Business Machines", "Shares of IBM rise on cloud demand")
    assert _ticker_evidence("IBM", "International Business Machines", "IBM beats earnings estimates")
    assert _ticker_evidence("KO", "Coca-Cola Co", "KO dividend hike announced")
    assert not _ticker_evidence("AAP", "Advance Auto Parts Inc", "AAP names four candidates for Bihar council polls")


def test_financial_word_far_from_ticker_does_not_count():
    far = "AMD was mentioned once in a long list of unrelated topics before anyone discussed the stock market"
    assert not _ticker_evidence("AMD", "Advanced Micro Devices Inc", far)


def test_ambiguous_symbols_need_cashtag_exchange_or_name():
    assert not _ticker_evidence("ALL", "Allstate Corp", "ALL shares of the fund were sold, stock fell")
    assert not _ticker_evidence("IT", "Gartner Inc", "IT spending rises while stock markets wobble")
    assert not _ticker_evidence("ON", "ON Semiconductor Corp", "ON Tuesday, shares of chipmakers rose")
    assert not _ticker_evidence("EU", "Some EU Fund", "EU bans trading in the product")
    assert _ticker_evidence("ALL", "Allstate Corp", "Allstate (NYSE: ALL) raises dividend")
    assert _ticker_evidence("IT", "Gartner Inc", "Gartner $IT stock slides")


def test_long_ticker_matches_with_case_sensitivity():
    assert _ticker_evidence("AAPL", "Apple Inc", "AAPL beats expectations")
    assert not _ticker_evidence("AAPL", "Apple Inc", "the snappiest pineapple")


def test_detect_ticker_uses_evidence(db):
    _company(db, "AAP", "Advance Auto Parts Inc")
    service = NewsService()
    assert service.detect_ticker(db, "AAP names four candidates for Bihar council polls") is None
    assert service.detect_ticker(db, "Advance Auto Parts (NYSE: AAP) cuts guidance") is not None


def test_detect_ticker_picks_strongest_evidence_and_skips_ties(db):
    _company(db, "A", "Agilent Technologies Inc")
    _company(db, "AAPL", "Apple Inc")
    service = NewsService()
    # «A look at Apple earnings» no debe vincularse a Agilent (sigla de una letra).
    assert service.detect_ticker(db, "A look at Apple earnings this week") is None
    got = service.detect_ticker(db, "A look at Apple (NASDAQ: AAPL) earnings this week")
    assert got is not None and got.ticker == "AAPL"
    # Cashtag gana al contexto.
    _company(db, "IBM", "International Business Machines")
    got = service.detect_ticker(db, "IBM stock steady while $AAPL rallies")
    assert got is not None and got.ticker == "AAPL"
    # Empate en el nivel mas alto: ninguna.
    assert service.detect_ticker(db, "$AAPL and $IBM both up") is None


def test_cornerback_headline_does_not_link_to_chubb():
    """Caso real 19 oct 2026: «CB Target» (cornerback, fútbol americano) se
    vinculó a Chubb (CB) por la palabra «target» en proximidad."""
    assert not _ticker_evidence(
        "CB", "Chubb Limited",
        "Tennessee Football 2028 In-State CB Target Jermaine Cobbins Visits for Third Saturday in October")
    assert not _ticker_evidence("CB", "Chubb Limited", "CB target practice scheduled for Saturday")


def test_price_target_phrase_still_counts_as_context():
    assert _ticker_evidence("CB", "Chubb Limited", "CB price target raised at Wells")
    assert _ticker_evidence("CB", "Chubb Limited", "Elevan el precio objetivo de CB")
    # Locuciones de analista reales (objeción del auditor, 19 oct 2026):
    assert _ticker_evidence("CB", "Chubb Limited", "Wells Fargo raises CB target price to $300")
    assert _ticker_evidence("CB", "Chubb Limited", "CB target price raised")
    assert _ticker_evidence("CB", "Chubb Limited", "Jefferies sets CB target at $280")
