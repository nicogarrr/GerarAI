"""Una tesis recién generada no sale como «Tesis archivada» (fallo #3).

La puerta de #2495/#2497/#2498 sigue protegiendo las cifras que se declaran
publicables (estado published/final); un borrador vigente se etiqueta solo.
"""
from decimal import Decimal

from app.models import FundamentalModelVersion, ThesisVersion
from app.services.thesis_publication_gate import model_withheld_reason


def _thesis(status, *, fingerprint=None, expected=None, inferred=False):
    basis = {}
    if fingerprint:
        basis["model_input_fingerprint"] = fingerprint
    if inferred:
        basis["inferred_inputs_used"] = [{"input_key": "revenue"}]
    return ThesisVersion(company_id=1, version=1, status=status, thesis_markdown="t",
                         executive_summary="s", expected_value=expected, valuation_basis=basis or None)


def _model(*, publishable, fingerprint="fp-1"):
    return FundamentalModelVersion(company_id=1, version=1, engine_version="t", algorithm_version="t",
                                   framework_key="dcf", horizon_years=10, status="ok", publishable=publishable,
                                   input_fingerprint=fingerprint, forecast_fingerprint="f",
                                   market_snapshot_fingerprint="m", valuation_snapshot_fingerprint="v")


def test_fresh_insufficient_data_thesis_without_model_is_not_archived():
    assert model_withheld_reason(_thesis("insufficient_data"), None) is None


def test_fresh_indicative_draft_without_model_is_not_archived():
    assert model_withheld_reason(_thesis("draft", expected=Decimal("0.46")), None) is None


def test_draft_built_from_latest_unpublishable_model_is_current():
    thesis = _thesis("draft", fingerprint="fp-1", expected=Decimal("10"))
    assert model_withheld_reason(thesis, _model(publishable=False, fingerprint="fp-1")) is None


def test_draft_superseded_by_newer_model_is_still_archived():
    thesis = _thesis("draft", fingerprint="fp-old", expected=Decimal("10"))
    assert model_withheld_reason(thesis, _model(publishable=False, fingerprint="fp-new"))


def test_draft_without_model_link_and_a_model_present_is_still_archived():
    assert model_withheld_reason(_thesis("draft"), _model(publishable=False))


def test_published_or_final_figures_still_need_a_publishable_model():
    for status in ("published", "final"):
        assert model_withheld_reason(_thesis(status, expected=Decimal("119.92")), None)
        linked = _thesis(status, fingerprint="fp-1", expected=Decimal("119.92"))
        assert model_withheld_reason(linked, _model(publishable=False, fingerprint="fp-1"))
        assert model_withheld_reason(linked, _model(publishable=True, fingerprint="fp-1")) is None


def test_current_draft_with_inferred_inputs_stays_withheld():
    assert model_withheld_reason(_thesis("draft", inferred=True), None)
