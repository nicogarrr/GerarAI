"""Contadores deterministas: normalizar EntityFacts una vez, sin cambiar resultados."""
from types import SimpleNamespace

import pytest

from app.services.connectors.edgartools_facts import facts_from_edgartools_entity


def _fact(concept="Revenues", **kw):
    return {"concept": concept, "period_end": "2024-12-31", "value": 10,
            "filing_date": "2025-02-01", "form_type": "10-K", "fiscal_period": "FY",
            "unit": "USD", **kw}


class CountedEntity:
    def __init__(self, facts):
        self.facts = facts
        self.loads = 0
        self.visits = 0

    def get_all_facts(self):
        self.loads += 1
        for fact in self.facts:
            self.visits += 1
            yield fact


@pytest.mark.parametrize("bank_like", [False, True])
def test_one_load_one_visit_per_fact(bank_like):
    raw = [_fact()] + [_fact("NotMapped") for _ in range(9_999)]
    counted = CountedEntity(raw)
    result = facts_from_edgartools_entity(counted, bank_like=bank_like)
    assert counted.loads == 1
    assert counted.visits == len(raw)
    assert result == facts_from_edgartools_entity([raw[0]], bank_like=bank_like)
    assert len(result[0]) == 1


def test_single_use_iterable_preserves_all_metrics_and_periods():
    raw = [_fact(), _fact("Assets"), _fact("NetIncomeLoss", value=4),
           _fact("Revenues", value=2, period_end="2024-09-30", form_type="10-Q", fiscal_period="Q3"),
           _fact("Revenues", value=12, filing_date="2025-03-01")]
    expected = facts_from_edgartools_entity(raw)
    assert facts_from_edgartools_entity(iter(raw)) == expected
    assert {f["metric"] for f in expected[0]} >= {"revenue", "total_assets", "net_income"}
    assert any(f["period"].endswith(":Q3") for f in expected[0])
    assert any(f["value"] == 12 for f in expected[0] if f["metric"] == "revenue")


def test_normalized_index_is_per_call_no_stale_filer_state():
    one = facts_from_edgartools_entity([_fact(value=10)])
    two = facts_from_edgartools_entity([_fact(value=20)])
    assert one != two
    assert facts_from_edgartools_entity([]) == ([], {})


def test_dict_and_object_facts_and_annual_anchor_are_preserved():
    raw = [_fact(accn="valid"), SimpleNamespace(**_fact("Assets", accession="valid")),
           _fact("NetIncomeLoss", accession="unknown")]
    # accn is the normalized key, accession is the upstream EntityFacts field.
    raw[0]["accession"] = "valid"
    facts, usage = facts_from_edgartools_entity(raw, annual_anchors={"valid": "2024-12-31"})
    assert "net_income" not in usage
    assert {f["metric"] for f in facts} >= {"revenue", "total_assets"}
