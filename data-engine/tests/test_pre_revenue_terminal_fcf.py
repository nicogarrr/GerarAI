"""Un camino causal invalido no borra los validos ni inventa una media."""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from scripts.run_valuation_evals import _value_case


def test_pre_revenue_bear_sin_terminal_positivo_conserva_base_bull():
    dataset = json.loads((Path(__file__).parents[1] / 'evals/valuation/valuation_engines_v1.json').read_text())
    case = next(c for c in dataset['cases'] if c['id'] == 'evpre05_funding_gap_dilutes_a_positive_value')
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            enriched = _value_case(db, case)
            result = enriched['artifact']
            assert result['status'] == 'partial'
            assert result['publishable'] is False
            assert result['bear_value'] is None
            assert result['expected_value'] is None
            assert result['base_value'] == pytest.approx(2.862800104)
            assert result['bull_value'] == pytest.approx(12.26968216)
            assert 'FCF terminal no positivo' in result['scenario_notes']['expected']
            assert result['trace']['weighted'] == {'reason': 'positive_terminal_fcf', 'complete': False}
            invalid = [s for s in result['trace']['scenarios'].values() if s['value_per_share'] is None]
            assert len(invalid) == 1
            assert invalid[0]['trace']['missing_inputs'] == ['positive_terminal_fcf']
    finally:
        engine.dispose()


@pytest.mark.parametrize('tenant', [None, '1', 0, -1, {}])
def test_objetivo_declarado_requiere_tenant_entero_positivo(tenant):
    from types import SimpleNamespace

    from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine

    context = SimpleNamespace(db=SimpleNamespace(info={'tenant_id': tenant}),
                              company=SimpleNamespace(id=42))
    assert PreRevenueScenarioEngine()._declared_margin_target(context) is None


@pytest.mark.parametrize('change,want', [
    ({}, .2), ({'unit': '%', 'base': 20}, .2),
    ({'unit': 'decimal', 'base': 20}, .2),
    ({'base': 0}, None), ({'base': -.1}, None),
    ({'method': 'reported'}, None), ({'as_of': 'future'}, None),
    ({'id': None, 'analyst_firm': '', 'unit': 'percent', 'base': 15}, .15),
])
def test_objetivo_declarado_valida_fecha_unidad_y_positividad(monkeypatch, change, want):
    from datetime import date
    from types import SimpleNamespace

    from app.services.declared_input_service import DeclaredInputService
    from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine

    values = dict(id=7, method='analyst', base=.2, unit='decimal',
                  analyst_firm='Firma', source_url='https://example.com/source',
                  as_of=date(2026, 1, 1))
    values.update(change)
    if values['as_of'] == 'future':
        values['as_of'] = date(2027, 1, 1)
    row = SimpleNamespace(**values)
    monkeypatch.setattr(DeclaredInputService, 'current', lambda *args, **kw: {('fcf_margin', ''): row})
    monkeypatch.setattr(DeclaredInputService, 'row_is_valid', lambda *args: True)
    context = SimpleNamespace(db=SimpleNamespace(info={'tenant_id': 1}),
                              company=SimpleNamespace(id=42), as_of=date(2026, 6, 1))
    result = PreRevenueScenarioEngine()._declared_margin_target(context)
    if want is None:
        assert result is None
    else:
        assert result.value == pytest.approx(want)
        assert result.id == (-7 if row.id else -1)
        assert result.source_urls == ['https://example.com/source']


@pytest.mark.parametrize('mode', ['missing', 'invalid', 'error'])
def test_objetivo_declarado_fallback_acotado(monkeypatch, mode, caplog):
    from types import SimpleNamespace

    from app.services.declared_input_service import DeclaredInputService
    from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine

    def current(*args, **kwargs):
        if mode == 'error':
            raise ValueError('texto privado')
        return {} if mode == 'missing' else {('fcf_margin', ''): SimpleNamespace(method='analyst')}
    monkeypatch.setattr(DeclaredInputService, 'current', current)
    monkeypatch.setattr(DeclaredInputService, 'row_is_valid', lambda *args: False)
    context = SimpleNamespace(db=SimpleNamespace(info={'tenant_id': 1}),
                              company=SimpleNamespace(id=42), as_of=None)
    assert PreRevenueScenarioEngine()._declared_margin_target(context) is None
    assert 'texto privado' not in caplog.text
