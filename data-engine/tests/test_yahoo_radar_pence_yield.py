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
