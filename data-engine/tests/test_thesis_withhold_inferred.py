from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.schemas.api import ThesisOut, valuation_uses_inferred_inputs
from app.services.thesis_approval_service import _assert_approvable


class Row:
    def __init__(self, basis):
        self.id = 1
        self.company_id = 1
        self.version = 3
        self.status = "published"
        self.thesis_markdown = "ASTS 1.95 vs 40.66"
        self.executive_summary = "margen -95%"
        self.rating = "expensive"
        self.current_price = Decimal("40.66")
        self.bear_value = Decimal("0.79")
        self.base_value = Decimal("1.83")
        self.bull_value = Decimal("3.21")
        self.expected_value = Decimal("1.95")
        self.margin_of_safety = Decimal("-0.95")
        self.data_confidence_score = 50
        self.source_coverage_score = 50
        self.red_team_score = 50
        self.valuation_risk_score = 50
        self.input_fingerprint = None
        self.hypothesis = None
        self.catalysts = None
        self.invalidation_criteria = None
        self.scenario_probabilities = None
        self.narrative_sections = None
        self.valuation_basis = basis
        self.created_at = datetime.now(UTC)


INFERRED = {"inferred_inputs_used": [{"input_key": "fcf_margin", "value": 0.25}]}


def test_inferred_basis_withholds_per_share_values():
    out = ThesisOut.model_validate(Row(INFERRED))
    assert out.expected_value is None and out.base_value is None
    assert out.bear_value is None and out.bull_value is None
    assert out.margin_of_safety is None
    assert out.rating == "insufficient_data"
    assert "faltan ingresos modelados" in out.valuation_withheld_reason
    assert "INFERIDO" not in out.executive_summary
    assert "1.95" not in out.thesis_markdown


@pytest.mark.parametrize("basis", [None, {}, {"inferred_inputs_used": []}])
def test_normal_basis_keeps_values(basis):
    out = ThesisOut.model_validate(Row(basis))
    assert out.expected_value == Decimal("1.95")
    assert out.valuation_withheld_reason is None
    assert not valuation_uses_inferred_inputs(basis)


def test_cannot_publish_inferred_thesis():
    with pytest.raises(ValueError, match="inferidos"):
        _assert_approvable(None, Row(INFERRED))
