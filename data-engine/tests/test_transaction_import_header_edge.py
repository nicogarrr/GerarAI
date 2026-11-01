"""Importación genérica: cabecera tras líneas en blanco y columnas con el mismo nombre.

- Un CSV que empieza con líneas en blanco tomaba la primera (vacía) como
  cabecera: «No se encontró la columna obligatoria…» en un fichero correcto.
- Con dos columnas del mismo nombre («Precio;Precio», «Divisa» repetida), la
  autodetección elegía la PRIMERA pero los valores se leían de la ÚLTIMA: un
  precio o una divisa equivocados sin ningún aviso.
"""

from app.services.transaction_import_service import TransactionImportService, parse_file_rows

BASE = "Fecha;Ticker;Tipo;Cantidad;Precio;Divisa\n15/03/2024;AAPL;Compra;10;170,50;USD\n"


def _preview(text: str):
    return TransactionImportService().preview_import(text.encode("utf-8"), "operaciones.csv")


def test_lineas_en_blanco_antes_de_la_cabecera():
    result = _preview("\n\r\n;;;\n" + BASE)
    assert result.success, result.errors
    assert result.total_rows == 1
    item = result.preview_items[0]
    assert (item.ticker, item.price, item.currency) == ("AAPL", 170.5, "USD")


def test_parse_file_rows_salta_lineas_vacias_iniciales():
    headers, rows = parse_file_rows(("\n" + BASE).encode("utf-8"), "a.csv")
    assert headers[0] == "Fecha"
    assert len(rows) == 1


def test_columna_repetida_lee_la_que_se_detecto():
    text = (
        "Fecha;Ticker;Tipo;Cantidad;Precio;Divisa;Precio;Divisa\n"
        "15/03/2024;AAPL;Compra;10;170,50;USD;157,00;EUR\n"
    )
    result = _preview(text)
    assert result.success, result.errors
    item = result.preview_items[0]
    assert (item.price, item.currency) == (170.5, "USD")
