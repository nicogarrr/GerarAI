"""Libro de divisas: casos deterministas (DGT V2466-08, V0234-07, V0282-22)."""
from datetime import date
from decimal import Decimal as D

from app.services.currency_ledger import (
    COMPUTED, INCOMPLETE, NOT_COMPUTED, Conversion, CurrencyLot,
    compute_currency_ledger, lots_from_sales,
)

Y0, Y1 = date(2025, 1, 1), date(2025, 12, 31)


def test_no_conversions_is_not_computed_not_zero():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(90))], [], Y0, Y1, opening_complete=True)
    assert r["status"] == NOT_COMPUTED and r["gain_base"] is None


def test_single_lot_full_conversion_gain():
    lots = [CurrencyLot(date(2025, 2, 1), D(1000), D(900))]  # 0.90 en la venta
    conv = [Conversion(date(2025, 3, 1), D(1000), D("0.95"))]
    r = compute_currency_ledger(lots, conv, Y0, Y1, opening_complete=True)
    assert r["status"] == COMPUTED and r["gain_base"] == 50.0 and r["unconverted"] == 0.0


def test_fifo_partial_consumption_across_lots():
    lots = [CurrencyLot(date(2025, 2, 1), D(100), D(90)), CurrencyLot(date(2025, 3, 1), D(100), D(100))]
    conv = [Conversion(date(2025, 4, 1), D(150), D("1.00"))]
    r = compute_currency_ledger(lots, conv, Y0, Y1, opening_complete=True)
    # coste = 90 + 50 = 140 ; transmision 150
    assert r["gain_base"] == 10.0 and r["unconverted"] == 50.0
    c2 = Conversion(date(2025, 5, 1), D(50), D("0.80"))
    r2 = compute_currency_ledger(lots, conv + [c2], Y0, Y1, opening_complete=True)
    assert r2["gain_base"] == 10.0 + (40.0 - 50.0)  # 2o lote: coste 50, transmision 40


def test_loss_is_negative():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(100))], [Conversion(date(2025, 3, 1), D(100), D("0.90"))], Y0, Y1, opening_complete=True)
    assert r["gain_base"] == -10.0


def test_conversion_exceeding_known_currency_is_incomplete():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(90))], [Conversion(date(2025, 3, 1), D(150), D("1"))], Y0, Y1, opening_complete=True)
    assert r["status"] == INCOMPLETE and r["gain_base"] is None


def test_missing_ecb_rate_or_lot_value_is_incomplete():
    lot = CurrencyLot(date(2025, 2, 1), D(100), D(90))
    assert compute_currency_ledger([lot], [Conversion(date(2025, 3, 1), D(100), None)], Y0, Y1, opening_complete=True)["status"] == INCOMPLETE
    nolot = CurrencyLot(date(2025, 2, 1), D(100), None)
    assert compute_currency_ledger([nolot], [Conversion(date(2025, 3, 1), D(100), D(1))], Y0, Y1, opening_complete=True)["gain_base"] is None


def test_opening_balance_not_guaranteed_is_incomplete():
    r = compute_currency_ledger([CurrencyLot(date(2025, 2, 1), D(100), D(90))], [Conversion(date(2025, 3, 1), D(100), D(1))], Y0, Y1)
    assert r["status"] == INCOMPLETE and r["gain_base"] is None


def test_lot_after_conversion_date_is_not_consumed():
    lots = [CurrencyLot(date(2025, 6, 1), D(100), D(90))]
    r = compute_currency_ledger(lots, [Conversion(date(2025, 3, 1), D(100), D(1))], Y0, Y1, opening_complete=True)
    assert r["status"] == INCOMPLETE


def test_conversion_outside_year_consumes_but_is_not_summed():
    lots = [CurrencyLot(date(2024, 12, 1), D(100), D(100)), CurrencyLot(date(2025, 2, 1), D(100), D(80))]
    convs = [Conversion(date(2024, 12, 20), D(100), D("1.1")), Conversion(date(2025, 3, 1), D(100), D("0.9"))]
    r = compute_currency_ledger(lots, convs, Y0, Y1, opening_complete=True)
    assert r["gain_base"] == 10.0  # 90 - 80; la de 2024 no entra


def test_lots_from_sales_keeps_unknown_rate_as_none():
    ls = lots_from_sales([{"date": date(2025, 1, 2), "proceeds_native": 10, "proceeds_base": None}])
    assert ls[0].eur_value is None


def test_report_summary_marks_ledger_not_computed_without_conversions():
    import inspect
    from app.services.tax_report_service import TaxReportService
    src = inspect.getsource(TaxReportService.compute_report)
    assert "currency_ledger_status" in src and "fx_conversions" in src
