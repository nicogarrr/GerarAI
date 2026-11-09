"""Pipeline de dos carriles (docling_pipeline): caminos de degradacion y provenance.

Todo hermetico: markitdown/docling se doblan con modulos falsos en sys.modules
o con el ``converter`` inyectable; ningun test descarga modelos ni toca la red.
Los documentos docling son SimpleNamespace con la superficie justa (provenance
best-effort: lo que no se puede leer se declara, nunca rompe el carril).

NO prueba (declarado): docling/markitdown reales, el conversor DocumentConverter
de verdad (linea 488: requiere los ~500 MB de modelos), _doc_page_count con un
objeto cuyo isinstance lanza (387-388, defensivo), el unlink que falla se prueba
con os.unlink doblado (el fichero temporal de ese test queda sin borrar,
declarado), ni la linea 703 del orquestador (defensiva: todo camino al fallback
ya lleva un warning con «pypdf»).
"""

from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace

import pytest

import app.services.docling_pipeline as dp
from app.services.document_ingestion_service import ParsedBlock


def test_env_int_invalido_o_negativo_cae_al_default(monkeypatch):
    monkeypatch.setenv("CAVAAI_DOCLING_TABLE_MIN_PIPE_LINES", "no-es-numero")
    assert dp.table_min_pipe_lines() == 3
    monkeypatch.setenv("CAVAAI_DOCLING_TABLE_MIN_PIPE_LINES", "5")
    assert dp.table_min_pipe_lines() == 5
    monkeypatch.setenv("CAVAAI_DOCLING_SCANNED_MIN_CHARS", "-2")
    assert dp.scanned_min_chars() == 0  # max(0, ...) acota por abajo


def test_bounded_image_pixels_sin_pillow_no_hace_nada(monkeypatch):
    """Pillow ausente: el contexto no acota nada y no rompe."""
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)
    with dp._bounded_image_pixels():
        pass
    assert dp._PIL_DEPTH == 0
    assert dp._PIL_SAVED is None


def test_count_table_pipe_lines_sin_separador_exige_densidad():
    """Pipes sueltos sin fila separadora GFM: hace falta el doble del umbral."""
    cuatro = "\n".join(f"fila | con | pipe {i}" for i in range(4))
    siete = "\n".join(f"fila | con | pipe {i}" for i in range(7))
    assert dp.count_table_pipe_lines(cuatro) == 0  # 4 < 3*2: texto con pipes
    assert dp.count_table_pipe_lines(siete) == 7   # densidad suficiente


def test_detect_xbrl_por_nombre_y_por_content_type():
    assert dp.detect_xbrl(b"<datos/>", "filing_htm.xml") is True
    assert dp.detect_xbrl(b"<datos/>", "informe", "application/xml") is True
    assert dp.detect_xbrl(b"texto plano", "nota.txt", "text/plain") is False


def test_extract_xbrl_facts_fact_roto_no_tira_el_resto(monkeypatch):
    """Un fact cuyos campos lanzan se omite y los demas se serializan."""
    from app.services.connectors import sec_xbrl_instance

    bueno = SimpleNamespace(tag="Assets", value=123, start=None, end=None,
                            instant=None, members=[])

    class _Roto:
        @property
        def tag(self):
            raise ValueError("fact roto")

    monkeypatch.setattr(sec_xbrl_instance, "parse_instance_dimensioned_facts",
                        lambda stream: [_Roto(), bueno])
    (fact,) = dp.extract_xbrl_facts(b"<xbrl/>")
    assert fact["tag"] == "Assets"
    assert fact["value"] == "123"
    assert fact["start"] is None and fact["end"] is None and fact["instant"] is None
    assert fact["members"] == []


def _markitdown_falso(monkeypatch, resultado=None, falla=None):
    modulo = types.ModuleType("markitdown")

    class _MarkItDown:
        def convert_stream(self, stream, file_extension=None):
            if falla is not None:
                raise falla
            return resultado

    modulo.MarkItDown = _MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", modulo)


def test_convert_fast_markitdown_usa_text_content_si_no_hay_markdown(monkeypatch):
    _markitdown_falso(monkeypatch, resultado=SimpleNamespace(
        markdown=None, text_content="texto del documento"))
    assert dp.convert_fast_markitdown(b"pdf", "x.pdf", ".pdf") == "texto del documento"


def test_convert_fast_markitdown_fallo_es_lane_failed(monkeypatch):
    _markitdown_falso(monkeypatch, falla=RuntimeError("pdf roto"))
    with pytest.raises(dp._LaneFailed, match="MarkItDown fallo.*RuntimeError"):
        dp.convert_fast_markitdown(b"pdf", "x.pdf", ".pdf")


def test_convert_fast_markitdown_vacio_es_lane_failed(monkeypatch):
    _markitdown_falso(monkeypatch, resultado=SimpleNamespace(markdown="   "))
    with pytest.raises(dp._LaneFailed, match="texto vacio"):
        dp.convert_fast_markitdown(b"pdf", "x.pdf", ".pdf")


def test_doc_page_count_variantes():
    assert dp._doc_page_count(SimpleNamespace(pages={1: None, 2: None})) == 2
    assert dp._doc_page_count(SimpleNamespace(pages=["a", "b", "c"])) == 3
    assert dp._doc_page_count(SimpleNamespace(pages=7)) == 7
    assert dp._doc_page_count(SimpleNamespace(pages="no es un conteo")) is None
    assert dp._doc_page_count(SimpleNamespace(pages=None)) is None


def test_prov_page_salta_entradas_invalidas_y_respeta_el_orden():
    item = SimpleNamespace(prov=[SimpleNamespace(page_no="no-int"),
                                 SimpleNamespace(page_no=3)])
    assert dp._prov_page(item) == 3
    assert dp._prov_page(SimpleNamespace(prov=[SimpleNamespace(page_no=0)])) is None
    assert dp._prov_page(SimpleNamespace(prov=5)) is None  # no iterable: best-effort
    assert dp._prov_page(SimpleNamespace(prov=None)) is None


def test_table_inventory_documento_reacio_devuelve_vacio():
    class _TablasReacias:
        def __iter__(self):
            raise RuntimeError("tablas ilegibles")

    assert dp._table_inventory(SimpleNamespace(tables=_TablasReacias())) == []


def test_table_markdown_segundo_intento_y_fallback_declarado():
    """export_to_markdown(doc) falla o devuelve vacio: se prueba sin argumentos;
    si ninguno sirve, el bloque declara que el export no esta disponible."""
    doc = SimpleNamespace()

    class _SegundoIntento:
        def export_to_markdown(self, *args):
            if args:
                raise TypeError("firma antigua")
            return " | a | b |\n | --- | --- |\n | 1 | 2 |"

    assert dp._table_markdown(_SegundoIntento(), doc, "#/tables/0").startswith("| a |")

    class _VacioPrimero:
        def export_to_markdown(self, *args):
            return "   " if args else " | c |\n | --- |\n | 3 |"

    assert dp._table_markdown(_VacioPrimero(), doc, "#/tables/1").startswith("| c |")

    class _NadaFunciona:
        def export_to_markdown(self, *args):
            raise RuntimeError("sin export")

    texto = dp._table_markdown(_NadaFunciona(), doc, "#/tables/2")
    assert "export no disponible" in texto
    assert "#/tables/2" in texto


def test_iter_docling_items_superficie_antigua_y_errores():
    """Sin iterate_items: textos y tablas como atributos; sin nada: _LaneFailed."""
    texto, tabla = SimpleNamespace(text="hola"), SimpleNamespace(text="tabla")
    doc_antiguo = SimpleNamespace(iterate_items=None, texts=[texto], tables=[tabla])
    assert dp._iter_docling_items(doc_antiguo) == [(texto, 0), (tabla, 0)]

    with pytest.raises(dp._LaneFailed, match="sin items iterables"):
        dp._iter_docling_items(SimpleNamespace(iterate_items=None, texts=[], tables=[]))

    def _iterador_roto():
        raise RuntimeError("iterador roto")
        yield  # pragma: no cover

    doc_roto = SimpleNamespace(iterate_items=_iterador_roto)
    with pytest.raises(dp._LaneFailed, match="iterate_items fallo"):
        dp._iter_docling_items(doc_roto)


def test_blocks_from_docling_document_salta_items_sin_texto():
    """Items sin texto util se saltan; si no queda nada, _LaneFailed para que
    el orquestador degrade a pypdf."""
    tabla = SimpleNamespace(prov=[SimpleNamespace(page_no=2)],
                            label=SimpleNamespace(value="Table"),
                            data=SimpleNamespace(num_rows=2, num_cols=2))
    vacio = SimpleNamespace(prov=[], label=None, data=None, text="  ")
    doc = SimpleNamespace(
        iterate_items=lambda: iter([(tabla, 0), (vacio, 0)]),
        tables=[tabla], pages={1: None, 2: None},
    )
    tabla.export_to_markdown = lambda *a: " | x |\n | --- |\n | 1 |"
    blocks, info = dp._blocks_from_docling_document(doc)
    (bloque,) = blocks  # el item vacio no genera bloque
    assert bloque.metadata["extraction_lane"] == "docling"
    assert bloque.metadata["page"] == 2
    assert bloque.metadata["table_id"] == "#/tables/0"
    assert info["page_count"] == 2
    assert info["tables"][0]["rows"] == 2

    doc_vacio = SimpleNamespace(
        iterate_items=lambda: iter([(vacio, 0)]), tables=[], pages={},
    )
    with pytest.raises(dp._LaneFailed, match="sin texto ni tablas|no extrajo"):
        dp._blocks_from_docling_document(doc_vacio)


def test_convert_heavy_docling_resultado_sin_documento():
    """converter inyectable cuyo resultado no trae document: _LaneFailed."""
    convertido = SimpleNamespace(document=None)
    converter = SimpleNamespace(convert=lambda path: convertido)
    with pytest.raises(dp._LaneFailed, match="sin documento"):
        dp.convert_heavy_docling(b"pdf", "x.pdf", ".pdf", converter=converter)


def test_convert_heavy_docling_limpieza_con_unlink_caido(monkeypatch):
    """El borrado del temporal falla: el carril devuelve los bloques igual
    (la limpieza es best-effort). El temporal de este test queda sin borrar."""
    item = SimpleNamespace(prov=[], label=None, data=None, text="contenido util")
    doc = SimpleNamespace(iterate_items=lambda: iter([(item, 0)]), tables=[], pages=1)
    converter = SimpleNamespace(convert=lambda path: SimpleNamespace(document=doc))

    def _unlink_caido(path):
        raise OSError("sin permisos")

    monkeypatch.setattr(os, "unlink", _unlink_caido)
    blocks, info = dp.convert_heavy_docling(b"pdf", "x.pdf", ".pdf",
                                            converter=converter)
    assert [b.text for b in blocks] == ["contenido util"]
    assert info["page_count"] == 1


def test_fast_blocks_solo_separadores_es_lane_failed():
    with pytest.raises(dp._LaneFailed, match="texto vacio"):
        dp._fast_blocks("\x0c \x0c")


def test_parse_pdf_two_lane_markitdown_caido_degrada_a_pypdf(monkeypatch):
    """MarkItDown presente pero el PDF le rompe el conversor: warning trazable
    y carril pypdf (PDF real de una pagina en blanco generado con pypdf)."""
    from io import BytesIO

    from pypdf import PdfWriter

    _markitdown_falso(monkeypatch, falla=RuntimeError("pdf roto"))
    buffer = BytesIO()
    escritor = PdfWriter()
    escritor.add_blank_page(width=612, height=792)
    escritor.write(buffer)
    resultado = dp.parse_pdf_two_lane(buffer.getvalue(), "blanco.pdf", ".pdf")
    assert resultado.parser == "pypdf"
    assert any("MarkItDown fallo" in warning for warning in resultado.warnings)


def _flags(monkeypatch, **flags):
    base = {"markitdown_enabled": True, "docling_lane_enabled": True,
            "docling_async_only": True, "docling_opt_in": False}
    base.update(flags)
    monkeypatch.setattr(dp, "lane_flags", lambda: base)


def test_parse_pdf_two_lane_carril_pesado_apagado_se_declara(monkeypatch):
    """Estructura XBRL detectada con DOCLING_LANE_ENABLED=0: warning declarado,
    sin intento pesado, y el PDF falso cae al fallback con warning de pypdf."""
    _flags(monkeypatch, markitdown_enabled=False, docling_lane_enabled=False)
    resultado = dp.parse_pdf_two_lane(b"<xbrl datos", "filing.pdf", ".pdf")
    assert resultado.parser == "pypdf"
    assert any("MARKITDOWN_ENABLED=0" in warning for warning in resultado.warnings)
    assert any("DOCLING_LANE_ENABLED=0" in warning for warning in resultado.warnings)
    assert any("pypdf fallo" in warning for warning in resultado.warnings)
    assert any("XBRL detectado pero sin facts" in warning
               for warning in resultado.warnings)


def test_parse_pdf_two_lane_pesado_sin_tablas_no_inventa_conteo(monkeypatch):
    """El intento pesado tiene exito sin tablas: no hay warning de conteo de
    tablas (la rama 664->669)."""
    _flags(monkeypatch)
    monkeypatch.setattr(dp, "convert_heavy_docling", lambda *a, **k: (
        [ParsedBlock(text="texto estructurado", metadata={"extraction_lane": "docling",
                                                          "page": 1})],
        {"page_count": 1, "tables": []},
    ))
    resultado = dp.parse_pdf_two_lane(b"<xbrl datos", "filing.pdf", ".pdf",
                                      allow_heavy=True)
    assert resultado.parser == "docling"
    assert not any("tabla(s)" in warning for warning in resultado.warnings)
