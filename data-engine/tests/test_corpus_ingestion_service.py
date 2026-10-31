"""Tests del servicio de ingesta del corpus libre (app/services/corpus_ingestion_service.py).

Los discoverers se ejercitan con un cliente HTTP falso que devuelve HTML
realista: lo que se prueba es el parseo, la deduplicacion, el salto de fuentes
rotas y las estadisticas de ingesta, no el propio falso.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

import app.services.corpus_ingestion_service as cis
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.services.knowledge_library_service import KnowledgeLibraryService


class _FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"%PDF-fake", status: int = 200):
        self.text = text
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Cliente httpx falso: resuelve rutas prefijadas; el resto responde OK vacio
    (las cartas del manifiesto Buffett siempre se descargan)."""

    def __init__(self, routes: dict, **kwargs):
        self.routes = routes
        self.kwargs = kwargs
        self.calls: list[str] = []

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        route = self.routes.get(url)
        if route is None:
            return _FakeResponse()
        if isinstance(route, Exception):
            raise route
        return route

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_slug_title_extrae_ultimo_segmento_legible():
    assert cis._slug_title("https://www.azvalor.com/anuncios/carta-junio-2024/") == "carta junio 2024"
    assert cis._slug_title("carta-anual-2023") == "carta anual 2023"


def test_numantia_discover_deduplica_y_compone_urls():
    html = (
        '<a href="pdfs/Numantia2023.pdf">Informe 2023</a>'
        '<a href="pdfs/Numantia2023.pdf">duplicado</a>'
        '<a href="pdfs/Numantia_S1_2024.pdf">Semestral</a>'
        '<a href="https://externo.example/pdfs/Ajeno.pdf">ajeno</a>'
    )
    client = _FakeClient({cis.NUMANTIA_HOME: _FakeResponse(text=html)})
    sources = cis._discover_numantia_sources(client)
    assert [s["filename"] for s in sources] == ["Numantia2023.pdf", "Numantia_S1_2024.pdf"]
    first = sources[0]
    assert first["url"] == "https://numantiapatrimonio.com/pdfs/Numantia2023.pdf"
    assert first["title"] == "Numantia Patrimonio - Carta 2023"
    assert first["author"] == cis.NUMANTIA_AUTHOR
    assert first["document_type"] == "fund_letter"
    assert first["language"] == "es"
    assert sources[1]["title"] == "Numantia Patrimonio - Carta S1_2024"


def test_numantia_home_inalcanzable_devuelve_vacio_sin_inventar():
    client = _FakeClient({cis.NUMANTIA_HOME: RuntimeError("connection refused")})
    assert cis._discover_numantia_sources(client) == []


def test_magallanes_discover_solo_pdfs_de_cartas_sin_anchor():
    html = (
        '<a href="https://magallanesvalue.com/wp-content/uploads/MAGALLANES-CARTA-ENERO-2024.pdf">c</a>'
        '<a href="https://magallanesvalue.com/wp-content/uploads/MAGALLANES-LETTER-Q1-2024.pdf">l</a>'
        '<a href="https://magallanesvalue.com/wp-content/uploads/MAGALLANES-CARTA-ENERO-2024.pdf#pie">anchor</a>'
        '<a href="https://magallanesvalue.com/wp-content/uploads/MAGALLANES-NOTICIA-2024.pdf">no carta</a>'
    )
    client = _FakeClient({cis.MAGALLANES_NOTICIAS: _FakeResponse(text=html)})
    sources = cis._discover_magallanes_sources(client)
    assert [s["filename"] for s in sources] == [
        "MAGALLANES-CARTA-ENERO-2024.pdf",
        "MAGALLANES-LETTER-Q1-2024.pdf",
    ]
    assert sources[0]["title"] == "Magallanes Value Investors - Carta ENERO 2024"
    assert sources[1]["title"] == "Magallanes Value Investors - Carta Q1 2024"
    assert all(s["author"] == cis.MAGALLANES_AUTHOR for s in sources)


def test_magallanes_inalcanzable_devuelve_vacio():
    client = _FakeClient({cis.MAGALLANES_NOTICIAS: RuntimeError("timeout")})
    assert cis._discover_magallanes_sources(client) == []


def test_azvalor_discover_gateway_y_pdf_directo_saltando_paginas_rotas(monkeypatch):
    monkeypatch.setattr(cis.time, "sleep", lambda *_: None)
    index_html = (
        '<a href="https://www.azvalor.com/anuncios-y-comunicados/carta-primer-trimestre-2024/">1</a>'
        '<a href="https://www.azvalor.com/anuncios-y-comunicados/carta-anual-2023/">2</a>'
        '<a href="https://www.azvalor.com/anuncios-y-comunicados/carta-rota-2022/">3</a>'
        '<a href="https://www.azvalor.com/anuncios-y-comunicados/carta-sin-pdf-2021/">4</a>'
        '<a href="https://www.azvalor.com/otra-seccion/noticia/">no carta</a>'
    )
    routes = {
        cis.AZVALOR_INDEX: _FakeResponse(text=index_html),
        "https://www.azvalor.com/anuncios-y-comunicados/carta-primer-trimestre-2024/": _FakeResponse(
            text='<a href="https://www.azvalor.com/azvalor-carta-1t2024/">Descargar</a>'
        ),
        "https://www.azvalor.com/anuncios-y-comunicados/carta-anual-2023/": _FakeResponse(
            text='<a href="https://www.azvalor.com/wp-content/uploads/2024-Carta-Anual.pdf">PDF</a>'
        ),
        "https://www.azvalor.com/anuncios-y-comunicados/carta-rota-2022/": RuntimeError("502"),
        "https://www.azvalor.com/anuncios-y-comunicados/carta-sin-pdf-2021/": _FakeResponse(
            text="<p>sin enlace de descarga</p>"
        ),
    }
    client = _FakeClient(routes)
    sources = cis._discover_azvalor_sources(client)
    # el indice se recorre ordenado: carta-anual-2023 va antes que carta-primer-trimestre-2024
    assert [s["filename"] for s in sources] == [
        "Azvalor-carta_anual_2023.pdf",
        "Azvalor-carta_primer_trimestre_2024.pdf",
    ]
    direct, gateway = sources
    assert gateway["url"] == "https://www.azvalor.com/azvalor-carta-1t2024/"
    assert gateway["title"] == "Azvalor - carta primer trimestre 2024"
    assert direct["url"] == "https://www.azvalor.com/wp-content/uploads/2024-Carta-Anual.pdf"
    assert all(s["author"] == cis.AZVALOR_AUTHOR and s["language"] == "es" for s in sources)


def test_azvalor_indice_inalcanzable_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(cis.time, "sleep", lambda *_: None)
    client = _FakeClient({cis.AZVALOR_INDEX: RuntimeError("dns")})
    assert cis._discover_azvalor_sources(client) == []


def test_buffett_sources_mapea_manifiesto_verificado():
    sources = cis._buffett_sources()
    assert len(sources) == len(cis.BUFFETT_LETTERS)
    by_year = {int(s["filename"].removeprefix("Berkshire").split(".")[0]): s for s in sources}
    assert by_year[1977]["url"] == "https://www.berkshirehathaway.com/letters/1977.html"
    assert by_year[1977]["filename"] == "Berkshire1977.html"
    assert by_year[1977]["published_on"] == date(1978, 3, 14)
    assert by_year[1998]["filename"] == "Berkshire1998.pdf"
    assert by_year[2007]["published_on"] is None
    sample = by_year[2024]
    assert sample["title"] == "Berkshire Hathaway - Carta anual accionistas 2024"
    assert sample["author"] == cis.BUFFETT_AUTHOR
    assert sample["document_type"] == "fund_letter"
    assert sample["language"] == "en"


def _fresh_db_with_tenant():
    init_db()
    db = SessionLocal()
    tenant = Tenant(external_id=f"corpus-svc-{uuid4().hex[:10]}", name="Corpus svc test")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    return db


def test_get_or_create_corpus_collection_es_idempotente():
    db = _fresh_db_with_tenant()
    try:
        first = cis.get_or_create_corpus_collection(db)
        db.commit()
        assert first.slug == cis.COLLECTION_SLUG
        assert first.name == cis.COLLECTION_NAME
        second = cis.get_or_create_corpus_collection(db)
        assert second.id == first.id
    finally:
        db.close()


def test_ingest_free_corpus_cuenta_ingestados_duplicados_fallos_y_saltados(monkeypatch):
    monkeypatch.setattr(cis.time, "sleep", lambda *_: None)
    routes = {
        cis.NUMANTIA_HOME: RuntimeError("home caida"),
        cis.AZVALOR_INDEX: RuntimeError("indice caido"),
        cis.MAGALLANES_NOTICIAS: RuntimeError("noticias caidas"),
    }
    client = _FakeClient(routes)
    monkeypatch.setattr(cis.httpx, "Client", lambda **kwargs: client)

    calls: list[dict] = []

    def fake_ingest(self, db, **kwargs):
        calls.append(kwargs)
        if kwargs["filename"] == "Berkshire2020.pdf":
            return {"status": "duplicate"}
        if kwargs["filename"] == "Berkshire2021.pdf":
            raise RuntimeError("fallo de almacenamiento")
        return {"status": "ingested"}

    monkeypatch.setattr(KnowledgeLibraryService, "ingest_bytes", fake_ingest)

    db = _fresh_db_with_tenant()
    try:
        stats = cis.ingest_free_corpus(db)
    finally:
        db.close()

    total_fuentes = len(cis.BUFFETT_LETTERS)
    assert len(calls) == total_fuentes  # ingest_bytes se llama para las 48; 2021 falla dentro
    assert stats["ingested"] == total_fuentes - 2
    assert stats["duplicates"] == 1
    assert len(stats["failed"]) == 1
    assert stats["failed"][0]["title"] == "Berkshire Hathaway - Carta anual accionistas 2021"
    assert "fallo de almacenamiento" in stats["failed"][0]["error"]
    assert stats["skipped_sources"] == [
        "numantia_home_unreachable",
        "azvalor_unreachable_or_empty",
        "magallanes_unreachable_or_empty",
    ]
    # la coleccion del corpus queda creada para el tenant
    assert calls and all(c["collection_id"] for c in calls)
    assert all(c["source_url"] == c["source_url"] for c in calls)
