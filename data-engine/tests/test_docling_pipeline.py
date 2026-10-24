"""Tests hermeticos del pipeline de ingesta en dos carriles.

NUNCA descargan los ~500 MB de modelos: el `DocumentConverter` se inyecta
falso (`converter=`) y MarkItDown se sustituye en `sys.modules`. Se testea:
decision de carril, provenance por chunk (lane/page/table_id), fallback con
dependencia ausente, fallback cuando Docling lanza, y que el shape de chunks
(dedupe por hash + claves que consumen Qdrant/KG/principios) no cambio.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import app.services.docling_pipeline as pipeline
from app.services.docling_pipeline import (
    LaneDecision,
    count_table_pipe_lines,
    decide_lane,
    detect_xbrl,
    docling_heavy_context,
    extract_xbrl_facts,
    heavy_lane_allowed,
    lane_flags,
    parse_pdf_two_lane,
    resolve_allow_heavy,
)
from app.services.document_ingestion_service import DocumentIngestionService

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "docling_two_page.pdf"

PLAIN_MD = (
    "# Nota trimestral\n\n"
    "Revenue grew twelve percent with margin discipline across the portfolio. "
    "Management guides prudently and allocates capital with patience. "
    "Risks include cyclicality and customer concentration over time.\n\n"
    "Second paragraph with enough trailing content to clear the scanned floor easily."
)

TABLE_MD = (
    "# Financial summary\n\n"
    "Revenue grew twelve percent with margin discipline across the portfolio.\n\n"
    "| metric | 2024 | 2025 |\n"
    "| --- | --- | --- |\n"
    "| revenue | 100 | 112 |\n"
    "| margin | 20% | 22% |\n"
)

INSTANCE_XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2023"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <context id="c1"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="d">us-gaap:CommonClassAMember</explicitMember></segment></entity>
    <period><startDate>2024-10-01</startDate><endDate>2025-09-30</endDate></period></context>
  <unit id="usdPerShare"><divide><unitNumerator><measure>iso4217:USD</measure></unitNumerator>
    <unitDenominator><measure>shares</measure></unitDenominator></divide></unit>
  <us-gaap:EarningsPerShareDiluted contextRef="c1" unitRef="usdPerShare">10.20</us-gaap:EarningsPerShareDiluted>
</xbrl>
"""


def _install_fake_markitdown(monkeypatch, markdown: str):
    """Sustituye el modulo markitdown por un falso determinista."""
    fake = ModuleType("markitdown")

    class _FakeResult:
        def __init__(self, text: str) -> None:
            self.markdown = text

    class _FakeMarkItDown:
        def convert_stream(self, stream, file_extension=None):  # noqa: ARG002
            return _FakeResult(markdown)

    fake.MarkItDown = _FakeMarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    return fake


def _drop_optional_deps(monkeypatch):
    """Simula dependencias no instaladas: el import perezoso debe degradar."""
    monkeypatch.setitem(sys.modules, "markitdown", None)
    monkeypatch.setitem(sys.modules, "docling", None)
    monkeypatch.setitem(sys.modules, "docling.document_converter", None)


def _docling_item(text="", *, page=None, table=False, table_id=None):
    prov = [SimpleNamespace(page_no=page)] if page else []
    item = SimpleNamespace(
        text=text,
        label=SimpleNamespace(value="table" if table else "text"),
        prov=prov,
        self_ref=table_id,
        data=SimpleNamespace(num_rows=2, num_cols=3) if table else None,
    )
    if table:
        item.export_to_markdown = lambda doc=None: "| metric | 2024 |\n| --- | --- |\n| revenue | 112 |"
    return item


def _fake_converter(*items):
    table_seen = 0
    tables = []
    for item, _level in items:
        if getattr(getattr(item, "label", None), "value", "") == "table":
            if item.self_ref is None:
                item.self_ref = f"#/tables/{table_seen}"
            tables.append(item)
            table_seen += 1
    doc = SimpleNamespace(
        pages={1: object(), 2: object()},
        tables=tables,
        iterate_items=lambda: list(items),
    )
    return SimpleNamespace(convert=lambda path: SimpleNamespace(document=doc))


def test_imports_are_lazy_and_never_raise_without_optional_deps():
    assert "docling" not in sys.modules
    assert "docling.document_converter" not in sys.modules
    assert "markitdown" not in sys.modules
    # Re-importar los modulos no exige las dependencias opcionales.
    import importlib

    importlib.reload(pipeline)
    assert "docling" not in sys.modules


def test_decide_lane_plain_goes_fast():
    decision = decide_lane(PLAIN_MD)
    assert decision.lane == "markitdown"


def test_decide_lane_tables_go_docling():
    decision = decide_lane(TABLE_MD)
    assert decision.lane == "docling"
    assert decision.table_pipe_lines >= 3
    assert "tables-detected" in decision.reason


def test_decide_lane_empty_fast_goes_pypdf():
    assert decide_lane(None).lane == "pypdf"
    assert decide_lane("   ").lane == "pypdf"


def test_decide_lane_scanned_goes_docling():
    decision = decide_lane("tiny")
    assert decision.lane == "docling"
    assert decision.scanned is True


def test_decide_lane_xbrl_goes_docling():
    decision = decide_lane(PLAIN_MD, xbrl_detected=True)
    assert decision.lane == "docling"
    assert decision.xbrl_detected is True


def test_decide_lane_threshold_is_env_tunable(monkeypatch):
    assert decide_lane(TABLE_MD).lane == "docling"
    monkeypatch.setenv("CAVAAI_DOCLING_TABLE_MIN_PIPE_LINES", "1000")
    assert decide_lane(TABLE_MD).lane == "markitdown"


def test_count_table_pipe_lines_ignores_loose_pipes():
    assert count_table_pipe_lines("a | b\nc | d\n") == 0
    assert count_table_pipe_lines(TABLE_MD) >= 3


def test_fast_lane_plain_pdf_uses_markitdown(monkeypatch):
    _install_fake_markitdown(monkeypatch, PLAIN_MD)
    parsed = parse_pdf_two_lane(b"%PDF-1.4 fake", "note.pdf", allow_heavy=False)
    assert parsed.parser == "markitdown"
    assert parsed.blocks
    assert all(block.metadata["extraction_lane"] == "markitdown" for block in parsed.blocks)
    assert all(block.metadata["page"] is None for block in parsed.blocks)


def test_fast_lane_uses_form_feed_page_breaks(monkeypatch):
    page_one = "page one text here with enough trailing content to clear any floor. " * 3
    page_two = "page two text here with enough trailing content to clear any floor. " * 3
    _install_fake_markitdown(monkeypatch, f"{page_one}\n\n\x0c\n{page_two}")
    parsed = parse_pdf_two_lane(b"%PDF-1.4 fake", "note.pdf", allow_heavy=False)
    assert parsed.parser == "markitdown"
    assert {block.metadata["page"] for block in parsed.blocks} == {1, 2}


def test_heavy_lane_tables_with_page_provenance(monkeypatch):
    _install_fake_markitdown(monkeypatch, TABLE_MD)
    converter = _fake_converter(
        (_docling_item("Intro revenue text here.", page=1), 0),
        (_docling_item("", page=2, table=True), 0),
        (_docling_item("Closing remark on margins.", page=2), 0),
    )
    parsed = parse_pdf_two_lane(
        b"%PDF-1.4 fake", "filing.pdf", allow_heavy=True, converter=converter
    )
    assert parsed.parser == "docling"
    lanes = {block.metadata["extraction_lane"] for block in parsed.blocks}
    assert lanes == {"docling"}
    pages = {block.metadata["page"] for block in parsed.blocks}
    assert pages == {1, 2}
    tables = [block for block in parsed.blocks if "table_id" in block.metadata]
    assert len(tables) == 1
    assert tables[0].metadata["table_id"] == "#/tables/0"
    assert tables[0].metadata["page"] == 2
    assert any("tabla" in warning for warning in parsed.warnings)


def test_sync_path_defers_and_never_builds_converter(monkeypatch):
    _install_fake_markitdown(monkeypatch, TABLE_MD)
    converter = Mock()
    parsed = parse_pdf_two_lane(
        b"%PDF-1.4 fake", "filing.pdf", allow_heavy=False, converter=converter
    )
    converter.convert.assert_not_called()
    assert parsed.parser == "markitdown"
    assert any("diferido" in warning for warning in parsed.warnings)


def test_missing_deps_fall_back_to_pypdf_with_traceable_warning(monkeypatch):
    _drop_optional_deps(monkeypatch)
    content = FIXTURE_PDF.read_bytes()
    # Incluso el worker degrada si no hay nada instalado: nunca 500 opaco.
    parsed = parse_pdf_two_lane(content, "filing.pdf", allow_heavy=True)
    assert parsed.parser == "pypdf"
    assert {block.metadata["page"] for block in parsed.blocks} == {1, 2}
    assert all(block.metadata["extraction_lane"] == "pypdf" for block in parsed.blocks)
    joined = " ".join(parsed.warnings)
    assert "markitdown no instalado" in joined
    assert "docling no instalado" in joined


def test_docling_failure_serves_fast_lane_and_traces(monkeypatch):
    _install_fake_markitdown(monkeypatch, TABLE_MD)
    converter = Mock()
    converter.convert.side_effect = RuntimeError(" layout model OOM (simulado)")
    parsed = parse_pdf_two_lane(
        b"%PDF-1.4 fake", "filing.pdf", allow_heavy=True, converter=converter
    )
    assert parsed.parser == "markitdown"
    assert any("Docling fallo" in warning for warning in parsed.warnings)


def test_docling_failure_without_fast_lane_ends_in_pypdf(monkeypatch):
    # Sin pre-filtro pero con XBRL, la decision es Docling; si el conversor
    # falla, el terminal es pypdf (con el bloque de facts XBRL adjunto).
    _drop_optional_deps(monkeypatch)
    converter = Mock()
    converter.convert.side_effect = RuntimeError("layout OOM (simulado)")
    parsed = parse_pdf_two_lane(
        INSTANCE_XML.encode(), "filing.pdf", allow_heavy=True, converter=converter
    )
    converter.convert.assert_called_once()
    assert parsed.parser == "pypdf"
    assert any("Docling fallo" in warning for warning in parsed.warnings)
    assert any("xbrl_facts" in block.metadata for block in parsed.blocks)


def test_ingestion_parse_wires_two_lane_for_pdfs(monkeypatch):
    _drop_optional_deps(monkeypatch)
    parsed = DocumentIngestionService()._parse(
        FIXTURE_PDF.read_bytes(), "filing.pdf", ".pdf", "application/pdf"
    )
    assert parsed.parser == "pypdf"
    assert len(parsed.blocks) == 2
    assert parsed.blocks[0].metadata["page"] == 1
    assert parsed.blocks[0].metadata["extraction_lane"] == "pypdf"


def test_native_pdf_parser_untouched():
    parsed = DocumentIngestionService()._parse_pdf(FIXTURE_PDF.read_bytes())
    assert parsed.parser == "pypdf"
    assert [block.metadata["page"] for block in parsed.blocks] == [1, 2]


def test_chunk_shape_and_hash_dedupe_unchanged(monkeypatch):
    _install_fake_markitdown(monkeypatch, PLAIN_MD)
    service = DocumentIngestionService()
    parsed = service._parse(b"%PDF-1.4 fake", "note.pdf", ".pdf", "application/pdf")
    chunks = service._chunk_blocks(parsed.blocks, "abc123", parsed.parser, "note.pdf", None)
    assert chunks
    for chunk in chunks:
        assert set(chunk["metadata"]) == {
            "checksum",
            "parser",
            "filename",
            "source_url",
            "block_metadata",
            "chunk_sha256",
        }
        assert chunk["metadata"]["chunk_sha256"] == hashlib.sha256(
            chunk["text"].encode("utf-8")
        ).hexdigest()
        assert chunk["metadata"]["block_metadata"]
        assert all(
            "extraction_lane" in meta for meta in chunk["metadata"]["block_metadata"]
        )


def test_xbrl_detection_and_fact_extraction():
    content = INSTANCE_XML.encode()
    assert detect_xbrl(content, "filing_htm.xml", "application/xml") is True
    assert detect_xbrl(b"plain text", "note.pdf", "application/pdf") is False
    facts = extract_xbrl_facts(content)
    assert len(facts) == 1
    assert facts[0]["tag"] == "EarningsPerShareDiluted"
    assert facts[0]["value"] == "10.20"
    assert facts[0]["start"] == "2024-10-01"
    assert facts[0]["members"] == ["CommonClassAMember"]


def test_xbrl_facts_never_break_ingestion():
    assert extract_xbrl_facts(b"not xml at all <<<") == []


def test_xbrl_pdf_appends_facts_block(monkeypatch):
    _install_fake_markitdown(monkeypatch, PLAIN_MD)
    parsed = parse_pdf_two_lane(
        INSTANCE_XML.encode(), "filing.pdf", allow_heavy=False, converter=Mock()
    )
    facts_blocks = [block for block in parsed.blocks if "xbrl_facts" in block.metadata]
    assert len(facts_blocks) == 1
    assert facts_blocks[0].metadata["xbrl_fact_count"] == 1
    assert any("diferido" in warning for warning in parsed.warnings)


def test_heavy_context_is_scoped():
    assert heavy_lane_allowed() is False
    assert resolve_allow_heavy(None) is False
    with docling_heavy_context():
        assert heavy_lane_allowed() is True
        assert resolve_allow_heavy(None) is True
    assert heavy_lane_allowed() is False
    assert resolve_allow_heavy(True) is True
    assert resolve_allow_heavy(False) is False


def test_lane_decision_dataclass_defaults():
    decision = LaneDecision(lane="pypdf", reason="test")
    assert decision.table_pipe_lines == 0
    assert decision.xbrl_detected is False
    assert decision.scanned is False


def test_lane_flags_default_on():
    flags = lane_flags()
    assert flags["markitdown_enabled"] is True
    assert flags["docling_lane_enabled"] is True
    assert flags["docling_async_only"] is True


def test_lanes_disabled_serve_classic_pypdf(monkeypatch):
    _install_fake_markitdown(monkeypatch, PLAIN_MD)
    monkeypatch.setenv("MARKITDOWN_ENABLED", "0")
    monkeypatch.setenv("DOCLING_LANE_ENABLED", "0")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        parsed = parse_pdf_two_lane(
            FIXTURE_PDF.read_bytes(), "filing.pdf", allow_heavy=False
        )
    finally:
        get_settings.cache_clear()
    assert parsed.parser == "pypdf"
    assert {block.metadata["page"] for block in parsed.blocks} == {1, 2}


# --- Contencion Pillow en el worker (SINTETICO: imagenes generadas en el test) ---


def _png_bytes(w: int, h: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("1", (w, h)).save(buf, "PNG")
    return buf.getvalue()


def test_heavy_context_bounds_and_restores_pillow_pixel_limit(monkeypatch):
    from PIL import Image

    monkeypatch.setenv("CAVAAI_DOCLING_MAX_IMAGE_PIXELS", "100")
    before = Image.MAX_IMAGE_PIXELS
    with pipeline.docling_heavy_context():
        assert Image.MAX_IMAGE_PIXELS == 100
    assert before == Image.MAX_IMAGE_PIXELS


def test_heavy_context_image_over_limit_fails_instead_of_warning(monkeypatch):
    import io

    import pytest
    from PIL import Image

    monkeypatch.setenv("CAVAAI_DOCLING_MAX_IMAGE_PIXELS", "100")
    with pipeline.docling_heavy_context():
        # 2x-limit o mas: DecompressionBombError; entre 1x y 2x: el aviso pasa a error.
        with pytest.raises((Image.DecompressionBombError, Image.DecompressionBombWarning)):
            Image.open(io.BytesIO(_png_bytes(20, 20)))
        with pytest.raises((Image.DecompressionBombError, Image.DecompressionBombWarning)):
            Image.open(io.BytesIO(_png_bytes(12, 12)))
        Image.open(io.BytesIO(_png_bytes(9, 9)))  # bajo el tope: normal
    # fuera del contexto el comportamiento previo no cambia
    Image.open(io.BytesIO(_png_bytes(20, 20)))


def test_heavy_context_restores_even_if_body_raises(monkeypatch):
    import pytest
    from PIL import Image

    monkeypatch.setenv("CAVAAI_DOCLING_MAX_IMAGE_PIXELS", "100")
    before = Image.MAX_IMAGE_PIXELS
    with pytest.raises(RuntimeError), pipeline.docling_heavy_context():
        raise RuntimeError("boom")
    assert before == Image.MAX_IMAGE_PIXELS
    assert pipeline.heavy_lane_allowed() is False
