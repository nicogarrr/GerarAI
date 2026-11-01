"""Importar operaciones: una compra a precio 0 o con el año 0001 entraba sin aviso.

Una compra a 0 deja la posición con coste 0 (toda venta futura sería
ganancia) y «0001-01-01» es un año mal escrito. Ahora la fila se rechaza con
un error claro; un dividendo a 0 y una venta a 0 siguen como antes.
"""

from app.services.transaction_import_service import TransactionImportService

HEADER = "Date,Ticker,Action,Quantity,Price\n"


def _preview(rows: str):
    return TransactionImportService().preview_import((HEADER + rows).encode("utf-8"), "ops.csv")


def test_compra_a_precio_cero_se_rechaza():
    res = _preview("2026-10-01,AAPL,buy,10,0\n")
    assert res.valid_rows_count == 0
    assert res.invalid_rows_count == 1
    assert any(
        e.field == "price" and e.message == "El precio de una compra debe ser mayor que cero" for e in res.errors
    )


def test_compra_sin_columna_de_accion_a_cero_se_rechaza():
    data = "Date,Ticker,Quantity,Price\n2026-10-01,AAPL,10,0\n"
    res = TransactionImportService().preview_import(data.encode("utf-8"), "ops.csv")
    assert res.valid_rows_count == 0
    assert any(e.field == "price" for e in res.errors)


def test_venta_a_cero_sigue_entrando():
    res = _preview("2026-10-01,AAPL,sell,10,0\n")
    assert res.valid_rows_count == 1


def test_anio_0001_se_rechaza():
    res = _preview("0001-01-01,AAPL,buy,10,150\n")
    assert res.valid_rows_count == 0
    msgs = [e.message for e in res.errors if e.field == "date"]
    assert msgs == ["La fecha de operación es anterior a 1900 (0001-01-01): revisa el año"]


def test_anio_mal_escrito_con_barras_se_rechaza():
    res = _preview("15/03/0201,AAPL,buy,10,150\n")
    assert res.valid_rows_count == 0
    assert any("revisa el año" in e.message for e in res.errors if e.field == "date")


def test_fechas_antiguas_reales_siguen_entrando():
    res = _preview("1999-12-31,AAPL,buy,10,150\n1900-01-02,KO,buy,1,10\n")
    assert res.valid_rows_count == 2
