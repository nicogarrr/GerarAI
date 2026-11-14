"""A valid date column cannot authenticate the requested financial series."""
import asyncio

import httpx
import pytest
from sqlalchemy import func, select

from app.models.entities import Document, FinancialFact
from app.services import wacc_input_service
from app.services.connectors.fred import FREDClient
from app.services.data_source_health import get_data_source_registry
from app.services.wacc_input_service import WaccInputService
from tests.test_wacc_input_service import _company, _patch_no_yfinance, db  # noqa: F401


@pytest.mark.parametrize('header', [
    'observation_date,CPIAUCSL',
    'DATE,UNRATE',
    'observation_date',
    'observation_date,',
    'observation_date,DGS10,CPIAUCSL',
    'observation_date,DGS10,DGS10',
])
def test_wrong_or_ambiguous_series_header_is_not_success(header):
    registry = get_data_source_registry()
    before = registry.get_status('fred').consecutive_failures

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=header+'\n2026-11-12,321.25\n')
        )) as client:
            return await FREDClient(client).series_csv('DGS10')

    with pytest.raises(RuntimeError, match='cabecera esperada'):
        asyncio.run(run())
    assert registry.get_status('fred').consecutive_failures == before + 1


@pytest.mark.parametrize('header', ['observation_date,DGS10', 'DATE,DGS10', '\ufeff"observation_date","DGS10"'])
def test_requested_series_legacy_and_quoted_headers_remain_supported(header):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=header+'\n2026-11-12,4.25\n')
        )) as client:
            return await FREDClient(client).series_csv('DGS10')

    assert asyncio.run(run()) == {'observations': [{'date':'2026-11-12', 'value':'4.25'}]}


def test_wrong_series_cannot_be_persisted_as_a_usd_risk_free_fact(db, monkeypatch):
    """Exercise the real CSV reader and WACC writer, not a fake fact assertion."""
    _patch_no_yfinance(monkeypatch)
    company = _company(db)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text='observation_date,CPIAUCSL\n2026-11-12,321.25\n')
        )) as client:
            fred = FREDClient(client)
            monkeypatch.setattr(fred, 'configured', lambda: False)
            monkeypatch.setattr(wacc_input_service, 'FREDClient', lambda: fred)
            return await WaccInputService().refresh(db, company)

    with pytest.raises(RuntimeError, match='cabecera esperada'):
        asyncio.run(run())
    assert db.scalar(select(func.count()).select_from(FinancialFact).where(FinancialFact.metric == 'risk_free_rate')) == 0
    assert db.scalar(select(func.count()).select_from(Document).where(Document.source_type == 'FRED')) == 0
