"""Ex-dates de Yahoo en la fecha LOCAL de la bolsa, no en UTC.

Yahoo fecha cada evento con el epoch de la apertura local. Datos reales del
chart (consultados el 30-oct-2026):
- BHP.AX dividendo: 1709766000 = 2024-03-06 23:00 UTC = 2024-03-07 10:00 Sydney.
- FPH.NZ dividendo: 1701723600 = 2023-12-04 21:00 UTC = 2023-12-05 10:00 Auckland.
- AAPL dividendo:   1715347800 = 2024-05-10 13:30 UTC = 2024-05-10 09:30 NY.
Con .date() en UTC, ASX y NZX caian un dia antes.
"""

import asyncio
from datetime import date

import pytest
from sqlalchemy import select

from app.models import DividendRecord
from app.services.connectors.yahoo import YahooFinanceClient
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.split_ingestion_service import SplitIngestionService
from tests.test_dividend_ingestion import _company, db  # noqa: F401


def _yahoo(tz: str | None, *, dividends=None, splits=None) -> YahooFinanceClient:
    client = YahooFinanceClient()
    meta = {"currency": "AUD"}
    if tz is not None:
        meta["exchangeTimezoneName"] = tz

    async def fake_chart(ticker, **kwargs):
        return {"meta": meta, "events": {"dividends": dividends or {}, "splits": splits or {}}}

    client._chart = fake_chart  # type: ignore[method-assign]
    return client


class _NoFMP:
    async def splits(self, ticker):  # pragma: no cover - Yahoo responde
        raise AssertionError("FMP no debe usarse")

    dividends = splits


def _dividend_rows(yahoo):
    service = DividendIngestionService(fmp=_NoFMP(), yahoo=yahoo)
    service._provider_symbol = lambda company: "X"  # type: ignore[method-assign]
    rows, source = asyncio.run(service._fetch_provider_rows(object()))
    assert source == "yahoo_finance"
    return rows


@pytest.mark.parametrize(
    ("tz", "epoch", "expected"),
    [
        ("Australia/Sydney", 1709766000, date(2024, 3, 7)),  # BHP.AX
        ("Pacific/Auckland", 1701723600, date(2023, 12, 5)),  # FPH.NZ
        ("Asia/Tokyo", 1711584000, date(2024, 3, 28)),  # 7203.T 09:00 JST
        ("America/New_York", 1715347800, date(2024, 5, 10)),  # AAPL
    ],
)
def test_dividend_ex_date_is_exchange_local(tz, epoch, expected):
    yahoo = _yahoo(tz, dividends={str(epoch): {"date": epoch, "amount": 0.72}})
    rows = _dividend_rows(yahoo)
    assert [row["ex_date"] for row in rows] == [expected]


def test_split_effective_date_is_exchange_local():
    epoch = 1709766000  # 2024-03-07 10:00 Sydney
    yahoo = _yahoo(
        "Australia/Sydney",
        splits={str(epoch): {"date": epoch, "numerator": 2, "denominator": 1, "splitRatio": "2:1"}},
    )
    service = SplitIngestionService(fmp=_NoFMP(), yahoo=yahoo)
    service._provider_symbol = lambda company: "X"  # type: ignore[method-assign]
    rows, _ = asyncio.run(service._fetch_rows(object()))
    assert [row["effective_date"] for row in rows] == [date(2024, 3, 7)]


@pytest.mark.parametrize("tz", [None, "", "Not/AZone"])
def test_unknown_timezone_falls_back_to_utc(tz):
    yahoo = _yahoo(tz, dividends={"1": {"date": 1715347800, "amount": 0.25}})
    assert [row["ex_date"] for row in _dividend_rows(yahoo)] == [date(2024, 5, 10)]


def test_resync_moves_utc_dated_row_instead_of_duplicating(db):  # noqa: F811
    """Una fila ASX guardada antes con la fecha UTC (6-mar) se corrige al 7-mar."""
    company = _company(db, ticker="BHP", currency="AUD")
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date(2024, 3, 6),
            pay_date=None,
            amount=0.72,
            currency="AUD",
            source="yahoo_finance",
        )
    )
    db.commit()
    yahoo = _yahoo("Australia/Sydney", dividends={"1": {"date": 1709766000, "amount": 0.72}})
    service = DividendIngestionService(fmp=_NoFMP(), yahoo=yahoo)
    service._provider_symbol = lambda company: "BHP.AX"  # type: ignore[method-assign]
    result = asyncio.run(service.sync_company(db, ticker="BHP"))
    assert result["inserted"] == 0, result
    dates = db.scalars(select(DividendRecord.ex_date).where(DividendRecord.company_id == company.id)).all()
    assert dates == [date(2024, 3, 7)]
