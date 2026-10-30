"""Un split 1:1 (marcador de spin-off) no es una agrupación de acciones."""

import asyncio
from datetime import date

from sqlalchemy import select

from app.models import CorporateAction
from app.services.split_ingestion_service import SplitIngestionService
from tests.test_dividend_ingestion import _company, db  # noqa: F401


class _Yahoo:
    def __init__(self, rows):
        self.rows = rows

    async def splits(self, ticker):
        return self.rows


class _NoFMP:
    async def splits(self, ticker):  # pragma: no cover - Yahoo responde
        raise AssertionError("FMP no debe usarse")


def _sync(db, rows):  # noqa: F811
    service = SplitIngestionService(fmp=_NoFMP(), yahoo=_Yahoo(rows))
    service._provider_symbol = lambda company: "X"  # type: ignore[method-assign]
    return asyncio.run(service.sync_company(db, ticker="GE"))


def test_one_for_one_marker_is_not_stored_as_reverse_split(db):  # noqa: F811
    company = _company(db, ticker="GE")
    rows = [
        # 2-abr-2024: spin-off de GE Vernova, Yahoo lo marca 1:1.
        {"date": 1712064600, "numerator": 1, "denominator": 1, "splitRatio": "1:1"},
        # 2-ago-2021: agrupación real 1 por 8.
        {"date": 1627911000, "numerator": 1, "denominator": 8, "splitRatio": "1:8"},
    ]
    result = _sync(db, rows)
    assert result["inserted"] == 1, result
    assert result["skipped"] == {"ratio_1_no_split": 1}
    stored = db.scalars(select(CorporateAction).where(CorporateAction.company_id == company.id)).all()
    assert [(a.action_type, a.effective_date, float(a.ratio)) for a in stored] == [
        ("reverse_split", date(2021, 8, 2), 0.125)
    ]
    assert all("1 por 1." not in (a.description or "") for a in stored)
