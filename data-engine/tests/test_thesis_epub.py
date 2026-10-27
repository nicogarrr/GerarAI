"""Tests herméticos de exportación de tesis a EPUB con EbookLib.

Sin red y sin binarios externos: el EPUB se construye 100 % en Python con
EbookLib y aquí se valida la estructura (mimetype primero y sin comprimir,
container, OPF, capítulos), los metadatos (título, GerarAI, es, identificador
estable, fecha), el TOC desde las secciones reales, las tildes/ñ/€, las
tablas como tablas y el escape de HTML inyectado; además del endpoint
GET /api/thesis/{ticker}/epub (200 descarga / 404 limpio sin tesis).

Run from data-engine/:
    pytest tests/test_thesis_epub.py -v
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import main
from app.core.database import Base, get_db
from app.models import Claim, Company, FundamentalModelVersion, Tenant, ThesisSection, ThesisVersion
from app.services.thesis_epub_service import (
    DISCLAIMER_ES,
    EPUB_MIMETYPE,
    EpubSection,
    ThesisEpubData,
    build_thesis_epub,
    markdown_lite_to_html,
)


def _sample_data() -> ThesisEpubData:
    return ThesisEpubData(
        ticker="SAN",
        company_name="Banco Santander",
        version=2,
        rating="buy",
        status="final",
        generated_on="2026-09-21",
        executive_summary="Resumen **sólido** del banco: valoración, cigüeña, niño, 8€.",
        sections=[
            EpubSection(
                title="Valoración",
                body="# Rango\n\n| Escenario | Valor |\n|---|---|\n| Toro | 8€ |\n| Base | 6€ |",
            ),
            EpubSection(title="Riesgos", body="Riesgo de tipos y **mora**: ¿qué pasa si sube la mora?"),
        ],
        citations=["[verified] El margen crece (https://ejemplo.com/fuente)"],
    )


def _open_epub(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


def _read_book(payload: bytes) -> epub.EpubBook:
    return epub.read_epub(io.BytesIO(payload))


def _toc_titles(book: epub.EpubBook) -> list[str]:
    titles: list[str] = []
    for entry in book.toc:
        if isinstance(entry, tuple):
            _section, children = entry
            titles.extend(getattr(child, "title", "") for child in children)
        else:
            titles.append(getattr(entry, "title", ""))
    return titles


def _chapter_raw(payload: bytes, suffix: str) -> str:
    with _open_epub(payload) as zf:
        names = [name for name in zf.namelist() if name.endswith(suffix)]
        assert names, f"capítulo *{suffix} no encontrado en {zf.namelist()}"
        assert len(names) == 1, f"capítulo *{suffix} ambiguo: {names}"
        return zf.read(names[0]).decode("utf-8")


def test_build_epub_es_zip_valido_con_mimetype_primero():
    payload = build_thesis_epub(_sample_data())
    assert payload[:2] == b"PK"

    with _open_epub(payload) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype", f"mimetype debe ser la primera entrada: {names[:3]}"
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype").decode("ascii") == EPUB_MIMETYPE
        container = zf.read("META-INF/container.xml").decode("utf-8")
        assert "EPUB/content.opf" in container
        assert "EPUB/content.opf" in names
        assert "EPUB/toc.ncx" in names
        assert "EPUB/nav.xhtml" in names


def test_build_epub_parseable_por_ebooklib_con_metadatos_byte_compatibles():
    payload = build_thesis_epub(_sample_data())
    book = _read_book(payload)

    assert book.get_metadata("DC", "title") == [("Tesis de inversión: SAN — Banco Santander", {})]
    assert book.get_metadata("DC", "creator") == [("GerarAI", {"id": "creator"})]
    assert book.get_metadata("DC", "language") == [("es", {})]
    assert book.get_metadata("DC", "identifier") == [("cavaai-thesis-SAN-v2", {"id": "id"})]
    assert book.get_metadata("DC", "date") == [("2026-09-21", {})]


def test_build_epub_toc_con_las_secciones_reales():
    payload = build_thesis_epub(_sample_data())
    book = _read_book(payload)

    assert _toc_titles(book) == [
        "Tesis de inversión: SAN — Banco Santander",
        "Resumen ejecutivo",
        "Valoración",
        "Riesgos",
        "Citas y evidencia",
        "Aviso legal",
    ]


def test_build_epub_numero_de_capitulos_y_contenido():
    payload = build_thesis_epub(_sample_data())

    with _open_epub(payload) as zf:
        chapters = sorted(name for name in zf.namelist() if name.endswith(".xhtml") and not name.endswith("nav.xhtml"))
        # portada + resumen + 2 secciones + citas + aviso (+ nav.xhtml aparte)
        assert len(chapters) == 6, chapters
        assert any(name.endswith("portada.xhtml") for name in chapters)
        assert any(name.endswith("resumen.xhtml") for name in chapters)
        assert any(name.endswith("seccion-01-valoracion.xhtml") for name in chapters)
        assert any(name.endswith("seccion-02-riesgos.xhtml") for name in chapters)
        assert any(name.endswith("citas.xhtml") for name in chapters)
        assert any(name.endswith("aviso.xhtml") for name in chapters)

    aviso = _chapter_raw(payload, "aviso.xhtml")
    assert "asesoramiento" in aviso
    assert DISCLAIMER_ES.split(".")[0][:40] in aviso

    citas = _chapter_raw(payload, "citas.xhtml")
    assert "margen crece" in citas

    resumen = _chapter_raw(payload, "resumen.xhtml")
    assert "<strong>sólido</strong>" in resumen


def test_build_epub_tablas_sobreviven_como_tablas():
    payload = build_thesis_epub(_sample_data())
    valoracion = _chapter_raw(payload, "seccion-01-valoracion.xhtml")

    assert "<table>" in valoracion
    assert "<th>Escenario</th>" in valoracion
    assert "<th>Valor</th>" in valoracion
    assert "<td>Toro</td>" in valoracion
    assert "<td>8€</td>" in valoracion


def test_build_epub_caracteres_espanoles_intactos():
    payload = build_thesis_epub(_sample_data())
    resumen = _chapter_raw(payload, "resumen.xhtml")
    riesgos = _chapter_raw(payload, "seccion-02-riesgos.xhtml")

    for token in ("sólido", "valoración", "cigüeña", "niño", "8€", "¿qué pasa si"):
        assert token in resumen + riesgos, f"{token!r} perdido en el EPUB"


def test_build_epub_escapa_html_inyectado():
    data = _sample_data()
    data.sections = [EpubSection(title="<script>alert(1)</script>", body="<img src=x onerror=y>")]
    payload = build_thesis_epub(data)

    # Sigue siendo un EPUB válido aunque el contenido sea hostil.
    book = _read_book(payload)
    assert book.get_metadata("DC", "identifier") == [("cavaai-thesis-SAN-v2", {"id": "id"})]

    chapter = _chapter_raw(payload, "seccion-01-script-alert-1-script.xhtml")
    assert "<script>" not in chapter
    assert "&lt;script&gt;" in chapter
    assert "<img" not in chapter


def test_build_epub_identificador_estable_entre_generaciones():
    first = _read_book(build_thesis_epub(_sample_data()))
    second = _read_book(build_thesis_epub(_sample_data()))
    assert first.get_metadata("DC", "identifier") == second.get_metadata("DC", "identifier")

    other_version = _sample_data()
    other_version.version = 3
    third = _read_book(build_thesis_epub(other_version))
    assert third.get_metadata("DC", "identifier") == [("cavaai-thesis-SAN-v3", {"id": "id"})]


def test_build_epub_contenido_malformado_no_rompe_y_tipos_fallan_en_alto():
    # Markup roto (tags sin cerrar, entidades): se escapa, no se rompe.
    broken = markdown_lite_to_html("<b>sin cerrar & <img src=x onerror=y>")
    assert "<img" not in broken
    payload = build_thesis_epub(
        ThesisEpubData(ticker="SAN", sections=[EpubSection(title="Rota", body=broken)])
    )
    assert _read_book(payload) is not None

    # Tipos rotos: error honesto (TypeError con mensaje), nunca EPUB corrupto.
    with pytest.raises(TypeError):
        build_thesis_epub("no-soy-thesis-epub-data")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        build_thesis_epub(ThesisEpubData(ticker="SAN", sections=[EpubSection(title="T", body=123)]))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        markdown_lite_to_html(123)  # type: ignore[arg-type]


def test_build_epub_sin_binario_externo():
    source = (Path(__file__).resolve().parent.parent / "app" / "services" / "thesis_epub_service.py").read_text(
        encoding="utf-8"
    )
    assert "from ebooklib import epub" in source
    # Patrones de invocación real (no menciones en prosa): ni pandoc como
    # comando ni subprocess/OS para lanzar herramientas de sistema.
    for pattern in (
        r"(?m)^\s*(import|from)\s+subprocess\b",
        r"subprocess\.",
        r"Popen\s*\(",
        r"os\.system\s*\(",
        r"shutil\.which\s*\(",
        r"check_output\s*\(",
        r"['\"]pandoc['\"]",
    ):
        assert not re.search(pattern, source), f"{pattern!r} no puede aparecer en el camino del EPUB"


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="epub-test", name="EPUB Test")
    session.add(tenant)
    session.flush()
    session.info["tenant_id"] = tenant.id

    company = Company(
        ticker="SAN",
        name="Banco Santander",
        exchange="BME",
        currency="EUR",
        sector="Financials",
        industry="Banks",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()

    thesis = ThesisVersion(
        company_id=company.id,
        version=3,
        status="final",
        thesis_markdown="# Tesis SAN",
        executive_summary="Resumen ejecutivo de prueba.",
        rating="buy",
    )
    session.add(thesis)
    # Tesis «final»: la puerta de publicación exige un modelo publicable
    # vigente para mostrar su valoración (si no, sale archivada).
    session.add(
        FundamentalModelVersion(
            company_id=company.id, version=1, engine_version="test", algorithm_version="test",
            framework_key="dcf", horizon_years=10, status="ok", publishable=True,
            input_fingerprint="epub-input", forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
        )
    )
    session.flush()

    session.add(
        ThesisSection(
            thesis_version_id=thesis.id,
            company_id=company.id,
            section_key="valuation",
            title="Valoración",
            body="Base: 6€.",
            status="published",
            order_index=1,
        )
    )
    session.add(
        Claim(
            company_id=company.id,
            thesis_version_id=thesis.id,
            statement="El margen de intereses crece.",
            status="verified",
            materiality_score=8,
        )
    )
    session.commit()

    def _override():
        yield session

    main.app.dependency_overrides[get_db] = _override
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_epub_endpoint_devuelve_descarga_valida(client):
    response = client.get("/api/thesis/SAN/epub")
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"] == "application/epub+zip"
    assert "attachment" in response.headers["content-disposition"]
    assert "gerarai-thesis-SAN-v3.epub" in response.headers["content-disposition"]

    with _open_epub(response.content) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert zf.read("mimetype").decode("ascii") == EPUB_MIMETYPE

    book = _read_book(response.content)
    assert book.get_metadata("DC", "identifier") == [("cavaai-thesis-SAN-v3", {"id": "id"})]
    assert book.get_metadata("DC", "language") == [("es", {})]
    assert "Valoración" in _toc_titles(book)

    citas = _chapter_raw(response.content, "citas.xhtml")
    assert "margen de intereses" in citas


def test_epub_endpoint_404_limpio_sin_tesis(client):
    response = client.get("/api/thesis/NADAAAA/epub")
    assert response.status_code == 404
    assert response.json() == {"detail": "No thesis for ticker"}


def test_uid_epub_estable_tras_rebrand():
    # Compatibilidad pre/post rebrand: el identificador DC no sigue la marca.
    # Mismo ticker y version => mismo uid que antes del renombre CavaAI -> GerarAI.
    from app.services.thesis_epub_service import EPUB_UID_TEMPLATE

    assert EPUB_UID_TEMPLATE.format(ticker="SAN", version=2) == "cavaai-thesis-SAN-v2"


def test_build_epub_enums_traducidos_fecha_es_y_banner_de_estado():
    """La portada nunca muestra el enum crudo ni una fecha ISO en prosa española.

    Regresión: el EPUB de una tesis no publicada salía con «rating: buy ·
    estado: final · generada el 2026-09-21» y sin el aviso de estado que el
    memo declara (no publicada -> lectura de seguimiento, no veredicto).
    """
    payload = build_thesis_epub(_sample_data())  # rating buy, status final
    portada = _chapter_raw(payload, "portada.xhtml")
    assert "rating: compra" in portada
    assert "estado: final" in portada
    assert "generada el 21 de septiembre de 2026" in portada
    assert "rating: buy" not in portada
    assert "2026-09-21" not in portada
    assert "no publicada ni aprobada" in portada
    assert "no un veredicto ni una recomendación" in portada

    # El metadato DC conserva la fecha ISO (Dublin Core), solo cambia la prosa.
    book = _read_book(payload)
    assert book.get_metadata("DC", "date") == [("2026-09-21", {})]


def test_build_epub_publicada_sin_banner_de_estado():
    data = _sample_data()
    data.status = "published"
    data.rating = "hold"
    portada = _chapter_raw(build_thesis_epub(data), "portada.xhtml")
    assert "estado: publicada" in portada
    assert "rating: mantener" in portada
    assert "no publicada ni aprobada" not in portada
