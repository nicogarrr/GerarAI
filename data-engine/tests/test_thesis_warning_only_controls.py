"""Consensus and inventory diagnostics never add a new publication veto."""
from types import SimpleNamespace

import pytest

from app.services import thesis_consensus_service as consensus
from app.services.thesis_service import ThesisService, _apply_value_driver_warning
from app.valuation.consensus_context import AnalystInputs, ConsensusSnapshot


@pytest.mark.parametrize('publishable', [True, False])
def test_consensus_warning_preserves_engine_decision(monkeypatch, publishable):
    snapshot = ConsensusSnapshot(symbol='SYNTH', status='available', mean=50,
        median=50, low=40, high=60, currency='USD', source='fixture',
        source_url='https://example.com/consensus')
    monkeypatch.setattr(consensus, 'load_consensus', lambda db, company: snapshot)
    monkeypatch.setattr(consensus, 'analyst_inputs_for_dcf', lambda db, company: AnalystInputs())
    blockers = [] if publishable else ['missing_financial_input']
    valuation = {'base_value': 100, 'expected_value': 110, 'current_price': 80,
        'currency': 'USD', 'publishable': publishable, 'publication_blockers': blockers.copy(),
        'trace': {'engine': 'standard_dcf', 'publishable': publishable}}
    result = consensus.apply_consensus_control(SimpleNamespace(info={'tenant_id': 1}),
        SimpleNamespace(ticker='SYNTH', id=1), valuation, enabled=True, block_publication=False)
    assert result['status'] == 'revisar'
    assert result['block_publication'] is False
    assert valuation['publishable'] is publishable
    assert valuation['publication_blockers'] == blockers
    assert valuation['base_value'] == 100 and valuation['expected_value'] == 110
    assert valuation['trace']['publishable'] is publishable
    markdown = ThesisService()._consensus_markdown(result)
    assert 'no bloquea' in markdown
    assert 'No publicable' not in markdown


@pytest.mark.parametrize('status', ['blocked', 'error'])
@pytest.mark.parametrize('publishable', [True, False])
def test_inventory_warning_preserves_values_and_existing_blockers(status, publishable):
    blockers = [] if publishable else ['missing_financial_input']
    valuation = {'publishable': publishable, 'base_value': 100,
        'publication_blockers': blockers.copy(), 'trace': {'publishable': publishable}}
    check = {'status': status, 'publishable': False, 'blocker': 'inventory_review',
        'reason': 'fixture warning', 'drivers': [], 'blocking': []}
    _apply_value_driver_warning(valuation, check)
    _apply_value_driver_warning(valuation, check)
    assert valuation['publishable'] is publishable
    assert valuation['base_value'] == 100
    assert valuation['publication_blockers'] == blockers
    assert valuation['trace']['publishable'] is publishable
    assert valuation['publication_warnings'] == ['inventory_review']
    assert check['block_publication'] is False
    markdown = ThesisService()._value_drivers_markdown(check)
    assert 'Aviso (sin veto de publicación)' in markdown
    assert 'fixture warning' in markdown
    assert 'Publicación bloqueada' not in markdown
