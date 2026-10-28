"""Supervivientes de mutmut en los helpers de ``tax_report_service`` (ronda 2).

Funciones puras del informe fiscal que no tenian ningun test directo: la hora
de ejecucion que ordena el FIFO, el tipo de cambio con caducidad (directo e
inverso) y el diferimiento de perdidas bloqueadas en divisa base.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.tax_report_service import (
    MAX_FX_AGE_DAYS,
    _defer_base,
    _execution_time,
    _fifo_sort_key,
    _rate_not_older_than,
)


def _tx(raw=None, *, action="buy", day=date(2025, 3, 10), id_=1):
    return SimpleNamespace(raw_payload=raw, action=action, trade_date=day, id=id_)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"dateTime": "20250310;093012"}, "093012"),       # Flex IBKR
        ({"dateTime": "2025-03-10 09:30:12"}, "093012"),   # con espacio
        ({"dateTime": "2025-03-10T09:30:12+01:00"}, "093012"),  # ISO con zona
        ({"dateTime": "20250310;0930"}, "093000"),         # sin segundos: rellena
        ({"dateTime": "20250310;09"}, ""),                 # menos de 4 cifras: nada
        ({"dateTime": "20250310"}, ""),                    # solo fecha
        ({"dateTime": None}, ""),
        ({}, ""),
        (None, ""),
        ("20250310;093012", ""),                           # payload no dict
    ],
)
def test_execution_time(raw, expected):
    assert _execution_time(_tx(raw)) == expected


def test_fifo_mismo_dia_sin_hora_compra_antes_que_venta_y_luego_id():
    sell = _tx(action="SELL", id_=1)
    buy = _tx(action="BOT", id_=2)
    later_buy = _tx(action="buy", id_=3)
    no_id = _tx(action="buy", id_=None)
    ordered = sorted([sell, later_buy, buy, no_id], key=_fifo_sort_key)
    assert ordered == [no_id, buy, later_buy, sell]
    # Con hora de ejecucion manda la hora, no el tipo de operacion.
    early_sell = _tx({"dateTime": "20250310;093000"}, action="sell", id_=4)
    late_buy = _tx({"dateTime": "20250310;153000"}, action="buy", id_=5)
    assert sorted([late_buy, early_sell], key=_fifo_sort_key) == [early_sell, late_buy]
    assert _fifo_sort_key(_tx(action=None, id_=None))[2:] == (1, 0)


D = date(2025, 3, 10)


def test_rate_not_older_than_directo_inverso_y_caducidad():
    direct = {("EUR", "USD"): [(date(2025, 3, 7), Decimal("0.90"))]}
    assert _rate_not_older_than(direct, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("0.90")
    # Solo existe el par inverso: 1 / tipo.
    inverse = {("USD", "EUR"): [(date(2025, 3, 7), Decimal("1.25"))]}
    assert _rate_not_older_than(inverse, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("1") / Decimal("1.25")
    # Subunidad: peniques -> EUR con el tipo de la libra / 100.
    gbp = {("EUR", "GBP"): [(D, Decimal("1.20"))]}
    assert _rate_not_older_than(gbp, quote_currency="GBp", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("0.012")
    # Exactamente max_age_days de antiguedad vale; uno mas, no.
    edge = {("EUR", "USD"): [(date(2025, 3, 3), Decimal("0.90"))]}
    assert _rate_not_older_than(edge, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("0.90")
    assert _rate_not_older_than(edge, quote_currency="USD", base_currency="EUR",
                                as_of=date(2025, 3, 11), max_age_days=7) is None
    assert MAX_FX_AGE_DAYS == 7


def test_rate_not_older_than_directo_caducado_o_futuro_cae_al_inverso():
    table = {
        ("EUR", "USD"): [(date(2025, 1, 2), Decimal("0.95"))],  # caducado
        ("USD", "EUR"): [(date(2025, 3, 7), Decimal("1.25"))],  # fresco
    }
    assert _rate_not_older_than(table, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("1") / Decimal("1.25")
    future = {
        ("EUR", "USD"): [(date(2025, 3, 20), Decimal("0.95"))],  # posterior a as_of
        ("USD", "EUR"): [(date(2025, 3, 7), Decimal("1.25"))],
    }
    assert _rate_not_older_than(future, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("1") / Decimal("1.25")
    zero = {
        ("EUR", "USD"): [(date(2025, 3, 7), Decimal("0"))],  # tipo 0: dato roto
        ("USD", "EUR"): [(date(2025, 3, 7), Decimal("1.25"))],
    }
    assert _rate_not_older_than(zero, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("1") / Decimal("1.25")
    assert _rate_not_older_than({}, quote_currency="USD", base_currency="EUR",
                                as_of=D, max_age_days=7) is None
    assert _rate_not_older_than({}, quote_currency="eur", base_currency="EUR",
                                as_of=D, max_age_days=7) == Decimal("1")


def test_defer_base_acumula_y_propaga_lo_desconocido():
    lot = {"deferred_base": Decimal("10"), "deferred_unknown": False}
    _defer_base(lot, Decimal("2"), {"loss_per_share_base": Decimal("3")})
    assert lot["deferred_base"] == Decimal("16")
    assert lot["deferred_unknown"] is False
    # Perdida de una venta descubierta: base y diferido desconocidos.
    _defer_base(lot, Decimal("1"), {"loss_unknown": True, "loss_per_share_base": Decimal("3")})
    assert lot["deferred_unknown"] is True
    assert lot["deferred_base"] is None
    # Una vez desconocido, no vuelve a ser un numero.
    _defer_base(lot, Decimal("1"), {"loss_per_share_base": Decimal("3")})
    assert lot["deferred_base"] is None
    # Sin perdida por accion en base: el diferido base pasa a desconocido.
    other = {"deferred_base": Decimal("5"), "deferred_unknown": False}
    _defer_base(other, Decimal("1"), {"loss_per_share_base": None})
    assert other["deferred_base"] is None
    assert other["deferred_unknown"] is False



def test_cash_amount_cae_a_quantity_solo_sin_price():
    from app.services.tax_report_service import cash_amount

    assert cash_amount(SimpleNamespace(price=Decimal("0"), quantity=Decimal("1"))) == Decimal("0")
    assert cash_amount(SimpleNamespace(price=None, quantity=Decimal("25"))) == Decimal("25")
    assert cash_amount(SimpleNamespace(price=None, quantity=None)) == Decimal("0")
    assert cash_amount(SimpleNamespace(price=None)) == Decimal("0")


def test_money_redondea_mitad_hacia_arriba():
    from app.services.tax_report_service import _money

    assert _money(Decimal("0.125")) == 0.13   # banquero daria 0.12
    assert _money(Decimal("2.675")) == 2.68
    assert _money(Decimal("-0.125")) == -0.13
    assert _money(None) is None


def test_fila_de_broker_firmada_y_retencion():
    from app.services.tax_report_service import (
        cash_quantity_is_canonical,
        is_broker_signed_cash_row,
        withholding_cost,
    )

    ibkr = SimpleNamespace(raw_payload={"trxID": "1"}, price=Decimal("-15"), quantity=Decimal("1"))
    manual = SimpleNamespace(raw_payload=None, price=Decimal("15"), quantity=Decimal("1"))
    weird = SimpleNamespace(raw_payload="trxID", price=Decimal("-15"), quantity=Decimal("1"))
    assert is_broker_signed_cash_row(ibkr) is True
    assert is_broker_signed_cash_row(manual) is False
    assert is_broker_signed_cash_row(weird) is False
    assert is_broker_signed_cash_row(SimpleNamespace(raw_payload={"other": 1})) is False
    assert is_broker_signed_cash_row(SimpleNamespace()) is False
    assert withholding_cost(ibkr) == Decimal("15")
    assert withholding_cost(manual) == Decimal("15")
    assert withholding_cost(weird) == Decimal("15")  # no es IBKR: valor absoluto
    assert cash_quantity_is_canonical(SimpleNamespace()) is True
    assert cash_quantity_is_canonical(SimpleNamespace(quantity=Decimal("25"))) is False
