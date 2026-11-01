"""Los errores del CSV de IBKR citan la fila de la hoja aunque haya filas vacías.

validate_ibkr_csv e import_ibkr_csv descartaban las filas vacías ANTES de
numerar: con una fila en blanco entre operaciones (o «,,,,» de una fila
vaciada en Excel), «Fila 3» señalaba otra fila de la hoja y el usuario
corregía la equivocada. Una celda entrecomillada con salto de línea sigue
siendo una sola fila, como en la hoja de cálculo.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant
from app.services.ibkr_import_service import IBKRImportService, validate_ibkr_csv

HEADER = "symbol,action,quantity,price,date,fees,currency\n"


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="csv-rows-test", name="csv rows")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_fila_vacia_no_desplaza_el_numero():
    text = HEADER + "ZZROWA,buy,10,5,2026-01-02,0,USD\n\n,,,,,,\nZZROWB,buy,x,5,2026-01-02,0,USD\n"
    errors = validate_ibkr_csv(text)
    assert len(errors) == 1
    assert errors[0].startswith("Fila 5 del CSV (ZZROWB)")


def test_lineas_en_blanco_al_principio_cuentan():
    text = "\n\n" + HEADER + "ZZROWB,buy,x,5,2026-01-02,0,USD\n"
    assert validate_ibkr_csv(text)[0].startswith("Fila 4 del CSV (ZZROWB)")


def test_celda_con_salto_de_linea_es_una_fila():
    text = HEADER + 'ZZROWA,buy,10,5,2026-01-02,0,"US\nD"\nZZROWB,buy,x,5,2026-01-02,0,USD\n'
    assert validate_ibkr_csv(text)[0].startswith("Fila 3 del CSV (ZZROWB)")


def test_importacion_omite_y_cita_la_fila_real():
    db = _session()
    text = HEADER + "ZZROWA,buy,10,5,2026-01-02,0,USD\n\nZZROWB,buy,x,5,2026-01-02,0,USD\nZZROWC,buy,2,5,2026-01-03,0,USD\n"
    result = IBKRImportService().import_ibkr_csv(db, text)
    assert result["trades_imported"] == 2
    assert result["rows_skipped"] == 1
    assert [error[:28] for error in result["row_errors"]] == ["Fila 4 del CSV (ZZROWB): la "]
