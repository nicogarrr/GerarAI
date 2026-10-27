"""Ganancia del valor en su moneda, conversión única al vender (DGT)."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.services.tax_report_service import replay_tax_fifo


def tx(i, action, price, day):
    return SimpleNamespace(id=i, action=action, quantity=D(1), price=D(price), fees=D(0), currency='USD', trade_date=day, raw_payload={})


def test_same_native_price_is_zero_despite_fx_move_v2422_20_scenario():
    buy, sell = date(2025, 1, 1), date(2025, 6, 1)
    rates = {buy: D('1'), sell: D('0.87692')}
    _, sales = replay_tax_fifo([tx(1, 'buy', '1000', buy), tx(2, 'sell', '1000', sell)], lambda currency, day: rates.get(day), buy, sell)
    assert sales[0]['gain_base_raw'] == D('0.00')
    # Old two-date convention invented -123.08 EUR on the securities sale.
    assert D('1000') * rates[sell] - D('1000') * rates[buy] == D('-123.08000')


def test_missing_buy_fx_does_not_hide_known_native_gain_at_sale():
    buy, sell = date(2025, 1, 1), date(2025, 6, 1)
    _, sales = replay_tax_fifo([tx(1, 'buy', '1000', buy), tx(2, 'sell', '1100', sell)], lambda currency, day: D('0.9') if day == sell else None, buy, sell)
    assert sales[0]['gain_base_raw'] == D('90')
