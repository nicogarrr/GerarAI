"""Un cero comunicado no es ausencia del importe del dividendo."""
import asyncio
from datetime import date

import httpx
import pytest

from app.services.connectors import earnings_calendar as ec


@pytest.mark.parametrize('value', [0, 0.0, '0', '$0.00'])
def test_explicit_zero_is_not_replaced_by_alias(value):
    result = ec.normalize_dividend_row(
        {'symbol': 'ABC', 'dividend_Rate': value, 'amount': '9.5'}, date(2026, 11, 13)
    )
    assert result['amount'] == 0


@pytest.mark.parametrize('value', [None, ''])
def test_missing_rate_keeps_amount_alias(value):
    result = ec.normalize_dividend_row(
        {'symbol': 'ABC', 'dividend_Rate': value, 'amount': '1.5'}, date(2026, 11, 13)
    )
    assert result['amount'] == 1.5


def test_zero_without_alias_is_known_not_null():
    result = ec.normalize_dividend_row(
        {'symbol': 'ABC', 'dividend_Rate': 0}, date(2026, 11, 13)
    )
    assert result['amount'] == 0


def test_dividend_range_preserves_numeric_zero():
    async def probe():
        def handler(request):
            return httpx.Response(200, json={'data': {'calendar': {'rows': [
                {'symbol': 'ABC', 'dividend_Rate': 0, 'amount': '9.5'}
            ]}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ec.fetch_dividends_range(date(2026, 11, 13), date(2026, 11, 13), client)
    result = asyncio.run(probe())
    assert result['status'] == 'ok'
    assert result['events'][0]['amount'] == 0
