"""Libro de divisas: casos deterministas (DGT V2466-08, V0234-07, V0282-22)."""
from datetime import date
from decimal import Decimal as D

from app.services.currency_ledger import (
    COMPUTED,
    INCOMPLETE,
    NOT_COMPUTED,
    Conversion,
    CurrencyLot,
    Outflow,
    compute_currency_ledger,
    lots_from_sales,
)

Y0, Y1 = date(2025, 1, 1), date(2025, 12, 31)
THRU = date(2027, 1, 1)  # datos hasta despues de cualquier ventana de 1 año


def test_no_conversions_is_not_computed_not_zero():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(90))], [], Y0, Y1, opening_complete=True, data_through=THRU)
    assert r["status"] == NOT_COMPUTED and r["gain_base"] is None


def test_single_lot_full_conversion_gain():
    lots = [CurrencyLot(date(2025, 2, 1), D(1000), D(900))]  # 0.90 en la venta
    conv = [Conversion(date(2025, 3, 1), D(1000), D("0.95"))]
    r = compute_currency_ledger(lots, conv, Y0, Y1, opening_complete=True, data_through=THRU)
    assert r["status"] == COMPUTED and r["gain_base"] == 50.0 and r["unconverted"] == 0.0


def test_fifo_partial_consumption_across_lots():
    lots = [CurrencyLot(date(2025, 2, 1), D(100), D(90)), CurrencyLot(date(2025, 3, 1), D(100), D(100))]
    conv = [Conversion(date(2025, 4, 1), D(150), D("1.00"))]
    r = compute_currency_ledger(lots, conv, Y0, Y1, opening_complete=True, data_through=THRU)
    # coste = 90 + 50 = 140 ; transmision 150
    assert r["gain_base"] == 10.0 and r["unconverted"] == 50.0
    c2 = Conversion(date(2025, 5, 1), D(50), D("0.80"))
    r2 = compute_currency_ledger(lots, conv + [c2], Y0, Y1, opening_complete=True, data_through=THRU)
    assert r2["gain_base"] == 10.0 + (40.0 - 50.0)  # 2o lote: coste 50, transmision 40


def test_loss_is_negative():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(100))], [Conversion(date(2025, 3, 1), D(100), D("0.90"))], Y0, Y1, opening_complete=True, data_through=THRU)
    assert r["gain_base"] == -10.0


def test_conversion_exceeding_known_currency_is_incomplete():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(90))], [Conversion(date(2025, 3, 1), D(150), D("1"))], Y0, Y1, opening_complete=True, data_through=THRU)
    assert r["status"] == INCOMPLETE and r["gain_base"] is None


def test_missing_ecb_rate_or_lot_value_is_incomplete():
    lot = CurrencyLot(date(2025, 2, 1), D(100), D(90))
    assert compute_currency_ledger([lot], [Conversion(date(2025, 3, 1), D(100), None)], Y0, Y1, opening_complete=True, data_through=THRU)["status"] == INCOMPLETE
    nolot = CurrencyLot(date(2025, 2, 1), D(100), None)
    assert compute_currency_ledger([nolot], [Conversion(date(2025, 3, 1), D(100), D(1))], Y0, Y1, opening_complete=True, data_through=THRU)["gain_base"] is None


def test_opening_balance_not_guaranteed_is_incomplete():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(90))], [Conversion(date(2025, 3, 1), D(100), D(1))], Y0, Y1)
    assert r["status"] == INCOMPLETE and r["gain_base"] is None


def test_lot_after_conversion_date_is_not_consumed():
    lots = [CurrencyLot(date(2025, 6, 1), D(100), D(90))]
    r = compute_currency_ledger(lots, [Conversion(date(2025, 3, 1), D(100), D(1))], Y0, Y1, opening_complete=True, data_through=THRU)
    assert r["status"] == INCOMPLETE


def test_conversion_outside_year_consumes_but_is_not_summed():
    lots = [CurrencyLot(date(2024, 12, 1), D(100), D(100)), CurrencyLot(date(2025, 2, 1), D(100), D(80))]
    convs = [Conversion(date(2024, 12, 20), D(100), D("1.1")), Conversion(date(2025, 3, 1), D(100), D("0.9"))]
    r = compute_currency_ledger(lots, convs, Y0, Y1, opening_complete=True, data_through=THRU)
    assert r["gain_base"] == 10.0  # 90 - 80; la de 2024 no entra


def test_lots_from_sales_keeps_unknown_rate_as_none():
    ls = lots_from_sales([{"date": date(2025, 1, 2), "proceeds_native": 10, "proceeds_base": None}])
    assert ls[0].eur_value is None


def test_report_summary_marks_ledger_not_computed_without_conversions():
    import inspect

    from app.services.tax_report_service import TaxReportService
    src = inspect.getsource(TaxReportService.compute_report)
    assert "currency_ledger_status" in src and "fx_conversions" in src


def _run(lots, convs, outflows=(), thru=THRU):
    return compute_currency_ledger(lots, convs, Y0, Y1, opening_complete=True, outflows=outflows, data_through=thru)


def test_purchase_outflow_consumes_fifo_without_own_result():  # V0282-22 / V0706-22
    lots = [CurrencyLot(date(2025, 1, 1), D(1000), D(900))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(600), D("0.95"))], [Outflow(date(2025, 2, 1), D(400), "compra", "b1")])
    # coste de los 600 restantes = 540; transmision 570; la compra de 400 no da resultado
    assert r["gain_base"] == 30.0 and r["unconverted"] == 0.0


def test_outflow_above_known_currency_is_incomplete():
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(90))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(50), D(1))], [Outflow(date(2025, 2, 1), D(200), "comision", "c1")])
    assert r["status"] == INCOMPLETE and r["gain_base"] is None and "comision" in r["reason"]


def test_loss_blocked_by_reacquisition_within_one_year_then_released():  # art. 33.5.e, V1613-25
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2025, 6, 1), D(100), D(92))]
    convs = [Conversion(date(2025, 3, 1), D(100), D("0.90")), Conversion(date(2025, 9, 1), D(100), D("1.00"))]
    r = _run(lots, convs)
    first, second = r["rows"]
    assert first["gain_base"] == -10.0 and first["blocked_loss_base"] == 10.0 and first["integrated_gain_base"] == 0.0
    # el lote readquirido pasa a valer 92 + 10 = 102 -> al convertir a 1.00 pierde 2
    assert second["gain_base"] == -2.0 and second["integrated_gain_base"] == -2.0
    assert r["gain_base"] == -2.0 and r["blocked_loss_base"] == 10.0


def test_partial_reacquisition_blocks_proportionally():
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2025, 6, 1), D(50), D(46))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"))])
    assert r["rows"][0]["blocked_loss_base"] == 5.0 and r["gain_base"] == -5.0


def test_reacquisition_beyond_one_year_does_not_block():
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2026, 6, 1), D(100), D(90))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"))])
    assert r["gain_base"] == -10.0 and r["blocked_loss_base"] == 0.0


def test_two_months_is_not_the_window():  # compra a los 4 meses sigue bloqueando
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2025, 7, 1), D(100), D(90))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"))])
    assert r["rows"][0]["blocked_loss_base"] == 10.0


def test_prior_year_acquisition_does_not_block_only_posterior_does():  # art. 33.5.e: solo posterior
    lots = [CurrencyLot(date(2024, 12, 1), D(100), D(100)), CurrencyLot(date(2025, 2, 1), D(100), D(90))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.80"))])
    assert r["rows"][0]["blocked_loss_base"] == 0.0 and r["gain_base"] == -20.0


def _same_day(lot_time, conv_time):
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2025, 3, 1), D(100), D(90), "", lot_time)]
    return _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"), "", conv_time)])["rows"][0]["blocked_loss_base"]


def test_same_day_without_times_blocks_conservatively():  # sin orden intradia, sin consulta que lo dirima
    assert _same_day("", "") == 10.0


def test_same_day_with_one_time_missing_blocks():
    assert _same_day("101500", "") == 10.0 and _same_day("", "101500") == 10.0


def test_same_day_known_times_only_later_purchase_blocks():
    assert _same_day("110000", "101500") == 10.0   # compra despues de la conversion
    assert _same_day("101500", "110000") == 0.0    # compra antes de la conversion
    assert _same_day("101500", "101500") == 0.0    # misma hora: no es posterior


def test_acquisition_exactly_one_year_after_blocks_and_one_day_later_does_not():
    base = [CurrencyLot(date(2025, 1, 1), D(100), D(100))]
    conv = [Conversion(date(2025, 3, 1), D(100), D("0.90"))]
    assert _run(base + [CurrencyLot(date(2026, 3, 1), D(100), D(90))], conv)["rows"][0]["blocked_loss_base"] == 10.0
    assert _run(base + [CurrencyLot(date(2026, 3, 2), D(100), D(90))], conv)["rows"][0]["blocked_loss_base"] == 0.0


def test_loss_with_window_still_open_is_incomplete():
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"))], thru=date(2025, 4, 1))
    assert r["status"] == INCOMPLETE and r["gain_base"] is None and "ventana" in r["reason"]



def test_loss_fully_covered_by_reacquisition_is_complete_with_window_open():
    # art. 33.5.e LIRPF + V1613-25: perdida 100 % cubierta por recompra dentro
    # del año siguiente -> no se computa y se integra al transmitir la divisa
    # recomprada. Ninguna recompra futura cambia nada: no es «incompleto».
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2025, 6, 1), D(120), D(108))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"))], thru=date(2025, 12, 31))
    row = r["rows"][0]
    assert row["window_open"] is True and row["blocked_loss_base"] == 10.0 and row["integrated_gain_base"] == 0.0
    assert r["status"] == COMPUTED and r["gain_base"] == 0.0 and r["blocked_loss_base"] == 10.0


def test_loss_partially_covered_with_window_open_stays_incomplete():
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(100)), CurrencyLot(date(2025, 6, 1), D(50), D(46))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("0.90"))], thru=date(2025, 12, 31))
    assert r["rows"][0]["blocked_loss_base"] == 5.0
    assert r["status"] == INCOMPLETE and r["gain_base"] is None and "ventana" in r["reason"]

def test_gain_is_never_blocked():
    lots = [CurrencyLot(date(2025, 1, 1), D(100), D(90)), CurrencyLot(date(2025, 6, 1), D(100), D(95))]
    r = _run(lots, [Conversion(date(2025, 3, 1), D(100), D("1.00"))])
    assert r["gain_base"] == 10.0 and r["blocked_loss_base"] == 0.0


def test_lot_acquired_later_same_day_is_not_consumed():
    # MEDIDO (sonda 31-10-2026): una conversion de las 10:00 consumia un lote
    # adquirido a las 15:00 del mismo dia (la divisa aun no existia). Con
    # ambas horas conocidas, el lote posterior no es consumible: sin saldo
    # anterior la conversion no tiene adquisicion y el resultado es
    # incomplete, nunca una ganancia computada con la base del futuro.
    lot = CurrencyLot(date(2026, 3, 2), D("100"), D("90"), "venta", "150000")
    conv = Conversion(date(2026, 3, 2), D("100"), D("0.95"), "fx", "100000")
    result = compute_currency_ledger([lot], [conv], date(2026, 3, 2), date(2026, 3, 2),
                                     opening_complete=True)
    assert result["rows"][0]["gain_base"] is None
    assert result["status"] == INCOMPLETE


def test_lot_acquired_earlier_same_day_is_consumed():
    lot = CurrencyLot(date(2026, 3, 2), D("100"), D("90"), "venta", "100000")
    conv = Conversion(date(2026, 3, 2), D("100"), D("0.95"), "fx", "150000")
    result = compute_currency_ledger([lot], [conv], date(2026, 3, 2), date(2026, 3, 2),
                                     opening_complete=True)
    assert result["rows"][0]["gain_base"] == 5.0
    assert result["status"] == COMPUTED


def test_same_day_without_times_still_consumes():
    # Sin hora no hay orden intradia conocido: se mantiene el criterio actual
    # (consumo por fecha) para no volver incomplete toda conversion intradia.
    lot = CurrencyLot(date(2026, 3, 2), D("100"), D("90"), "venta", "")
    conv = Conversion(date(2026, 3, 2), D("100"), D("0.95"), "fx", "")
    result = compute_currency_ledger([lot], [conv], date(2026, 3, 2), date(2026, 3, 2),
                                     opening_complete=True)
    assert result["rows"][0]["gain_base"] == 5.0
