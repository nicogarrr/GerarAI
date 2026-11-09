"""IBKR import: bordes de validacion y filas sinteticas sin destino.

No se prueba aqui: el guard de carrera por IntegrityError en import_ibkr_csv
(exige una insercion concurrente entre el chequeo previo y el flush; no hay
via sintetica determinista sin parchear el servicio), los manejadores de
csv.Error (el lector csv del servicio no usa strict=True y no lanza con
comillas malformadas; forzarlo exigiria tocar limites internos), el
enriquecimiento opcional de compania (except amplio declarado nosemgrep) ni
los bloqueos de reconciliacion del snapshot (lote aparte). Todo con datos
sinteticos: CSV y XML construidos a mano, SQLite real en memoria, sin red.

Nota de medicion: el rechazo de entidades lo produce el pre-parseo del
wrapper validate_flex_xml (308-309), no el manejador interno de
_validate_flex_xml (334-335), que es defensivo y no se alcanza por la via
publica: esas lineas seguiran sin cubrir. El test verifica el comportamiento
visible: el mensaje exacto de rechazo. (Corregida una version anterior de
esta nota, que atribuia el hueco a un fallo del tracer con excepciones
desde codigo C: falso, lo demostro el auditor.)
"""

from sqlalchemy import create_engine, select

from app.core.database import Base
from app.models import CashBalance, Transaction
from app.services.ibkr_import_service import (
    _XML_ENTITIES_MSG,
    IBKRImportService,
    validate_flex_xml,
    validate_ibkr_csv,
)
from tests.test_ibkr_import import _tenant_session


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = _tenant_session(engine)
    db.info["_engine"] = engine  # se libera en el finally del test que lo use
    return db


def _flex(row):
    return (
        '<FlexQueryResponse queryName="QA" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="QA000" fromDate="2026-10-01" toDate="2026-10-23">'
        f"<CashReport>{row}</CashReport></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def test_validate_flex_xml_vacio():
    assert validate_flex_xml("") == [
        "El fichero está vacío: descarga de nuevo el Flex Query XML desde IBKR (Informes > Flex Queries)."
    ]
    assert validate_flex_xml("   \n ") == [
        "El fichero está vacío: descarga de nuevo el Flex Query XML desde IBKR (Informes > Flex Queries)."
    ]


def test_validate_flex_xml_rechaza_entidades():
    xml = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE FlexQueryResponse [<!ENTITY xxe "boom">]>'
        "<FlexQueryResponse>&xxe;</FlexQueryResponse>"
    )
    assert validate_flex_xml(xml) == [_XML_ENTITIES_MSG]


def test_validate_flex_xml_raiz_desconocida():
    errors = validate_flex_xml("<FooResponse><Bar/></FooResponse>")
    assert errors == [
        "La raíz <FooResponse> no parece un Flex Query de IBKR: no contiene "
        "OpenPosition, Trade, CashTransaction ni CashReport. Revisa que el fichero "
        "sea el XML del Flex Query (no el CSV ni un extracto parcial)."
    ]


def test_validate_flex_xml_raiz_ajena_con_etiquetas_conocidas_continua():
    # Raiz que no es FlexQueryResponse pero contiene etiquetas Flex: la
    # validacion sigue y llega a las filas, que dictan sus propios errores.
    errors = validate_flex_xml("<Foo><Trade/></Foo>")
    assert errors == [
        "Fila 2 (Trade): falta el símbolo (atributo symbol). Esa operación "
        "se omite; revisa que la query incluya la columna Symbol."
    ]


def test_validate_csv_solo_cabecera():
    errors = validate_ibkr_csv("symbol,action,quantity,price,date\n")
    assert errors == [
        "El CSV no contiene filas de datos: debe tener una fila de cabecera "
        "(symbol, action, quantity, price, date) y al menos una operación."
    ]


def test_csv_external_id_demasiado_largo_se_omite():
    csv_text = (
        "symbol,action,quantity,price,date,currency,external_id\n"
        f"ZZUS,buy,1,150,2025-01-10,USD,{'X' * 121}\n"
    )
    db = _db()
    try:
        result = IBKRImportService().import_ibkr_csv(db, csv_text)
        assert result["trades_imported"] == 0
        assert result["rows_skipped"] == 1
        assert any(
            "identificador de operación demasiado largo" in error
            for error in result["row_errors"]
        )
        assert db.scalars(select(Transaction)).all() == []
    finally:
        db.close()
        db.info["_engine"].dispose()


def test_accion_desconocida_se_conserva_y_vacia_es_trade():
    svc = IBKRImportService()
    assert svc._action("HOLD") == "hold"
    assert svc._action("") == "trade"
    assert svc._action(None) == "trade"


def test_cash_report_sin_divisa_se_omite():
    db = _db()
    try:
        result = IBKRImportService().import_flex_xml(
            db, _flex('<CashReportCurrency endingCash="100.00" reportDate="2026-09-25"/>')
        )
        assert result["rows_skipped"] == 1
        assert result["cash_imported"] == 0
        assert db.scalars(select(CashBalance)).all() == []
    finally:
        db.close()
        db.info["_engine"].dispose()
