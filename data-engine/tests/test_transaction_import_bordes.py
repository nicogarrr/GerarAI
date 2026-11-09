"""Bordes de transaction_import_service (TI1): validaciones de commit, deteccion
de columnas y separadores, decodificacion de ficheros y filas con error.

Sin red: en el test de commit real (sobreventa) el getter compartido de Redis se
dobla con None, que el servicio de invalidacion interpreta como "sin cliente
configurado" y no invalida nada (sin clear falso). Sin ficheros reales: los xlsx
y CSV se construyen en memoria. BBDD: SQLite real en los tests de commit (lote
vacio y sobreventa con PortfolioLedgerService real, con commit y rollback
everdaderos); el resto son helpers puros o vista previa sin persistencia.
Los mensajes se comprueban por igualdad estricta donde el servicio los fija; en
el validador pydantic (TransactionImportCommitRequest) el ValueError llega
envuelto en ValidationError y se comprueba el fragmento.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.local_date import local_today
from app.models.entities import Base, Company, Position, Tenant, Transaction
from app.services.transaction_import_service import (
    ParsedTransaction,
    TransactionImportCommitRequest,
    TransactionImportService,
    _excel_cell_text,
    auto_detect_columns,
    detect_decimal_mark,
    parse_file_rows,
    parse_flexible_date,
)


def _tx(**kwargs) -> dict:
    base = {
        "row_number": 7,
        "ticker": "SAN.MC",
        "date": "2024-03-05",
        "action": "buy",
        "quantity": 10.0,
        "price": 3.5,
        "fees": 1.0,
        "currency": "EUR",
    }
    base.update(kwargs)
    return base


# ------------------------------------------------- validador del commit (pydantic)


def test_commit_request_comision_fuera_de_rango() -> None:
    with pytest.raises(ValidationError) as excinfo:
        TransactionImportCommitRequest(transactions=[ParsedTransaction(**_tx(fees=1e20))])
    assert "Fila 7: comisión fuera de rango" in str(excinfo.value)


def test_commit_request_fecha_invalida() -> None:
    with pytest.raises(ValidationError) as excinfo:
        TransactionImportCommitRequest(transactions=[ParsedTransaction(**_tx(date="2024-13-40"))])
    assert "Fila 7: fecha no válida ('2024-13-40')" in str(excinfo.value)


def test_commit_request_fecha_futura() -> None:
    futura = (local_today() + timedelta(days=10)).isoformat()
    with pytest.raises(ValidationError) as excinfo:
        TransactionImportCommitRequest(transactions=[ParsedTransaction(**_tx(date=futura))])
    assert f"Fila 7: la fecha de operación no puede ser futura ({futura})" in str(excinfo.value)


# --------------------------------------------------------------- columnas y marcas


def test_auto_detect_columns_espanol() -> None:
    headers = ["Fecha Operación", "Símbolo", "Tipo", "Cantidad", "Precio", "Comisión", "Moneda"]
    assert auto_detect_columns(headers) == {
        "date": "Fecha Operación",
        "ticker": "Símbolo",
        "action": "Tipo",
        "quantity": "Cantidad",
        "price": "Precio",
        "fees": "Comisión",
        "currency": "Moneda",
    }


def test_detect_decimal_mark_coma_tras_punto() -> None:
    assert detect_decimal_mark(["1.234,56"]) == ","


def test_parse_flexible_date_objeto_date() -> None:
    assert parse_flexible_date(date(2024, 3, 5)) == date(2024, 3, 5)


def test_parse_flexible_date_irreconocible() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_flexible_date("32-13-99")
    assert str(excinfo.value) == "Formato de fecha irreconocible: '32-13-99'"


def test_excel_cell_text_none() -> None:
    assert _excel_cell_text(None) == ""


# ------------------------------------------------------------------ parseo ficheros


def _xlsx_bytes(filas: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for fila in filas:
        ws.append(fila)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_parse_file_rows_excel_omite_filas_vacias() -> None:
    contenido = _xlsx_bytes([[None, None], ["ticker", "price"], ["SAN.MC", 3.5]])
    headers, data_rows = parse_file_rows(contenido, "datos.xlsx")
    assert headers == ["ticker", "price"]
    assert data_rows == [["SAN.MC", "3.5"]]


def test_parse_file_rows_utf16_con_bom() -> None:
    contenido = "ticker,price\nSAN.MC,3.5\n".encode("utf-16")
    headers, data_rows = parse_file_rows(contenido, "datos.csv")
    assert headers == ["ticker", "price"]
    assert data_rows == [["SAN.MC", "3.5"]]


def test_parse_file_rows_latin1_cuando_utf8_falla() -> None:
    contenido = "ticker,concepto\nSAN.MC,caña\n".encode("latin-1")
    headers, data_rows = parse_file_rows(contenido, "datos.csv")
    assert headers == ["ticker", "concepto"]
    assert data_rows == [["SAN.MC", "caña"]]


def test_parse_file_rows_csv_vacio() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_file_rows(b"  \n\n", "datos.csv")
    assert str(excinfo.value) == "El archivo CSV está vacío"


def test_parse_file_rows_separador_tabulador() -> None:
    headers, data_rows = parse_file_rows(b"ticker\tprice\nSAN.MC\t3.5\n", "datos.csv")
    assert headers == ["ticker", "price"]
    assert data_rows == [["SAN.MC", "3.5"]]


def test_parse_file_rows_csv_malformado() -> None:
    # csv.Error determinista: un campo mayor que csv.field_size_limit. Se fija
    # el limite a su valor por defecto (131072) y se restaura el previo al salir,
    # para no depender del valor global que otro proceso haya dejado.
    limite_previo = csv.field_size_limit()
    csv.field_size_limit(131072)
    try:
        contenido = ("ticker,price\n" + "x" * 200000 + ",1\n").encode("utf-8")
        with pytest.raises(ValueError) as excinfo:
            parse_file_rows(contenido, "datos.csv")
        assert (
            str(excinfo.value)
            == "El archivo CSV está mal formado y no se puede leer; guárdalo de nuevo como CSV (UTF-8)"
        )
    finally:
        csv.field_size_limit(limite_previo)


def test_parse_file_rows_sin_registros_validos() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_file_rows(b";;\n;;\n", "datos.csv")
    assert str(excinfo.value) == "El archivo CSV no contiene registros válidos"


# ----------------------------------------------------------------------- preview


_CSV_BASE = "Fecha,Ticker,Tipo,Cantidad,Precio\n2024-03-05,SAN.MC,buy,{cantidad},{precio}\n"


def test_preview_con_custom_mapping() -> None:
    respuesta = TransactionImportService().preview_import(
        _CSV_BASE.format(cantidad=10, precio="3.5").encode("utf-8"),
        "datos.csv",
        custom_mapping={"price": "Precio"},
    )
    assert respuesta.success is True
    assert respuesta.detected_columns["price"] == "Precio"


def test_preview_columna_obligatoria_ausente() -> None:
    contenido = b"Fecha,Ticker,Cantidad\n2024-03-05,SAN.MC,10\n"
    respuesta = TransactionImportService().preview_import(contenido, "datos.csv")
    assert respuesta.success is False
    assert len(respuesta.errors) == 1
    error = respuesta.errors[0]
    assert error.row_number == 0
    assert error.field == "price"
    assert error.message == "No se encontró la columna obligatoria 'price' en la cabecera"


def test_preview_cantidad_cero_en_compra() -> None:
    respuesta = TransactionImportService().preview_import(
        _CSV_BASE.format(cantidad=0, precio="3.5").encode("utf-8"), "datos.csv"
    )
    assert respuesta.success is False
    mensajes = [(e.row_number, e.field, e.message) for e in respuesta.errors]
    assert (2, "quantity", "La cantidad debe ser mayor que cero") in mensajes


def test_preview_precio_no_numerico() -> None:
    respuesta = TransactionImportService().preview_import(
        _CSV_BASE.format(cantidad=10, precio="abc").encode("utf-8"), "datos.csv"
    )
    assert respuesta.success is False
    mensajes = [(e.row_number, e.field, e.message) for e in respuesta.errors]
    assert (2, "price", "Precio no numérico o ausente") in mensajes


# ------------------------------------------------------------------------ commit


def test_commit_sin_transacciones() -> None:
    # La sesion no llega a tocarse: el servicio lanza antes de usar la BBDD.
    sesion = Session(create_engine("sqlite:///:memory:"))
    try:
        with pytest.raises(ValueError) as excinfo:
            TransactionImportService().commit_import(sesion, [])
        assert str(excinfo.value) == "No hay transacciones para importar"
    finally:
        sesion.close()


def test_preview_cantidad_no_numerica() -> None:
    respuesta = TransactionImportService().preview_import(
        _CSV_BASE.format(cantidad="abc", precio="3.5").encode("utf-8"), "datos.csv"
    )
    assert respuesta.success is False
    mensajes = [(e.row_number, e.field, e.message) for e in respuesta.errors]
    assert (2, "quantity", "Cantidad no numérica o ausente") in mensajes


def test_auto_detect_columns_por_subcadena() -> None:
    # Ninguna cabecera es exactamente un alias: solo casa la pasada de subcadena.
    headers = ["Fecha de Compra", "Nemotécnico del Valor", "Cantidad de Títulos", "Precio Unitario Final"]
    assert auto_detect_columns(headers) == {
        "date": "Fecha de Compra",
        "ticker": "Nemotécnico del Valor",
        "quantity": "Cantidad de Títulos",
        "price": "Precio Unitario Final",
    }


# ------------------------------------------------------- commit con SQLite real


@pytest.fixture
def sesion_tenant():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as sesion:
        sesion.add(Tenant(external_id="tenant-ti-bordes", name="Tenant TI Bordes", metadata_={}))
        sesion.commit()
    with factory() as sesion:
        sesion.info["tenant_id"] = "tenant-ti-bordes"
        yield sesion


def test_commit_sobreventa_hace_rollback(sesion_tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    # El commit real dispara la invalidacion de cache en after_commit
    # (cache_invalidation -> invalidate_portfolio_cache -> cache._redis_client ->
    # PING a localhost:6379). Se dobla el getter compartido con None: el servicio
    # lo interpreta como "sin cliente configurado" y no invalida nada (sin clear
    # falso). monkeypatch restaura solo al terminar.
    monkeypatch.setattr("app.core.cache._redis_client", lambda: None)  # noqa: SLF001
    servicio = TransactionImportService()
    compra = ParsedTransaction(
        row_number=2,
        ticker="AAA",
        date="2024-01-05",
        action="buy",
        quantity=10,
        price=3.5,
        fees=0.0,
        currency="EUR",
    )
    assert (
        servicio.commit_import(sesion_tenant, [compra], source_filename="compra.csv")["imported_count"] == 1
    )
    venta = ParsedTransaction(
        row_number=2,
        ticker="AAA",
        date="2024-01-06",
        action="sell",
        quantity=50,
        price=4.0,
        fees=0.0,
        currency="EUR",
    )
    with pytest.raises(ValueError) as excinfo:
        servicio.commit_import(sesion_tenant, [venta], source_filename="venta.csv")
    assert str(excinfo.value) == (
        "Error de sobreventa en cartera durante la importación: "
        "Cannot sell 50.0 AAA: only 10.000000 shares are available on the ledger."
    )
    # El rollback no deja la pata de venta a medias: 0 ventas, la compra retenida
    # y la posicion del ledger coherente con ella (10 titulos de AAA).
    assert sesion_tenant.scalar(select(func.count(Transaction.id)).where(Transaction.action == "sell")) == 0
    assert sesion_tenant.scalar(select(func.count(Transaction.id)).where(Transaction.action == "buy")) == 1
    posicion = sesion_tenant.scalar(
        select(Position).join(Company, Position.company_id == Company.id).where(Company.ticker == "AAA")
    )
    assert posicion is not None
    assert posicion.quantity == Decimal("10")
