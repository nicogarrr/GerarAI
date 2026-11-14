"""Misaligned SEC columns cannot prove a complete filing history."""
import asyncio
from datetime import date

import pytest

from app.services import catalyst_calendar_service as service


def payload(forms, reports):
    return {'category': 'Large accelerated filer', 'fiscalYearEnd': '1231',
            'filings': {'recent': {'form': forms, 'reportDate': reports}}}


@pytest.mark.parametrize('forms,reports', [
    (['10-Q', '10-Q'], ['2026-06-30']),
    (['10-Q'], ['2026-03-31', '2026-06-30']),
    (['10-Q'], []), ([], ['2026-06-30']),
])
def test_misaligned_columns_surface_as_unavailable(monkeypatch, forms, reports):
    monkeypatch.setattr(service, '_FAILED_UNTIL', {})
    async def cik(ticker):
        return '123'
    async def submissions(cik):
        return payload(forms, reports)
    result = asyncio.run(service.fetch_filing_deadlines(
        {'TEST'}, date(2026, 1, 1), date(2027, 12, 31),
        cik_fetcher=cik, submissions_fetcher=submissions,
    ))
    assert result['status'] == 'unavailable'
    assert result['events'] == []
    assert result['errors'] == ['Plazos 10-Q/10-K: EDGAR no disponible para TEST']


def test_aligned_columns_match_parent_result():
    # Measured against parent 88546b2 before adding the alignment guard.
    result = service.filing_deadline_event(payload(['10-Q'], ['2026-06-30']), 'TEST')
    assert result == {
        'date': '2026-11-09', 'ticker': 'TEST', 'type': 'filing_deadline',
        'title': 'Plazo para presentar el 10-Q',
        'detail': '40 días tras el cierre de periodo estimado (30 sept 2026) sobre el último informe periódico (cierre 30 jun 2026); categoría EDGAR: emisor acelerado grande',
        'source': 'Regla SEC (Form 10-Q/10-K) aplicada al último informe en EDGAR',
    }


def test_both_empty_columns_preserve_no_deadline():
    assert service.filing_deadline_event(payload([], []), 'TEST') is None
