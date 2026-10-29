"""Tipo de convenio verificado para Hong Kong (10 %).

España-Hong Kong 2011, BOE-A-2012-5039, art. 10.2.b: el impuesto en origen no
puede exceder del 10 % del importe bruto en todos los demás casos (el 0 % del
art. 10.2.a exige sociedad con al menos el 25 % del capital, no una persona
física minorista).

Cálculo a mano:
  Dividendo 200,00 €, retenido 20,00 € (10 %) → tope 200 × 10 % = 20,00 €
  acreditable; con TME del ahorro 19 % la cuota española es 38,00 € → deducción
  0588 = min(20, 38) = 20,00 €.
  Dividendo 300,00 €, retenido 0 → nada que deducir, y NO va a revisión
  manual (antes, sin tipo de convenio, todo el país iba a revisión).
"""

from decimal import Decimal

from app.services.tax_irpf_filing import (
    TREATY_DIVIDEND_RATES,
    TREATY_RATE_SOURCES,
    build_double_taxation,
)


def _div(ticker, gross, withheld):
    return {
        "ticker": ticker,
        "dividends_base": gross,
        "withholding_base": withheld,
        "missing_fx": False,
        "payments": [],
    }


def test_hong_kong_tope_10_por_ciento_y_deduccion_con_tme():
    result = build_double_taxation([_div("HKX", 200.0, 20.0)], {"HKX": "HK"}, 2026, tme=Decimal("0.19"))
    (hk,) = result["countries"]
    assert hk["treaty_cap_base"] == 20.0
    assert hk["deduction_base"] == 20.0
    assert hk["treaty_rate_source"].startswith("BOE-A-2012-5039")
    assert result["manual_review"] == []
    assert result["total_deduction_base"] == 20.0


def test_hong_kong_sin_retencion_no_va_a_revision_manual():
    result = build_double_taxation(
        [_div("HKY1", 300.0, 0.0), {"HKX": "HK"} and _div("HKX", 200.0, 20.0)],
        {"HKY1": "HK", "HKX": "HK"},
        2026,
        tme=Decimal("0.19"),
    )
    assert result["manual_review"] == []
    assert result["partial"] is False
    assert result["total_deduction_base"] == 20.0


def test_hong_kong_exceso_sobre_el_10_por_ciento_es_reclamable_en_origen():
    result = build_double_taxation([_div("HKZ1", 100.0, 30.0)], {"HKZ1": "HK"}, 2026, tme=Decimal("0.19"))
    (hk,) = result["countries"]
    assert hk["treaty_cap_base"] == 10.0
    assert hk["excess_reclaimable_base"] == 20.0
    assert hk["deduction_base"] == 10.0


def test_hong_kong_tipo_y_cita_boe():
    assert TREATY_DIVIDEND_RATES["HK"] == Decimal("0.10")
    assert "BOE-A-2012-5039" in TREATY_RATE_SOURCES["HK"]
