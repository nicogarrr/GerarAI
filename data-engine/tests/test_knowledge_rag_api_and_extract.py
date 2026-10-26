from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import knowledge_rag as route_module
from app.core.config import Settings
from app.core.database import Base, get_db
from app.services.knowledge_rag.extract import (
    ExtractionError,
    extract_file,
    extract_plain_text,
    sections_from_docling,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    yield session
    session.close()


def _client(db, monkeypatch, tmp_path: Path, enabled: bool = True):
    settings = Settings(_env_file=None, knowledge_rag_enabled=enabled, knowledge_rag_inbox_dir=tmp_path,
                        knowledge_rag_min_free_gb=0.0)
    monkeypatch.setattr(route_module, "get_settings", lambda: settings)
    monkeypatch.setattr("app.services.knowledge_rag.runtime.get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(route_module.router, prefix="/api/knowledge-rag")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


PAYLOAD = {
    "path": "carta.txt",
    "title": "Carta 2020",
    "source_uri": "https://example.org/c.pdf",
    "language": "es",
    "doc_type": "letter",
    "rights": "public_domain",
    "author": "Autor",
}


def test_disabled_flag_returns_503(db, monkeypatch, tmp_path) -> None:
    client = _client(db, monkeypatch, tmp_path, enabled=False)
    assert client.post("/api/knowledge-rag/query", json={"query": "margen"}).status_code == 503
    assert client.post("/api/knowledge-rag/sources", json=PAYLOAD).status_code == 503
    assert client.get("/api/knowledge-rag/status").json()["enabled"] is False


def test_create_source_validates_path_and_dedupes(db, monkeypatch, tmp_path) -> None:
    sent: list[int] = []
    import app.workers.knowledge_rag_actors as actors

    monkeypatch.setattr(actors.ingest_knowledge_source, "send", lambda sid, **_k: sent.append(sid))
    client = _client(db, monkeypatch, tmp_path)
    assert client.post("/api/knowledge-rag/sources", json={**PAYLOAD, "path": "../x.txt"}).status_code == 400
    assert client.post("/api/knowledge-rag/sources", json=PAYLOAD).status_code == 400  # no existe
    (tmp_path / "carta.txt").write_text("Texto de la carta sobre margen de seguridad.")
    first = client.post("/api/knowledge-rag/sources", json=PAYLOAD)
    assert first.status_code == 200 and first.json()["deduplicated"] is False and sent == [first.json()["id"]]
    second = client.post("/api/knowledge-rag/sources", json=PAYLOAD)
    assert second.json()["deduplicated"] is True and len(sent) == 1
    assert client.get(f"/api/knowledge-rag/sources/{first.json()['id']}").json()["status"] == "queued"


def test_dated_source_without_as_of_is_rejected(db, monkeypatch, tmp_path) -> None:
    (tmp_path / "f.txt").write_text("Revenue 1.")
    client = _client(db, monkeypatch, tmp_path)
    res = client.post("/api/knowledge-rag/sources", json={**PAYLOAD, "path": "f.txt", "doc_type": "filing"})
    assert res.status_code == 400 and "as_of" in res.json()["detail"]


def test_plain_text_extraction_has_honest_warning() -> None:
    doc = extract_plain_text("Uno.\n\nDos.")
    assert [b.text for b in doc.sections[0].blocks] == ["Uno.", "Dos."] and doc.warnings


def test_unsupported_extension_is_rejected(tmp_path) -> None:
    path = tmp_path / "a.exe"
    path.write_bytes(b"x")
    with pytest.raises(ExtractionError):
        extract_file(path)


def test_docling_document_walk_builds_heading_paths_pages_and_bboxes() -> None:
    def item(label, text, page=None, level=None):
        bbox = SimpleNamespace(l=1, t=2, r=3, b=4, coord_origin=SimpleNamespace(value="BOTTOMLEFT"))
        prov = [SimpleNamespace(page_no=page, bbox=bbox)] if page else []
        return SimpleNamespace(label=SimpleNamespace(value=label), text=text, prov=prov, level=level)

    table = item("table", "", page=2)
    table.export_to_markdown = lambda doc=None: "| a | b |\n|---|---|\n| 1 | 2 |"
    items = [
        (item("title", "Libro"), 0),
        (item("page_header", "ruido"), 0),
        (item("section_header", "Cap 1", level=1), 1),
        (item("text", "Parrafo uno.", page=1), 2),
        (item("section_header", "Sub", level=2), 2),
        (item("text", "Parrafo dos.", page=2), 3),
        (table, 3),
        (item("section_header", "Cap 2", level=1), 1),
        (item("list_item", "punto", page=3), 2),
    ]
    doc = SimpleNamespace(iterate_items=lambda: iter(items))
    out = sections_from_docling(doc)
    assert [s.heading_path for s in out.sections] == [
        ("Libro", "Cap 1"), ("Libro", "Cap 1", "Sub"), ("Libro", "Cap 2")
    ]
    sub = out.sections[1].blocks
    assert sub[0].page == 2 and sub[0].bbox.page == 2 and sub[1].kind == "table"
    assert all("ruido" not in b.text for s in out.sections for b in s.blocks)


def test_real_docling_markdown_and_epub(tmp_path) -> None:
    pytest.importorskip("docling")
    md = tmp_path / "a.md"
    md.write_text("# Carta 2020\n\nPrimer parrafo.\n\n## Riesgo\n\nEl riesgo es perdida permanente.\n")
    doc = extract_file(md)
    assert [s.heading_path for s in doc.sections] == [("Carta 2020",), ("Carta 2020", "Riesgo")]
    epub = tmp_path / "b.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>'
            "<dc:title>T</dc:title><dc:language>en</dc:language></metadata>"
            '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine></package>')
        z.writestr("c1.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head><body>'
            "<h1>Chapter One</h1><p>Be fearful when others are greedy.</p></body></html>")
    out = extract_file(epub)
    assert out.sections[0].heading_path == ("Chapter One",)
    assert "fearful" in out.sections[0].blocks[0].text
