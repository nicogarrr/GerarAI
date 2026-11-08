"""Huecos de cobertura de app/services/ibkr_import_service.py (servicios 2/10).

Datos 100% sinteticos: XML y CSV construidos en el test, sin credenciales,
cuentas ni extractos reales de IBKR. Estilo de la casa: llamadas directas a
las funciones del modulo; NADA de red, BD ni broker.

Que NO se prueba aqui: la importacion a BD (import_flex_xml/import_ibkr_csv
completos, con SQLite) va en otro lote; aqui solo validacion pura
(validate_flex_xml, _is_date, _trim_xml_lead, _semicolon_v1_csv_values y la
deteccion de orden de fechas con barra). La cobertura propia de este
archivo se mide sola (pytest --cov del modulo con solo este archivo).
"""
from __future__ import annotations

from app.services import ibkr_import_service as m


def _flex(*filas: str) -> str:
    cuerpo = "".join(filas)
    return (
        '<FlexQueryResponse queryName="q" type="AF">'
        f"<FlexStatements><FlexStatement>{cuerpo}</FlexStatement></FlexStatements>"
        "</FlexQueryResponse>"
    )


def _errores(xml: str) -> list[str]:
    return m.validate_flex_xml(xml)


# --- orden de fechas con barra (por fichero) ------------------------------------


def test_fechas_barra_mezcladas_se_rechazan():
    # Evidencia en los dos sentidos: 15/03 solo puede ser dd/MM y 03/15 solo
    # MM/dd -> el fichero es incoherente y se rechaza entero.
    xml = _flex(
        '<Trade symbol="AAPL" quantity="1" tradePrice="10" tradeDate="15/03/2026"/>',
        '<Trade symbol="AAPL" quantity="1" tradePrice="10" tradeDate="03/15/2026"/>',
    )
    assert _errores(xml) == [m._MIXED_FLEX_DATES]


def test_fechas_barra_solo_dia_primero_validan():
    # 15/03/2026 solo puede ser 15 de marzo: el fichero fija dd/MM y la fila
    # no acusa error de fecha.
    xml = _flex(
        '<Trade symbol="AAPL" quantity="1" tradePrice="10" tradeDate="15/03/2026"/>',
    )
    assert _errores(xml) == []


def test_fechas_barra_solo_mes_primero_validan():
    xml = _flex(
        '<Trade symbol="AAPL" quantity="1" tradePrice="10" tradeDate="03/15/2026"/>',
    )
    assert _errores(xml) == []


# --- validacion por fila ---------------------------------------------------------


def test_openposition_precio_no_numerico():
    xml = _flex('<OpenPosition symbol="AAPL" position="10" markPrice="abc"/>')
    errores = _errores(xml)
    assert any("markPrice" in e and "abc" in e for e in errores)


def test_trade_sin_simbolo():
    xml = _flex('<Trade quantity="1" tradePrice="10" tradeDate="20260315"/>')
    errores = _errores(xml)
    assert any("(Trade)" in e and "falta el símbolo" in e for e in errores)


def test_trade_precio_no_numerico_y_negativo():
    xml = _flex(
        '<Trade symbol="AAPL" quantity="1" tradePrice="abc" tradeDate="20260315"/>',
        '<Trade symbol="MSFT" quantity="1" tradePrice="-3" tradeDate="20260315"/>',
    )
    errores = _errores(xml)
    assert any("AAPL" in e and "el precio 'abc'" in e for e in errores)
    assert any("MSFT" in e and "es negativo" in e for e in errores)


def test_trade_fecha_irreconocible():
    xml = _flex(
        '<Trade symbol="AAPL" quantity="1" tradePrice="10" tradeDate="32/13/2026"/>',
    )
    errores = _errores(xml)
    assert any("32/13/2026" in e and "formato" in e for e in errores)


def test_cash_transaction_importe_y_fecha_malos():
    xml = _flex(
        '<CashTransaction symbol="AAPL" amount="abc" dateTime="32/13/2026"/>',
    )
    errores = _errores(xml)
    assert any("(CashTransaction)" in e and "el importe 'abc'" in e for e in errores)
    assert any("(CashTransaction)" in e and "32/13/2026" in e for e in errores)


def test_cash_report_sin_divisa_y_saldo_malo():
    xml = _flex(
        '<CashReport endingCash="100" toDate="20260315"/>',
        '<CashReport currency="USD" endingCash="abc" toDate="20260315"/>',
    )
    errores = _errores(xml)
    assert any("(CashReport)" in e and "falta la divisa" in e for e in errores)
    assert any("(CashReport)" in e and "el saldo 'abc'" in e for e in errores)


# --- fichero entero: entidades, XML roto, PnL no listo ---------------------------


def test_xml_con_entidades_se_rechaza():
    xml = (
        '<?xml version="1.0"?><!DOCTYPE FlexQueryResponse [<!ENTITY x "y">]>'
        '<FlexQueryResponse><FlexStatement accountId="U1">&x;</FlexStatement></FlexQueryResponse>'
    )
    assert _errores(xml) == [m._XML_ENTITIES_MSG]


def test_xml_malformado_es_error_legible():
    errores = _errores("<FlexQueryResponse><Trade")
    assert len(errores) == 1
    assert "no se puede leer" in errores[0]


def test_xml_con_bom_y_lineas_en_blanco_valida():
    assert _errores('\ufeff\n\n<FlexQueryResponse><OpenPositions><OpenPosition symbol="AAPL" position="1" markPrice="10" reportDate="2026-03-15"/></OpenPositions></FlexQueryResponse>') == []


def test_pnl_no_listo_se_detecta():
    xml = _flex('<Message>Realized P/L is not ready. Pnl disabled for this account.</Message>')
    assert _errores(xml) == [m._PNL_NOT_READY_MESSAGE]


def test_trim_xml_lead_con_no_texto_devuelve_tal_cual():
    assert m._trim_xml_lead(b"<x/>") == b"<x/>"


# --- helpers puros ----------------------------------------------------------------


def test_is_date_normaliza_sufijos():
    assert m._is_date("2026-03-15;otra") is True
    assert m._is_date("2026-03-15 10:30:00") is True
    assert m._is_date("2026-03-15,") is True
    assert m._is_date("no-es-fecha") is False
    assert m._is_date("") is False
    assert m._is_date(None) is False


def test_semicolon_v1_csv_values_huella_legada():
    celdas = {"quantity": "32,725", "price": "10.5", "date": "2026-03-05",
              "fees": "1.25", "currency": "usd"}
    valores = m._semicolon_v1_csv_values("AAPL", "BUY", lambda k: celdas.get(k))
    assert valores == ["AAPL", "BUY", "32725", "10.5", "2026-03-05", "1.25", "USD"]


def test_semicolon_v1_csv_values_ilegible_es_none():
    celdas = {"quantity": "abc", "price": "10", "date": "2026-03-05",
              "fees": "", "currency": "USD"}
    assert m._semicolon_v1_csv_values("AAPL", "BUY", lambda k: celdas.get(k)) is None
