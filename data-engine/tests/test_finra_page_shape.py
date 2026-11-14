"""Malformed FINRA page members degrade before being marked healthy."""
import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import short_interest as si


@pytest.mark.parametrize('rows', [[None], [1], ['bad'], [{'symbolCode': 'EXAMPLE'}, None], [True], [[]]])
def test_malformed_members_return_unknown_without_exception(monkeypatch, rows):
    registry = MagicMock()
    monkeypatch.setattr(si, 'get_data_source_registry', lambda: registry)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
            return await si.fetch_short_interest('EXAMPLE', client=client, max_requests=1)

    assert asyncio.run(run()) is None
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()


@pytest.mark.parametrize('rows', [[], [{'symbolCode': 'EXAMPLE'}]])
def test_valid_pages_preserve_success_and_rows(monkeypatch, rows):
    registry = MagicMock()
    monkeypatch.setattr(si, 'get_data_source_registry', lambda: registry)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
            return await si._short_interest_page(0, 200, client)

    assert asyncio.run(run()) == rows
    registry.record_success.assert_called_once_with(si.REGISTRY_KEY)
    registry.record_failure.assert_not_called()


def test_refresh_keeps_valid_daily_volume_when_interest_page_is_malformed(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base, Company, ConnectorState, Tenant
    from app.services.short_positions_service import refresh_shorts

    day = datetime.now(UTC).date()
    daily = si.REGSHO_DAILY_HEADER
    text = '|'.join(daily) + '\n' + f'{day:%Y%m%d}|EXAMPLE|10|0|100|Q\n'
    registry = MagicMock()
    monkeypatch.setattr(si, 'get_data_source_registry', lambda: registry)
    real_client = httpx.AsyncClient

    def handler(request):
        if request.url.host == 'cdn.finra.org':
            return httpx.Response(200, text=text)
        return httpx.Response(200, json=[None])

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    engine = create_engine(f'sqlite:///{tmp_path}/shorts.db')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id='owner'))
        db.commit()
        db.info['tenant_id'] = 1
        company = Company(ticker='EXAMPLE', name='Example', exchange='NASDAQ', company_type='compounders', valuation_model='dcf')
        db.add(company)
        db.commit()
        result = asyncio.run(refresh_shorts(db, company))
        assert result['status'] == 'available'
        assert result['data']['short_volume'] == 10
        assert result['data']['total_volume'] == 100
        assert result['data']['short_interest'] is None
        state = db.query(ConnectorState).filter_by(company_id=company.id, connector='public_shorts').one()
        assert state.last_success_at is not None
        assert state.consecutive_errors == 0
        assert state.last_error is None
    engine.dispose()
    registry.record_failure.assert_called()
