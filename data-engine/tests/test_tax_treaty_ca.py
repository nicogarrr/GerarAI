"""Tipo de convenio verificado para Canadá (15 %).

- España-Canadá, BOE-A-1981-2731 (texto consolidado con el Protocolo de
  2014, BOE-A-2015-10793), art. X.2: el impuesto en origen no puede exceder
  del 15 % del importe bruto "en todos los demás casos" (persona física
  minorista; el 5 % del art. X.2.a exige sociedad con >=10 % del capital).

Cálculo a mano:
  Dividendo canadiense 200,00 €, retenido 50,00 € (25 % interno canadiense
  sin aplicación del convenio) → tope 200 × 15 % = 30,00 € acreditable;
  exceso 20,00 € reclamable en origen. Con TME del ahorro 19 % la cuota
  española es 38,00 € → deducción 0588 = min(30, 38) = 30,00 €.
  Dividendo canadiense 100,00 € con 15,00 € retenidos (15 % aplicado en
  origen) → tope 15,00 €; sin exceso; deducción 15,00 €.
"""

from decimal import Decimal

from app.services.tax_irpf_filing import build_double_taxation


def _div(ticker, gross, withheld):
    return {
        "ticker": ticker, "dividends_base": gross, "withholding_base": withheld,
        "missing_fx": False, "payments": [],
    }


def test_canada_tope_15_por_ciento_y_exceso_reclamable():
    result = build_double_taxation([_div("BN", 200.0, 50.0)], {"BN": "CA"}, 2025, tme=Decimal("0.19"))
    (ca,) = result["countries"]
    assert ca["country"] == "CA"
    assert ca["treaty_rate"] == 0.15
    assert ca["treaty_cap_base"] == 30.0
    assert ca["excess_reclaimable_base"] == 20.0
    assert ca["deduction_base"] == 30.0
    assert ca["treaty_rate_source"].startswith("BOE-A-1981-2731")
    assert result["manual_review"] == []
    assert result["partial"] is False
    assert result["total_deduction_base"] == 30.0


def test_canada_retencion_justa_al_15_por_ciento_sin_exceso():
    result = build_double_taxation([_div("RY", 100.0, 15.0)], {"RY": "CA"}, 2025, tme=Decimal("0.19"))
    (ca,) = result["countries"]
    assert ca["treaty_cap_base"] == 15.0
    assert ca["excess_reclaimable_base"] == 0.0
    assert ca["deduction_base"] == 15.0
    assert result["manual_review"] == []


def test_canada_sin_tme_solo_muestra_tope():
    result = build_double_taxation([_div("BN", 200.0, 50.0)], {"BN": "CA"}, 2025)
    (ca,) = result["countries"]
    assert ca["status"] == "pendiente_tme"
    assert ca["deduction_base"] is None
    assert ca["treaty_cap_base"] == 30.0
