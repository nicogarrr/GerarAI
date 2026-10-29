"""Tipos de convenio verificados para Países Bajos, Alemania y Francia (15 %).

Fuentes (texto consolidado del BOE, artículo de dividendos, persona física
minorista):
  - Países Bajos 1971, BOE-A-1972-1469, art. 10.2: "no puede exceder del 15 por
    100 del importe bruto de los dividendos".
  - Alemania 2011, BOE-A-2012-10212, art. 10.2.b: "15 por ciento del importe
    bruto de los dividendos en todos los demás casos".
  - Francia 1995, BOE-A-1997-12729, art. 10.2.a: "no podrá exceder del 15 por
    100 del importe bruto de los dividendos".
Irlanda (BOE-A-1994-28597, art. 10.1.b/c) depende del crédito fiscal irlandés,
que no fija el convenio: sigue en revisión manual.

Cálculo a mano (Basic-Fit, NL): dividendo 100,00 €, retenido 15,00 € (15 %) →
tope 15,00 €; cuota española con TME 19 % = 19,00 € → deducción 0588 = 15,00 €.
Alemania: 100,00 € con retención 26,375 € → tope 15,00 €, exceso reclamable
11,375 € (se redondea a 11,38 €), deducción 15,00 €.
"""

from decimal import Decimal

import pytest

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


@pytest.mark.parametrize(
    ("country", "boe"),
    [("NL", "BOE-A-1972-1469"), ("DE", "BOE-A-2012-10212"), ("FR", "BOE-A-1997-12729")],
)
def test_tipo_15_y_cita_boe(country, boe):
    assert TREATY_DIVIDEND_RATES[country] == Decimal("0.15")
    assert TREATY_RATE_SOURCES[country].startswith(boe)


def test_basic_fit_paises_bajos_deduce_hasta_el_15_sin_revision_manual():
    result = build_double_taxation([_div("BFIT.AS", 100.0, 15.0)], {"BFIT.AS": "NL"}, 2026, tme=Decimal("0.19"))
    (nl,) = result["countries"]
    assert nl["treaty_cap_base"] == 15.0
    assert nl["deduction_base"] == 15.0
    assert result["manual_review"] == []
    assert result["total_deduction_base"] == 15.0


def test_alemania_exceso_sobre_el_15_es_reclamable_en_origen():
    result = build_double_taxation([_div("SAP.DE", 100.0, 26.375)], {"SAP.DE": "DE"}, 2026, tme=Decimal("0.19"))
    (de,) = result["countries"]
    assert de["treaty_cap_base"] == 15.0
    assert de["deduction_base"] == 15.0
    assert de["excess_reclaimable_base"] == pytest.approx(11.38, abs=0.005)


def test_francia_con_tme_por_debajo_del_tope():
    # Retención 12,8 % < 15 %: se acredita lo retenido (12,80 €), con cuota 19 €.
    result = build_double_taxation([_div("MC.PA", 100.0, 12.8)], {"MC.PA": "FR"}, 2026, tme=Decimal("0.19"))
    (fr,) = result["countries"]
    assert fr["deduction_base"] == 12.8
    assert result["manual_review"] == []


def test_irlanda_sigue_en_revision_manual():
    assert "IE" not in TREATY_DIVIDEND_RATES
    result = build_double_taxation([_div("IEX", 100.0, 25.0)], {"IEX": "IE"}, 2026, tme=Decimal("0.19"))
    assert result["manual_review"] != []
