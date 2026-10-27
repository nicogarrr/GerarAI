"""F394: valuation API exposes the share basis; theses persist their own basis."""

from app.schemas import ThesisOut, ValuationResponse
from app.services.thesis_service import ThesisService


def test_valuation_response_keeps_listed_share_values():
    payload = {
        "ticker": "ADRA", "model_type": "standard_dcf", "adr_ratio": 8.0,
        "value_per_share_basis": "ordinary_share",
        "listed_share_values": {"bear": 8.0, "base": 256.3, "bull": 400.0, "expected": 250.0},
    }
    out = ValuationResponse(**payload).model_dump()
    assert out["adr_ratio"] == 8.0
    assert out["value_per_share_basis"] == "ordinary_share"
    assert out["listed_share_values"]["base"] == 256.3


def test_valuation_response_defaults_for_non_adr():
    out = ValuationResponse(ticker="X", model_type="m").model_dump()
    assert out["adr_ratio"] is None and out["listed_share_values"] is None


def test_thesis_persists_its_own_basis_not_a_later_valuation():
    valuation = {
        "value_per_share_basis": "ordinary_share", "adr_ratio": 8.0,
        "listed_share_values": {"base": 256.3, "bear": 100.0, "bull": 400, "expected": None},
    }
    basis = ThesisService._valuation_basis(valuation)
    assert basis == {
        "value_per_share_basis": "ordinary_share", "adr_ratio": 8.0,
        "listed_share_values": {"base": 256.3, "bear": 100.0, "bull": 400.0},
    }


def test_no_basis_evidence_gives_none():
    assert ThesisService._valuation_basis({"base_value": 1}) is None
    assert ThesisService._valuation_basis({"value_per_share_basis": "ordinary_share"})[
        "listed_share_values"
    ] is None


def test_thesis_out_exposes_valuation_basis():
    assert "valuation_basis" in ThesisOut.model_fields

def test_basis_stores_fingerprint_of_the_model_used_not_latest():
    """La liga modelo-tesis guarda el fingerprint del modelo QUE GENERO esta
    tesis (long_term_model.persistence), nunca el ultimo modelo persistido."""
    valuation = {
        "value_per_share_basis": "ordinary_share",
        "long_term_model": {"persistence": {"input_fingerprint": "fp-modelo-usado-v3"}},
    }
    basis = ThesisService._valuation_basis(valuation)
    assert basis["model_input_fingerprint"] == "fp-modelo-usado-v3"


def test_basis_omits_fingerprint_key_without_model():
    """Sin modelo ligado la clave no aparece (contrato sin ruido)."""
    basis = ThesisService._valuation_basis({"value_per_share_basis": "ordinary_share"})
    assert "model_input_fingerprint" not in basis


def test_margin_convention_survives_without_share_basis():
    from app.valuation.margin_convention import MARGIN_OF_SAFETY_CONVENTION

    basis = ThesisService._valuation_basis({
        "trace": {"margin_of_safety_convention": MARGIN_OF_SAFETY_CONVENTION},
    })
    assert basis["margin_of_safety_convention"] == MARGIN_OF_SAFETY_CONVENTION
    assert basis["value_per_share_basis"] is None


def test_model_version_alone_does_not_establish_margin_convention():
    assert ThesisService._valuation_basis({
        "trace": {"model_version": "valuation-engines-v2"},
    }) is None
