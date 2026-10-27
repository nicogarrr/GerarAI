"""yahoo_symbol: clases US con punto (BRK.B) y alias de Euronext Amsterdam."""
from types import SimpleNamespace

from app.services.propicks_price_service import yahoo_symbol


def _c(ticker, exchange, currency):
    return SimpleNamespace(ticker=ticker, exchange=exchange, currency=currency)


def test_clase_us_con_punto_usa_guion_de_yahoo():
    # yfinance con «BRK.B» no devuelve barras (verificado 2026-10-27);
    # «BRK-B» si. El master guarda la clase con punto (convencion Finnhub).
    assert yahoo_symbol(_c("BRK.B", "NYSE", "USD")) == "BRK-B"
    assert yahoo_symbol(_c("BF.A", "NYSE", "USD")) == "BF-A"
    assert yahoo_symbol(_c("brk.b", "NYSE", "USD")) == "BRK-B"


def test_sufijo_de_bolsa_con_punto_queda_intacto():
    assert yahoo_symbol(_c("SAN.MC", "BME", "EUR")) == "SAN.MC"
    assert yahoo_symbol(_c("CGEO.L", "LONDON STOCK EXCHANGE", "GBP")) == "CGEO.L"


def test_alias_euronext_amsterdam_igual_que_wacc():
    # Mismos nombres de bolsa que acepta wacc_input_service (F156): sin
    # ellos ASML quedaba sin simbolo y sin precio de cierre.
    assert yahoo_symbol(_c("ASML", "EURONEXT AMSTERDAM", "EUR")) == "ASML.AS"
    assert yahoo_symbol(_c("ASML", "NYSE EURONEXT - AMSTERDAM", "EUR")) == "ASML.AS"
