"""Partial SEC columns cannot establish that no results filing exists."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.services import earnings_materials_service as svc
from tests.test_earnings_materials_service import INDEX_6K, FakeSEC


def resolve(sec):
    return asyncio.run(svc.resolve_materials(sec=sec, ticker='EXAMPLE', event_date=date(2026, 11, 13), fiscal_label='Sep/2026', confirmed=True))


@pytest.mark.parametrize('form', ['8-K', '6-K'])
@pytest.mark.parametrize('column', ['filingDate', 'accessionNumber'])
@pytest.mark.parametrize('values', [[], ['x', 'y']])
def test_required_columns_must_align(form, column, values):
    recent = {'form': [form], 'items': ['2.02'], 'filingDate': ['2026-11-13'], 'accessionNumber': ['0001-26-1']}
    recent[column] = values
    sec = FakeSEC({'filings': {'recent': recent}})
    sec.filing_document = AsyncMock(side_effect=AssertionError('must not fetch index'))
    result = resolve(sec)
    assert result['status'] == 'no_disponible'
    assert result['documents'] == []
    sec.filing_document.assert_not_called()


@pytest.mark.parametrize('items', [[], ['2.02', '9.01']])
def test_domestic_items_must_align(items):
    sec = FakeSEC({'filings': {'recent': {'form': ['8-K'], 'items': items, 'filingDate': ['2026-11-13'], 'accessionNumber': ['0001-26-1']}}})
    sec.filing_document = AsyncMock(side_effect=AssertionError('must not fetch index'))
    assert resolve(sec)['status'] == 'no_disponible'
    sec.filing_document.assert_not_called()


def test_empty_recent_preserves_absence():
    assert resolve(FakeSEC({'filings': {'recent': {}}}))['status'] == 'sin_filing'


@pytest.mark.parametrize('items', [None, [], ['unused', 'unused']])
def test_foreign_items_not_required_for_verified_documents(items):
    recent = {'form': ['6-K'], 'filingDate': ['2026-11-13'], 'accessionNumber': ['0001-26-1']}
    if items is not None:
        recent['items'] = items
    sec = FakeSEC({'filings': {'recent': recent}}, {'0001-26-1-index.htm': INDEX_6K, 'release.htm': 'PRESS RELEASE Results quarter ended September 30, 2026'})
    result = resolve(sec)
    assert result['status'] == 'ok'
    assert len(result['documents']) == 1
