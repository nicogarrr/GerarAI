"""Importación CSV: el separador decimal se decide por fichero, no por celda.

Una celda con un único separador y tres cifras («3,450», «1.234») es ambigua:
puede ser decimal o grupo de miles. Leída sola, el parser la toma como miles.
En un fichero que en otras celdas escribe la coma como decimal («34,12»,
«-2,00»), «3,450» es 3,45 € (Santander) y no 3.450 €: un coste x1000 que la
vista previa daba por válido. Al revés, en un fichero con punto decimal
(«34.12»), «1.234» es 1,234 y no 1.234.
"""

from __future__ import annotations

from app.services.transaction_import_service import TransactionImportService


def _preview(csv_text: str):
    return TransactionImportService().preview_import(file_bytes=csv_text.encode(), filename="x.csv")


def _prices(result) -> dict[str, float]:
    return {item.ticker: item.price for item in result.preview_items}


def test_spanish_file_reads_three_decimal_price_as_decimal() -> None:
    result = _preview(
        "Fecha;Ticker;Tipo;Cantidad;Precio;Comisión;Divisa\n"
        "15/01/2024;SAN;compra;100;3,450;-2,00;EUR\n"
        "16/01/2024;ITX;compra;10;34,12;-2,00;EUR\n"
    )
    assert result.errors == []
    assert _prices(result) == {"SAN": 3.45, "ITX": 34.12}


def test_spanish_file_keeps_point_as_thousands() -> None:
    result = _preview(
        "Fecha;Ticker;Tipo;Cantidad;Precio;Divisa\n"
        "15/01/2024;ASML;compra;1.000;612,50;EUR\n"
        "16/01/2024;SAN;compra;2.500;3,450;EUR\n"
    )
    items = {item.ticker: item for item in result.preview_items}
    assert items["ASML"].quantity == 1000
    assert items["SAN"].quantity == 2500
    assert items["SAN"].price == 3.45


def test_english_file_reads_three_decimal_price_as_decimal() -> None:
    result = _preview(
        "Date,Ticker,Action,Quantity,Price,Fees,Currency\n"
        "2024-01-15,AAPL,buy,10,185.12,1.00,USD\n"
        "2024-01-16,ZETA,buy,100,1.234,1.00,USD\n"
    )
    assert result.errors == []
    assert _prices(result) == {"AAPL": 185.12, "ZETA": 1.234}


def test_english_file_keeps_comma_as_thousands() -> None:
    result = _preview(
        'Date,Ticker,Action,Quantity,Price,Fees,Currency\n'
        '2024-01-15,NVR,buy,1,"7,450.25",1.00,USD\n'
        '2024-01-16,BRK,buy,2,"1,234",1.00,USD\n'
    )
    assert _prices(result) == {"NVR": 7450.25, "BRK": 1234.0}


def test_ambiguous_file_keeps_previous_reading() -> None:
    # Sin ninguna celda que delate el separador, se mantiene la lectura de
    # siempre (miles), para no cambiar ficheros que ya se importaban igual.
    result = _preview(
        "Fecha;Ticker;Tipo;Cantidad;Precio;Divisa\n"
        "15/01/2024;NVR;compra;1;7,450;USD\n"
    )
    assert _prices(result) == {"NVR": 7450.0}


def test_inconsistent_file_keeps_cell_reading() -> None:
    # Coma decimal en una fila y punto decimal en otra: no hay criterio de
    # fichero y cada celda se lee como antes.
    result = _preview(
        "Fecha;Ticker;Tipo;Cantidad;Precio;Divisa\n"
        "15/01/2024;AAA;compra;1;12,50;EUR\n"
        "16/01/2024;BBB;compra;1;13.75;EUR\n"
        "17/01/2024;CCC;compra;1;3,450;EUR\n"
    )
    assert _prices(result) == {"AAA": 12.5, "BBB": 13.75, "CCC": 3450.0}
