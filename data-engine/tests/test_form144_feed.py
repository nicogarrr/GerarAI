"""Feed insider: la seccion proposed_sales lista avisos Form 144
persistidos y NUNCA los mezcla con las operaciones P/S ejecutadas."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Form144Notice
from app.services import insider_feed


@pytest.fixture(autouse=True)
def _own_databases():
    yield
    for engine in _isolated_engines:
        engine.dispose()
    _isolated_engines.clear()


_isolated_engines = []


def _db():
    engine = create_engine("sqlite:///:memory:")
    _isolated_engines.append(engine)
    Base.metadata.create_all(engine)
    return Session(engine)


def _notice(**overrides) -> Form144Notice:
    data = {
        "accession_number": "0000849869-26-000005",
        "form": "144",
        "is_amendment": False,
        "issuer_cik": "0000849869",
        "issuer_ticker": "SLGN",
        "issuer_name": "SILGAN HOLDINGS INC",
        "seller_cik": "0001164469",
        "seller_name": "LEWIS ROBERT B",
        "relationships": ["Director"],
        "broker_name": "FSC Securities Corporation",
        "securities_class_title": "Common Stock",
        "shares_to_sell": 88861.0,
        "aggregate_market_value": 3687731.50,
        "shares_outstanding": 105682020.0,
        "approx_sale_date": "11/16/2026",
        "exchange": "NYSE",
        "securities": [],
        "acquisitions": [],
        "sales_past_3m": [],
        "nothing_to_report_past_3m": True,
        "notice_date": "11/13/2026",
        "plan_adoption_dates": [],
        "remarks": None,
        "filing_date": "2026-11-13",
        "source_url": "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml",
        "index_url": "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/",
        "raw_sha256": None,
        "parser_version": "1.0",
        "status": "parsed",
        "error": None,
    }
    data.update(overrides)
    return Form144Notice(**data)


def test_feed_lists_proposed_sales_separate_from_transactions():
    db = _db()
    db.add(_notice())
    db.commit()
    feed = insider_feed.build_feed(db, days=90, today=date(2026, 11, 18))
    assert feed["totals"]["proposed_sales_count"] == 1
    assert len(feed["proposed_sales"]) == 1
    entry = feed["proposed_sales"][0]
    assert entry["ticker"] == "SLGN"
    assert entry["seller"] == "LEWIS ROBERT B"
    assert entry["relationships"] == ["Director"]
    assert entry["shares"] == 88861.0
    assert entry["market_value"] == 3687731.50
    assert entry["approx_sale_date"] == "11/16/2026"
    assert entry["has_10b5_1_plan"] is False
    # DERIVADO de cifras declaradas: 88861 / 105682020.
    assert entry["pct_of_shares_outstanding"] == pytest.approx(0.0841, abs=0.001)
    # Un aviso jamas cuenta como operacion ejecutada.
    assert feed["totals"]["sell_count"] == 0
    assert feed["totals"]["buy_count"] == 0
    assert feed["transactions"] == []


def test_feed_marks_10b5_1_plan_adoption():
    db = _db()
    db.add(_notice(plan_adoption_dates=["06/23/2023"]))
    db.commit()
    feed = insider_feed.build_feed(db, days=90, today=date(2026, 11, 18))
    entry = feed["proposed_sales"][0]
    assert entry["has_10b5_1_plan"] is True
    assert entry["plan_adoption_dates"] == ["06/23/2023"]


def test_feed_respects_cutoff_and_ticker_filter():
    db = _db()
    db.add(_notice())
    db.add(_notice(accession_number="0000849869-25-000001", filing_date="2025-01-10"))
    db.commit()
    feed = insider_feed.build_feed(db, days=90, today=date(2026, 11, 18))
    # Solo el aviso dentro de la ventana de 90 dias.
    assert feed["totals"]["proposed_sales_count"] == 1
    feed = insider_feed.build_feed(db, days=90, ticker="OTRO", today=date(2026, 11, 18))
    assert feed["totals"]["proposed_sales_count"] == 0
    assert feed["proposed_sales"] == []


def test_feed_missing_figures_stay_none():
    db = _db()
    db.add(_notice(shares_to_sell=None, aggregate_market_value=None, shares_outstanding=None))
    db.commit()
    feed = insider_feed.build_feed(db, days=90, today=date(2026, 11, 18))
    entry = feed["proposed_sales"][0]
    assert entry["shares"] is None
    assert entry["market_value"] is None
    assert entry["pct_of_shares_outstanding"] is None
