"""Direct thesis API serialization must not promote an unknown archived ratio."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import ThesisVersion
from app.schemas import ThesisOut


def thesis(convention=None, margin=Decimal('-0.649')):
    return ThesisVersion(
        id=1, company_id=1, version=11, status='published', rating='expensive',
        thesis_markdown='Original -64,9 %', executive_summary='Original -64,9 %',
        current_price=Decimal('343.46'), expected_value=Decimal('120.53'),
        margin_of_safety=margin, valuation_basis={'margin_of_safety_convention': convention},
        data_confidence_score=80, source_coverage_score=80, red_team_score=80,
        valuation_risk_score=80, created_at=datetime(2026, 10, 19, tzinfo=UTC),
    )


@pytest.mark.parametrize('convention', [None, 'valuation-engines-v2', 'future_formula'])
def test_unknown_margin_retained_as_archive_only_through_double_serialization(convention):
    row = thesis(convention)
    out = ThesisOut.model_validate(row)
    for payload in (out, ThesisOut.model_validate(out.model_dump())):
        assert payload.margin_of_safety is None
        assert payload.archived_margin_of_safety == Decimal('-0.649')
        assert payload.margin_of_safety_status == 'unknown_convention'
        assert payload.thesis_markdown == 'Original -64,9 %'
    assert row.margin_of_safety == Decimal('-0.649')


def test_explicit_formula_keeps_current_margin():
    out = ThesisOut.model_validate(thesis('discount_to_value_v1', Decimal('-1.849581')))
    assert out.margin_of_safety == out.archived_margin_of_safety == Decimal('-1.849581')
    assert out.margin_of_safety_status == 'verified'


def test_missing_margin_stays_missing():
    out = ThesisOut.model_validate(thesis(margin=None))
    assert out.margin_of_safety is out.archived_margin_of_safety is None
    assert out.margin_of_safety_status == 'missing'


def test_inferred_valuation_does_not_reappear_via_archive():
    row = thesis('discount_to_value_v1')
    row.valuation_basis = {
        **row.valuation_basis,
        'inferred_inputs_used': [{'input_key': 'fcf_margin', 'value': 0.3}],
    }
    out = ThesisOut.model_validate(row)
    assert out.margin_of_safety is out.archived_margin_of_safety is None
    assert out.margin_of_safety_status == 'withheld'
