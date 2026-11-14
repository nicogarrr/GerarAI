"""Una fila no objeto no debe romper ni aparentar calendario completo."""
import asyncio

import pytest

from app.services.company_events_service import CompanyEventsService
from tests.test_company_events_service import _company, _future_row, db  # noqa: F401


@pytest.mark.parametrize("bad", [None, "fila ilegible", 0, []])
def test_calendario_conserva_filas_validas_y_declara_parcial(db, bad):  # noqa: F811
    company = _company(db)
    row = _future_row()

    async def calendar(*_):
        return {"earningsCalendar": [row, bad]}

    async def eps(*_):
        return []

    out = asyncio.run(CompanyEventsService(db, calendar_fetcher=calendar, eps_history_fetcher=eps).get_events(company))
    assert out["next_event"]["date"] == row["date"]
    assert out["calendar_status"] == "partial"
    assert "parcial" in out["note"]


def test_calendario_solo_filas_ilegibles_no_es_vacio_verificado(db):  # noqa: F811
    company = _company(db)

    async def calendar(*_):
        return {"earningsCalendar": [None]}

    async def eps(*_):
        return []

    out = asyncio.run(CompanyEventsService(db, calendar_fetcher=calendar, eps_history_fetcher=eps).get_events(company))
    assert out["calendar_status"] == "unavailable"
    assert out["next_event"] is None
