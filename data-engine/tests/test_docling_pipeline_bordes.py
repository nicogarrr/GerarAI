"""docling_pipeline: remate de bordes (370, 387-388, 488 y 635 sobre main).

Hermetico: markitdown/docling se doblan con modulos falsos en sys.modules y el
conversor pesado con una clase falsa espia (conteos exactos de init/convert).
Ningun test descarga modelos ni toca la red. El temporal del carril docling se
escribe y borra de verdad en el fs.

NO prueba (declarado):
- Linea 703 del orquestador (warnings.append("Carril pypdf clasico.")):
  inalcanzable por la via publica; verificado leyendo parse_pdf_two_lane — todo
  camino hasta el fallback ya arrastra un warning con «pypdf» (markitdown
  ausente, fallo o palabras pegadas, MARKITDOWN_ENABLED=0, intento pesado
  degradado, o el propio fallo de pypdf), asi que el guarda `not any(...)` la
  deja sin ejecutar.
- Ramas 129->exit y 135->exit: cuerpos "..." de los Protocols (declaraciones
  de tipo), no ejecutables.
- Docling/markitdown reales: dependencias no instaladas en este entorno.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

import app.services.docling_pipeline as dp


def _markitdown_falso(monkeypatch, resultado=None, falla=None):
    modulo = types.ModuleType("markitdown")

    class _MarkItDown:
        def convert_stream(self, stream, file_extension=None):
            if falla is not None:
                raise falla
            return resultado

    modulo.MarkItDown = _MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", modulo)


def _flags(monkeypatch, **flags):
    base = {"markitdown_enabled": True, "docling_lane_enabled": True,
            "docling_async_only": True, "docling_opt_in": False}
    base.update(flags)
    monkeypatch.setattr(dp, "lane_flags", lambda: base)


def test_convert_fast_markitdown_lane_unavailable_se_propaga_sin_envolver(monkeypatch):
    """Linea 370: un _LaneUnavailable del interior del try se re-lanza tal cual
    (no se envuelve en _LaneFailed)."""
    _markitdown_falso(monkeypatch, falla=dp._LaneUnavailable("dependencia ausente"))
    with pytest.raises(dp._LaneUnavailable) as excinfo:
        dp.convert_fast_markitdown(b"pdf", "x.pdf", ".pdf")
    assert str(excinfo.value) == "dependencia ausente"


def test_doc_page_count_dict_cuyo_len_lanza_devuelve_none():
    """Lineas 387-388: isinstance pasa pero len() lanza; provenance best-effort
    devuelve None en vez de romper."""

    class _PaginasExplosivas(dict):
        def __len__(self):
            raise RuntimeError("boom")

    assert dp._doc_page_count(SimpleNamespace(pages=_PaginasExplosivas())) is None


def test_convert_heavy_docling_sin_converter_instancia_document_converter_una_vez(monkeypatch):
    """Linea 488: sin converter inyectado se importa docling y se construye
    DocumentConverter exactamente una vez; el temporal se escribe y se borra."""
    llamadas = {"init": 0, "convert": 0}
    paquete = types.ModuleType("docling")
    submodulo = types.ModuleType("docling.document_converter")

    class _DocumentConverter:
        def __init__(self):
            llamadas["init"] += 1

        def convert(self, path):
            llamadas["convert"] += 1
            return SimpleNamespace(
                document=SimpleNamespace(texts=[], furniture=[], tables=[])
            )

    submodulo.DocumentConverter = _DocumentConverter
    paquete.document_converter = submodulo
    monkeypatch.setitem(sys.modules, "docling", paquete)
    monkeypatch.setitem(sys.modules, "docling.document_converter", submodulo)

    with pytest.raises(dp._LaneFailed, match="sin items iterables"):
        dp.convert_heavy_docling(b"pdf", "x.pdf", ".pdf")
    assert llamadas == {"init": 1, "convert": 1}


def test_parse_pdf_two_lane_opt_in_fuerza_carril_pesado_sobre_markdown_limpio(monkeypatch):
    """Linea 635: markdown rapido limpio (decision plain -> carril rapido) pero
    docling_opt_in activo re-decide al carril pesado."""
    markdown_limpio = " ".join(["parrafo"] * 120)  # 960 chars, sin '|', sin pegar
    _markitdown_falso(monkeypatch, resultado=SimpleNamespace(markdown=markdown_limpio))
    _flags(monkeypatch, docling_opt_in=True)
    documento = SimpleNamespace(
        texts=[SimpleNamespace(text="texto del carril pesado", prov=[])],
        furniture=[],
        tables=[],
    )
    converter = SimpleNamespace(
        convert=lambda path: SimpleNamespace(document=documento)
    )
    parsed = dp.parse_pdf_two_lane(
        b"%PDF-1.4 fake", "filing.pdf", allow_heavy=True, converter=converter
    )
    assert parsed.parser == dp.LANE_DOCLING
    assert [block.text for block in parsed.blocks] == ["texto del carril pesado"]
