"""Veracidad de /corporate-actions: ni historia antigua que tape lo accionable ni splits duplicados."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.corporate_actions import list_actions
from app.models.entities import Base, Company, CorporateAction
from app.services.split_ingestion_service import SplitIngestionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker):
    row = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD", company_type="operating", valuation_model="unassigned")
    db.add(row)
    db.flush()
    return row


def test_list_cap_trims_old_history_not_recent_actions(db):
    old = _company(db, "OLD")
    recent = _company(db, "NEW")
    for i in range(205):  # splits antiguos importados del universo
        db.add(CorporateAction(tenant_id=1, company_id=old.id, action_type="split", effective_date=date(1970, 1, 1) + timedelta(days=i), ratio=Decimal("2"), applied=False, source="yahoo_finance"))
    db.add(CorporateAction(tenant_id=1, company_id=recent.id, action_type="split", effective_date=date.today() - timedelta(days=2), ratio=Decimal("3"), applied=False, source="yahoo_finance"))
    db.commit()
    rows = list_actions(limit=200, db=db)
    assert len(rows) == 200
    assert rows[0]["ticker"] == "NEW"  # el split reciente entra en la lista
    assert rows == sorted(rows, key=lambda r: r["effective_date"], reverse=True)


class _Yahoo:
    def __init__(self, rows):
        self.rows = rows

    async def splits(self, ticker):
        return self.rows


class _FMP:
    def __init__(self, rows):
        self.rows = rows

    async def splits(self, ticker):
        return self.rows


def test_non_terminating_ratio_is_stored_precision_so_dedupe_matches():
    ratio = SplitIngestionService._parse_ratio({"numerator": 5, "denominator": 3})
    assert ratio == ratio.quantize(Decimal("1e-10"))  # cabe en Numeric(24, 10)


def test_same_split_from_yahoo_then_fmp_one_day_apart_is_not_duplicated(db):
    _company(db, "MCD")
    yahoo = [{"date": 1598832000, "numerator": 2, "denominator": 1}]  # 2020-08-31
    asyncio.run(SplitIngestionService(fmp=_FMP([]), yahoo=_Yahoo(yahoo)).sync_company(db, ticker="MCD"))

    class _YahooDown:
        async def splits(self, ticker):
            raise RuntimeError("down")

    fmp = [{"date": "2020-09-01", "numerator": 2, "denominator": 1}]
    result = asyncio.run(SplitIngestionService(fmp=_FMP(fmp), yahoo=_YahooDown()).sync_company(db, ticker="MCD"))
    assert result["inserted"] == 0 and result["existing"] == 1
    assert len(db.scalars(select(CorporateAction)).all()) == 1
