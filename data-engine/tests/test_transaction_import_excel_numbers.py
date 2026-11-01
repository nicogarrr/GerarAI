"""Excel: las celdas numéricas no tienen separador ambiguo.

Una celda numérica de Excel (1.234, 12,345 en pantalla) llega como float; antes
se convertía con ``str`` y el lector localizado leía «1.234» como mil
doscientos treinta y cuatro, y «1e-05» como texto no numérico.
"""
import datetime
import io

import openpyxl
import pytest

from app.services.transaction_import_service import TransactionImportService

HEADERS = ["Ticker", "Fecha", "Acción", "Cantidad", "Precio"]


def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    for row in [HEADERS, *rows]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _items(rows: list[list]) -> list[dict]:
    preview = TransactionImportService().preview_import(_xlsx(rows), "cartera.xlsx")
    assert preview.errors == []
    return [item.model_dump() for item in preview.preview_items]


@pytest.mark.parametrize("price", [1.234, 12.345, 999.125, 0.00001, 1234.5])
def test_precio_numerico_de_excel_se_lee_tal_cual(price):
    items = _items([["AAPL", datetime.date(2026, 3, 2), "compra", 10, price]])
    assert items[0]["price"] == pytest.approx(price)


def test_cantidad_numerica_con_tres_decimales():
    items = _items([["AAPL", datetime.date(2026, 3, 2), "compra", 2.125, 50.0]])
    assert items[0]["quantity"] == pytest.approx(2.125)
    assert items[0]["price"] == pytest.approx(50.0)


def test_texto_espanol_junto_a_numeros_de_excel_sigue_igual():
    items = _items(
        [
            ["AAPL", datetime.date(2026, 3, 2), "compra", 10, "3,45"],
            ["MSFT", datetime.date(2026, 3, 3), "compra", 5, 1.234],
        ]
    )
    assert items[0]["price"] == pytest.approx(3.45)
    assert items[1]["price"] == pytest.approx(1.234)
