"""Radar Yahoo: rentabilidad por dividendo en cotizaciones en peniques.

Verificado en vivo el 30-oct-2026 (Yahoo quote):
  TSCO.L GBp 538.0, trailingAnnualDividendRate 0.148 (GBP),
  trailingAnnualDividendYield 0.000279 (0,03 %), dividendYield 2.78 (%).
Calculo independiente: 0.148 GBP = 14.8 p; 14.8 / 538 = 2,75 % ~ 2,78 %.
El campo trailing divide libras entre peniques: 100 veces bajo.
"""
from decimal import Decimal

from app.services.yahoo_radar_service import parse_screener_quotes


def _payload(**quote):
    return {"finance": {"result": [{"quotes": [{"symbol": "TSCO.L", **quote}]}]}}


def test_yield_en_peniques_usa_dividend_yield_no_el_trailing_x100_bajo():
    [c] = parse_screener_quotes(_payload(
        currency="GBp", trailingAnnualDividendYield=0.0002787194, dividendYield=2.78,
    ))
    assert c.dividend_yield == Decimal("0.0278")


def test_yield_en_peniques_sin_dividend_yield_es_nd():
    [c] = parse_screener_quotes(_payload(currency="GBp", trailingAnnualDividendYield=0.0002787194))
    assert c.dividend_yield is None


def test_yield_en_divisa_principal_respaldo_trailing():
    [c] = parse_screener_quotes(_payload(currency="EUR", trailingAnnualDividendYield=0.023972603))
    assert c.dividend_yield == Decimal("0.023972603")


def test_yield_en_divisa_principal_prefiere_dividend_yield():
    [c] = parse_screener_quotes(_payload(
        currency="EUR", trailingAnnualDividendYield=0.023972603, dividendYield=2.42,
    ))
    assert c.dividend_yield == Decimal("0.0242")


def test_pb_con_libro_en_otra_divisa_es_nd():
    """HSBA.L real (30-oct): 1287,2 GBp, libro 7,554 USD, Yahoo P/B 1,70 = GBP/USD."""
    [c] = parse_screener_quotes(_payload(
        symbol="HSBA.L", currency="GBp", financialCurrency="USD",
        priceToBook={"raw": 1.7039942}, dividendYield={"raw": 5.1},
    ))
    assert c.price_to_book is None


def test_pb_con_libro_en_la_misma_divisa_se_mantiene():
    # GBp (subunidad) y GBP son la misma divisa principal: P/B intacto.
    [c] = parse_screener_quotes(_payload(
        symbol="TSCO.L", currency="GBp", financialCurrency="GBP",
        priceToBook={"raw": 2.9}, dividendYield={"raw": 2.78},
    ))
    assert c.price_to_book == Decimal("2.9")
    [d] = parse_screener_quotes(_payload(symbol="X.L", currency="GBp", priceToBook={"raw": 1.2}))
    assert d.price_to_book == Decimal("1.2")  # sin financialCurrency: no se sabe, se mantiene
