"""Un Excel con demasiadas filas dice el límite real, no «Error al leer el archivo Excel»."""

from __future__ import annotations

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    sheet = wb.active
    for row in rows:
        sheet.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_con_demasiadas_filas_dice_el_limite(monkeypatch):
    import app.services.transaction_import_service as svc

    monkeypatch.setattr(svc, "MAX_IMPORT_ROWS", 3)
    data = _xlsx([["ticker", "date", "quantity", "price"]] + [["DEMO", "2026-01-05", 1, 10]] * 4)

    with pytest.raises(ValueError) as exc:
        svc.parse_file_rows(data, "demo.xlsx")

    assert str(exc.value) == "El archivo supera el máximo de 3 filas; divídelo en varios lotes"


def test_excel_vacio_dice_que_no_tiene_filas():
    import app.services.transaction_import_service as svc

    with pytest.raises(ValueError) as exc:
        svc.parse_file_rows(_xlsx([]), "vacio.xlsx")

    assert str(exc.value) == "El archivo Excel no contiene filas con datos"


def test_excel_en_el_limite_se_lee_entero(monkeypatch):
    import app.services.transaction_import_service as svc

    monkeypatch.setattr(svc, "MAX_IMPORT_ROWS", 3)
    headers, rows = svc.parse_file_rows(
        _xlsx([["ticker", "date", "quantity", "price"]] + [["DEMO", "2026-01-05", 1, 10]] * 3), "ok.xlsx",
    )

    assert headers == ["ticker", "date", "quantity", "price"]
    assert len(rows) == 3


def test_excel_corrupto_sigue_siendo_un_error_de_lectura():
    import app.services.transaction_import_service as svc

    with pytest.raises(ValueError) as exc:
        svc.parse_file_rows(b"PK\x03\x04 no es un xlsx", "roto.xlsx")

    assert "XLSX" in str(exc.value) or "Error al leer el archivo Excel" in str(exc.value)
