import pytest

from app.services.thesis_service import ThesisService
from app.services.tracked_evidence import tracked_evidence


@pytest.mark.parametrize(('receipt', 'expected'), [
    ({'status':'ok', 'facts_imported':24}, 'ok'),
    ({'status':'skipped', 'reason':'actualizado_ultimas_24h'}, 'ok'),
    ({'status':'skipped', 'reason':'emisor_no_sec'}, 'pending'),
    ({'status':'error', 'reason':'sec_no_disponible'}, 'pending'),
    ({'status':'error', 'reason':'sin_hechos_financieros'}, 'pending'),
])
def test_sec_attempt_is_not_described_as_never_attempted(receipt, expected):
    evidence = tracked_evidence(receipt)
    block = evidence['sources']['fundamentals']
    assert block['status'] == expected
    markdown = ThesisService()._sources_markdown(evidence['sources'])
    fundamentals_line = next(line for line in markdown.splitlines() if line.startswith('- Fundamentales:'))
    assert 'no intentado' not in fundamentals_line
    assert 'None' not in fundamentals_line
    assert '24 hechos' not in fundamentals_line  # imported count is not total verified history


def test_missing_receipt_makes_no_claim():
    assert tracked_evidence(None) == {}
