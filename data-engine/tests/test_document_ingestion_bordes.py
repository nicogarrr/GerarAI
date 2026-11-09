"""Bordes residuales de document_ingestion_service: XLSX nivel 2 y flush de chunks.

XLSX real construido con openpyxl (el escaneo ZIP de nivel 1 ya lo cubre
tests/test_document_ingestion_parsers.py); aqui load_workbook va doblado con
un libro falso para alcanzar los limites de hojas/dimensiones del segundo
nivel sin montar libros gigantes. El flush de chunks se prueba por llamada
directa a _chunk_blocks con ParsedBlock sinteticos (misma convencion que
test_document_ingestion_parsers.py).

NO prueba (declarado):
- 401-403, encolado KPI al worker LLM (CAVAAI_ENABLE_AUTO_KPI_EXTRACTION):
  la casa ya lo declara saltado a proposito en test_document_ingestion_caminos.py
  por tocar el pipeline LLM; no se ejerce ni el worker ni el LLM.
- Arco 712->715 de _chunk_blocks (piece vacio al salir del bucle):
  inalcanzable. Se entra en esa rama solo con len(text) > max_chars >= 1,
  y cualquier texto no vacio produce splitlines() no vacio; el bucle siempre
  deja piece con al menos el ultimo elemento (tras cada split-flush vuelve a
  piece.append(line)). Verificado con inputs de fuzzing manual (saltos,
  cortes exactos, lineas largas).
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.services.document_ingestion_service import DocumentIngestionService, ParsedBlock


def _xlsx_bytes() -> bytes:
    """XLSX real minimo: una hoja, una celda. Nivel 1 (ZIP) debe dejarlo pasar."""
    libro = Workbook()
    libro.active["A1"] = "dato"
    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def test_xlsx_segundo_nivel_rechaza_demasiadas_hojas(monkeypatch):
    """627: len(worksheets) > MAX_XLSX_SHEETS aborta con mensaje exacto."""
    import openpyxl

    monkeypatch.setattr(
        openpyxl, "load_workbook",
        lambda *a, **k: SimpleNamespace(
            worksheets=[SimpleNamespace()] * 101, close=lambda: None
        ),
    )
    with pytest.raises(
        ValueError, match=r"El XLSX tiene demasiadas hojas para ingerirlo"
    ):
        DocumentIngestionService()._parse_xlsx(_xlsx_bytes())


def test_xlsx_segundo_nivel_rechaza_dimensiones(monkeypatch):
    """632: una hoja con max_row > MAX_XLSX_ROWS aborta con mensaje exacto."""
    import openpyxl

    hoja = SimpleNamespace(max_row=60_000, max_column=3)
    monkeypatch.setattr(
        openpyxl, "load_workbook",
        lambda *a, **k: SimpleNamespace(worksheets=[hoja], close=lambda: None),
    )
    with pytest.raises(
        ValueError, match=r"Las dimensiones del XLSX superan el limite de ingesta"
    ):
        DocumentIngestionService()._parse_xlsx(_xlsx_bytes())


def test_chunk_flush_descarta_acumulado_que_compacta_vacio():
    """668-670: un flush sobre acumulado de solo blancos limpia y sigue.

    Con max_chars=3, el bloque largo entra en el corte por lineas: tras el
    primer split-flush, la linea en blanco interna reinicia piece con una
    cadena vacia y la siguiente linea larga fuerza un flush cuyo acumulado es
    solo "\n" -> _compact lo deja vacio y se descarta sin emitir chunk.
    La primera llamada a flush() con acumulado vacio (664-665) tambien queda
    ejercitada.
    """
    servicio = DocumentIngestionService()
    bloques = [ParsedBlock(text="abc\n\nwxyz", metadata={"f": 1})]
    chunks = servicio._chunk_blocks(bloques, "checksum", "parser", "f.txt", None, max_chars=3)
    assert [c["text"] for c in chunks] == ["abc", "wxy", "z"]


def test_chunk_texto_corto_multi_bloque_sin_descarte():
    """Contraste del flush: acumulado con contenido real emite su chunk (666-686)."""
    servicio = DocumentIngestionService()
    bloques = [ParsedBlock(text="bloque unico", metadata={"f": 1})]
    chunks = servicio._chunk_blocks(bloques, "chk", "parser", "f.txt", None)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "bloque unico"
    assert chunks[0]["metadata"]["checksum"] == "chk"
