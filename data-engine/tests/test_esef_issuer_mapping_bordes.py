"""Bordes de ``esef_issuer_mapping``: entradas vacias y ``reviewed_isin_for_ticker``.

Lo que cada test demuestra:
- ``reviewed_isins_for_ticker`` con ticker vacio/None devuelve el conjunto
  vacio (guarda de entrada, antes de consultar las tablas reviewed).
- ``reviewed_isin_for_ticker`` devuelve el ISIN reviewed exacto por pais
  (ES, NL, IE), normaliza espacios y minusculas, y devuelve None para
  entradas vacias y para tickers no reviewed (nunca adivina).
"""

from app.services.esef_issuer_mapping import (
    reviewed_isin_for_ticker,
    reviewed_isins_for_ticker,
)


def test_isins_entrada_vacia_o_none_devuelve_conjunto_vacio():
    assert reviewed_isins_for_ticker("") == frozenset()
    assert reviewed_isins_for_ticker(None) == frozenset()
    assert reviewed_isins_for_ticker("   ") == frozenset()


def test_isin_entrada_vacia_o_none_devuelve_none():
    assert reviewed_isin_for_ticker("") is None
    assert reviewed_isin_for_ticker(None) is None
    assert reviewed_isin_for_ticker("   ") is None


def test_isin_reviewed_por_pais_exacto():
    # ES (tabla CNMV), NL (ASML) e IE (Kerry ADR), ISINs revisados a mano.
    assert reviewed_isin_for_ticker("ITX") == "ES0148396007"
    assert reviewed_isin_for_ticker("ASML") == "NL0010273215"
    assert reviewed_isin_for_ticker("KRYAY") == "IE0004906560"


def test_isin_normaliza_espacios_y_minusculas():
    assert reviewed_isin_for_ticker("  asml ") == "NL0010273215"
    assert reviewed_isin_for_ticker("kryay") == "IE0004906560"


def test_isin_no_reviewed_devuelve_none():
    # KRKNF es Kraken Robotics (Canada), no presenta ESEF: nunca se adivina.
    assert reviewed_isin_for_ticker("KRKNF") is None
    assert reviewed_isin_for_ticker("TICKER_INEXISTENTE") is None
