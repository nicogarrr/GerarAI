"""An absent displayed bear is not a zero in the weighted valuation."""
from types import SimpleNamespace

from app.services.thesis_deep_narrative import fact_pack

NOTE = ('Escenario bajista: la deuda y las obligaciones superan el valor del negocio; '
        'el valor por acción es negativo y no publicable: N/D. '
        'El valor esperado sí lo tiene en cuenta.')


def _valuation(**overrides):
    return {'status': 'ok', 'publishable': True, 'bear_value': None,
            'expected_value': 100.0, 'scenario_notes': {'bear': NOTE}, **overrides}


def _texts(value):
    company = SimpleNamespace(ticker='UNH', currency='USD')
    return [f['texto'] for f in fact_pack(company, value, {}, None, [])]


def test_null_bear_note_reaches_redactor_without_becoming_zero():
    texts = _texts(_valuation())
    note = next(t for t in texts if NOTE in t)
    assert 'N/D' in note
    assert 'El valor esperado sí lo tiene en cuenta.' in note
    assert not any('bear): 0.00' in t for t in texts)


def test_note_is_not_used_for_a_present_bear():
    texts = _texts(_valuation(bear_value=25.0))
    assert any('bear): 25.00 USD' in t for t in texts)
    assert not any(NOTE in t for t in texts)


def test_null_without_reason_does_not_invent_negative_or_weight():
    texts = _texts(_valuation(scenario_notes={}))
    assert not any('negativ' in t or 'pesa' in t for t in texts)


def test_only_bear_note_not_unrelated_scenario_prose_is_added():
    texts = _texts(_valuation(scenario_notes={'bear': NOTE, 'bull': 'unrelated'}))
    assert any(NOTE in t for t in texts)
    assert not any('unrelated' in t for t in texts)


def test_blank_or_invalid_note_is_not_invented_or_stringified():
    for notes in [None, [], {'bear': ''}, {'bear': '  '}, {'bear': {'text': NOTE}}]:
        texts = _texts(_valuation(scenario_notes=notes))
        assert not any('bear) N/D.' in t for t in texts)
