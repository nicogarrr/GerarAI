"""r5-tesis2: el «por qué» de la dilución del SOTP sale en formato español y en la divisa del modelo.

Antes: «SBC 47,5 M$/año × 4 años ÷ precio 32.33 = 5,9 M»: el precio con punto decimal inglés (los millones ya
iban con coma) y «M$» fijo aunque, desde #5372, el modelo de un emisor que reporta en CAD/EUR/TWD va en esa divisa
(el precio se convierte a ella). Regla general: precio con dos decimales a la española y la divisa ISO de las
anclas; sin divisa conocida, ninguna (nunca un «$» supuesto).
"""

from app.services.expert_team import sotp_rules as r

BASE = {"ticker": "X", "price": 1342.374, "currency": "USD", "sbc_annual_millions": 47.5,
        "burns_cash": True, "annual_burn_millions": 900.0, "cash_millions": 100.0,
        "short_term_investments_millions": None}


def _why(anchors):
    return {d["label"]: d["why"]["shares"] for d in r.code_dilution(anchors, 4)}


def test_precio_con_coma_decimal_y_miles_con_punto():
    why = _why(BASE)
    sbc = why["Remuneración en acciones (SBC) hasta el año valorado"]
    assert "÷ precio 1.342,37 USD" in sbc
    assert "1342.37" not in sbc
    gap = why["Ampliaciones para cubrir la quema"]
    assert "÷ precio 1.342,37 USD" in gap


def test_divisa_del_modelo_no_dolar_fijo():
    why = _why({**BASE, "currency": "CAD", "price": 50.5})
    sbc = why["Remuneración en acciones (SBC) hasta el año valorado"]
    assert "47,5 M CAD/año" in sbc and "÷ precio 50,50 CAD" in sbc
    assert "$" not in sbc
    assert "M CAD/año" in why["Ampliaciones para cubrir la quema"]


def test_sin_ampliacion_tambien_en_la_divisa_del_modelo():
    why = _why({**BASE, "currency": "EUR", "cash_millions": 5000.0})
    assert "quema 900,0 M EUR/año" in why["Ampliaciones para cubrir la quema"]


def test_sin_divisa_no_inventa_simbolo():
    why = _why({**BASE, "currency": None, "price": 32.0})
    sbc = why["Remuneración en acciones (SBC) hasta el año valorado"]
    assert "$" not in sbc and "÷ precio 32,00 =" in sbc and "47,5 M/año" in sbc
