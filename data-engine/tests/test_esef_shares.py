"""Contratos de la derivacion de acciones ESEF (app.services.esef_shares).

Via unica de acciones medias para emisores ESEF: medido 2026-10-29, 0/105
emisores ES etiquetan WeightedAverageNumberOf*Shares en base scope.
Revision del piloto (2026-10-29): shares_diluted SOLO desde BPA diluido;
el fallback basico vive en shares_basic_derived, metrica informativa que el
DCF no acepta sin equivalencia acreditada. Cifras y cotas de los casos
observadas en la medicion.
"""

from decimal import Decimal

from app.services.esef_shares import (
    BASIC_METRIC,
    DERIVATION_FORMULA,
    DILUTED_METRIC,
    derive_shares,
)


def _entry(val, decimals=2):
    return {"val": val, "decimals": decimals}


def test_happy_path_diluted_lane():
    # SAN FY2024: beneficio atribuido 12.574 M EUR, BPA diluido 0,71 EUR.
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("12574000000")},
        {"2024-12-31": _entry("0.71", 2)},
        {},
    )
    assert not skipped and not basic
    assert len(diluted) == 1
    d = diluted[0]
    assert d.lane == "diluted"
    assert d.period == "2024-12-31"
    assert d.shares == (Decimal("12574000000") / Decimal("0.71")).quantize(Decimal("1"))
    assert d.shares > 0
    assert d.rel_error_bound < Decimal("0.02")
    assert not d.numerator_adjustment_risk


def test_basic_fallback_goes_to_its_own_metric_lane():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000000")},
        {},
        {"2024-12-31": _entry("0.50", 2)},
    )
    assert not diluted and not skipped
    assert len(basic) == 1
    assert basic[0].lane == "basic"
    assert basic[0].shares == Decimal("2000000")
    # La via basica NUNCA escribe la metrica diluida.
    assert BASIC_METRIC != DILUTED_METRIC == "shares_diluted"


def test_period_with_diluted_never_uses_basic():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000000")},
        {"2024-12-31": _entry("0.50", 2)},
        {"2024-12-31": _entry("0.55", 2)},
    )
    assert len(diluted) == 1 and not basic
    assert diluted[0].eps == Decimal("0.50")


def test_differing_basic_flags_numerator_adjustment_risk():
    # Basico 0,80 vs diluido 0,71: diferencia muy por encima del redondeo;
    # posibles convertibles/preferentes en el numerador del diluido.
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("12574000000")},
        {"2024-12-31": _entry("0.71", 2)},
        {"2024-12-31": _entry("0.80", 2)},
    )
    assert diluted[0].numerator_adjustment_risk


def test_equal_basic_and_diluted_within_rounding_is_clean():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("12574000000")},
        {"2024-12-31": _entry("0.71", 2)},
        {"2024-12-31": _entry("0.72", 2)},
    )
    assert not diluted[0].numerator_adjustment_risk


def test_only_overlapping_periods_are_derived():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("100"), "2023-12-31": _entry("90")},
        {"2024-12-31": _entry("0.5", 2)},
        {},
    )
    assert [d.period for d in diluted] == ["2024-12-31"]
    assert skipped == []  # los periodos sin solape no se reportan aqui


def test_zero_eps_never_divides():
    # NYE: BPA 0,0 declarado en la medicion 2026-10-29.
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000")}, {"2024-12-31": _entry("0.0", 2)}, {}
    )
    assert not diluted
    assert [s.reason for s in skipped] == ["bpa_cero"]
    assert skipped[0].lane == "diluted"


def test_sign_mismatch_is_rejected():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000")}, {"2024-12-31": _entry("-0.5", 2)}, {}
    )
    assert not diluted
    assert [s.reason for s in skipped] == ["signo_incoherente_beneficio_bpa"]


def test_rounding_bound_over_two_percent_is_rejected():
    # SCYR: BPA 0,11 con 2 decimales -> cota 4,5 % (medido 2026-10-29).
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000000")}, {"2024-12-31": _entry("0.11", 2)}, {}
    )
    assert not diluted
    assert skipped[0].reason.startswith("redondeo_bpa_")


def test_rounding_bound_just_under_two_percent_passes():
    # BPA 0,26 con 2 decimales -> cota ~1,92 %.
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000000")}, {"2024-12-31": _entry("0.26", 2)}, {}
    )
    assert not skipped and len(diluted) == 1


def test_missing_and_inf_decimals_are_rejected():
    for bad in ({"val": "0.5", "decimals": None}, {"val": "0.5", "decimals": "INF"}):
        diluted, basic, skipped = derive_shares(
            {"2024-12-31": _entry("1000")}, {"2024-12-31": bad}, {}
        )
        assert not diluted
        assert [s.reason for s in skipped] == ["bpa_sin_decimals"]


def test_non_numeric_values_are_rejected():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("no-num")}, {"2024-12-31": _entry("0.5", 2)}, {}
    )
    assert not diluted
    assert [s.reason for s in skipped] == ["beneficio_atribuido_no_numerico"]
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000")}, {"2024-12-31": _entry(None, 2)}, {}
    )
    assert not diluted
    assert [s.reason for s in skipped] == ["bpa_no_numerico"]


def test_negative_profit_and_eps_gives_positive_shares():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("-500000")}, {"2024-12-31": _entry("-0.30", 2)}, {}
    )
    assert not skipped and diluted[0].shares > 0


def test_shares_quantized_to_whole_units():
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000000")}, {"2024-12-31": _entry("0.30", 2)}, {}
    )
    assert diluted[0].shares == diluted[0].shares.quantize(Decimal("1"))


def test_basic_lane_carries_same_guards():
    # El fallback basico pasa por las mismas guardas (aqui: redondeo).
    diluted, basic, skipped = derive_shares(
        {"2024-12-31": _entry("1000000")}, {}, {"2024-12-31": _entry("0.11", 2)}
    )
    assert not basic
    assert skipped[0].lane == "basic"


def test_formula_and_metric_names_declared():
    assert "ProfitLossAttributableToOwnersOfParent" in DERIVATION_FORMULA
    assert DILUTED_METRIC == "shares_diluted"
    assert BASIC_METRIC == "shares_basic_derived"
