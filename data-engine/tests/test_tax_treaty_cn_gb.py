"""Tipos de convenio verificados para China (10 %) y Reino Unido (10 %).

- España-China 2018, BOE-A-2021-4911, art. 10.2.b: el impuesto en origen no
  puede exceder del 10 % del importe bruto (persona física).
- España-Reino Unido 2013, BOE-A-2014-5171, art. 10.2.a.i: 10 % del bruto.

Cálculo a mano:
  Dividendo chino 200,00 €, retenido 20,00 € (10 %) → tope 200 × 10 % = 20,00 €
  acreditable; con TME del ahorro 19 % la cuota española es 38,00 € → deducción
  0588 = min(20, 38) = 20,00 €.
  Dividendo británico 300,00 €, retenido 0 → nada que deducir, y NO va a
  revisión manual (antes, sin tipo de convenio, todo el país iba a revisión).
  Dividendo chino 100 € con 30 € retenidos → tope 10,00 €; exceso 20,00 €
  reclamable en origen.
"""

from decimal import Decimal

from app.services.tax_irpf_filing import build_double_taxation


def _div(ticker, gross, withheld):
    return {
        "ticker": ticker, "dividends_base": gross, "withholding_base": withheld,
        "missing_fx": False, "payments": [],
    }


def test_china_tope_10_por_ciento_y_deduccion_con_tme():
    result = build_double_taxation([_div("CNX", 200.0, 20.0)], {"CNX": "CN"}, 2025, tme=Decimal("0.19"))
    (cn,) = result["countries"]
    assert cn["treaty_cap_base"] == 20.0
    assert cn["deduction_base"] == 20.0
    assert cn["treaty_rate_source"].startswith("BOE-A-2021-4911")
    assert result["manual_review"] == []
    assert result["total_deduction_base"] == 20.0


def test_china_exceso_sobre_el_10_por_ciento_es_reclamable_en_origen():
    result = build_double_taxation([_div("CNY1", 100.0, 30.0)], {"CNY1": "CN"}, 2025, tme=Decimal("0.19"))
    (cn,) = result["countries"]
    assert cn["treaty_cap_base"] == 10.0
    assert cn["excess_reclaimable_base"] == 20.0
    assert cn["deduction_base"] == 10.0


def test_reino_unido_sin_retencion_no_va_a_revision_manual():
    result = build_double_taxation(
        [_div("GBX1", 300.0, 0.0), _div("CNX", 200.0, 20.0)],
        {"GBX1": "GB", "CNX": "CN"}, 2025, tme=Decimal("0.19"),
    )
    assert result["manual_review"] == []
    assert result["partial"] is False
    assert result["total_deduction_base"] == 20.0
