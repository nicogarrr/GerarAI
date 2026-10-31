"""Pruebas para la exportación de tesis y carteras a PDF.

Fulfills: VAL-DATA-005, VAL-DATA-001
Expected Behavior:
- PDF generado con formato profesional y branding GerarAI
- Incluye resumen ejecutivo, composición de cartera y análisis
- Descarga rápida (< 5 segundos)
- Sanitización de nombres de archivo contra path traversal e inyección
- Endpoints HTTP GET /api/thesis/{ticker}/pdf y GET /api/portfolio/{id}/pdf
"""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.thesis import router as thesis_router
from app.core.database import Base, get_db
from app.models.entities import Company, Portfolio, Position, Tenant, ThesisSection, ThesisVersion
from app.services.thesis_pdf_service import (
    HoldingItem,
    PdfSection,
    ThesisPdfData,
    build_thesis_pdf,
    sanitize_pdf_filename,
)


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as s:
        tenant = Tenant(external_id="tenant-pdf-test", name="Tenant PDF Test", metadata_={})
        s.add(tenant)
        s.commit()
        tenant_id = tenant.id

        company = Company(
            ticker="SAN.MC",
            name="Banco Santander S.A.",
            exchange="BME",
            currency="EUR",
            sector="Financial Services",
            industry="Diversified Banking",
            company_type="operating",
            valuation_model="dcf",
        )
        s.add(company)
        s.commit()

        thesis = ThesisVersion(
            tenant_id=tenant_id,
            company_id=company.id,
            version=1,
            status="published",
            rating="buy",
            thesis_markdown="# Tesis Banco Santander\n\nFortaleza de capital y diversificación internacional.",
            executive_summary="Tesis de inversión basada en fortaleza de capital y diversificación global.",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(thesis)
        s.commit()

        sec1 = ThesisSection(
            tenant_id=tenant_id,
            company_id=company.id,
            section_key="competitive_position",
            thesis_version_id=thesis.id,
            order_index=1,
            title="1. Posición Competitiva",
            body="Liderazgo en cuota de mercado en España y América Latina con escala eficiente.",
        )
        s.add(sec1)

        portfolio = Portfolio(
            tenant_id=tenant_id,
            name="Cartera Mixta Conservadora",
            base_currency="EUR",
            is_default=True,
            created_at=datetime.now(UTC),
        )
        s.add(portfolio)
        s.commit()

        pos = Position(
            tenant_id=tenant_id,
            portfolio_id=portfolio.id,
            company_id=company.id,
            quantity=1000.0,
            average_cost=4.50,
            market_price=4.50,
        )
        s.add(pos)
        s.commit()

        port_id = portfolio.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tenant_id
            yield session

    app = FastAPI()
    app.include_router(thesis_router, prefix="/api/thesis")
    app.include_router(portfolio_router, prefix="/api/portfolio")
    app.dependency_overrides[get_db] = _db
    client = TestClient(app, raise_server_exceptions=False)
    yield client, factory, port_id


def test_sanitize_pdf_filename():
    """Verifica que se eliminan caracteres peligrosos de nombres de archivo."""
    assert sanitize_pdf_filename("SAN.MC") == "SAN.MC"
    assert sanitize_pdf_filename("../../etc/passwd") == "etc-passwd"
    assert sanitize_pdf_filename("mi; rm -rf /; tesis") == "mi-rm-rf-tesis"
    assert sanitize_pdf_filename("Cartera Global 2026!") == "Cartera-Global-2026"
    assert sanitize_pdf_filename("") == "gerarai-tesis"


def test_build_thesis_pdf_structure_and_speed():
    """Verifica que el PDF se genera con estructura válida, branding y en menos de 5 segundos."""
    data = ThesisPdfData(
        ticker="IBE.MC",
        company_name="Iberdrola S.A.",
        version=1,
        rating="strong_buy",
        status="published",
        generated_on="2026-10-30",
        executive_summary="Empresa líder en energías renovables y redes eléctricas de distribución con flujos estables.",
        sections=[
            PdfSection(title="1. Fortaleza del Balance", body="Inversión sostenida en redes con marcos regulatorios predictibles."),
            PdfSection(title="2. Catalizadores y Rentabilidad", body="Crecimiento de EBITDA y dividendo en progresión."),
        ],
        holdings=[
            HoldingItem(ticker="IBE.MC", shares=200, price=11.50, value=2300.0, weight="100.0%"),
        ],
        citations=["Informe Financiero Semestral Iberdrola 2026 [claim:1]"],
    )

    t0 = time.time()
    pdf_bytes = build_thesis_pdf(data)
    elapsed = time.time() - t0

    # Cumple el requisito de rendimiento (< 5 segundos)
    assert elapsed < 5.0
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 2

    # Verifica que el texto extraído contiene branding y datos
    page1_text = reader.pages[0].extract_text()
    assert "GERAR AI" in page1_text
    assert "Iberdrola S.A." in page1_text
    assert "IBE.MC" in page1_text
    assert "Resumen Ejecutivo" in page1_text
    assert "Composición de la Cartera" in page1_text


def test_get_thesis_pdf_endpoint(env):
    """Verifica el endpoint GET /api/thesis/{ticker}/pdf."""
    client, _, _ = env

    # Ticker existente
    res = client.get("/api/thesis/SAN.MC/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment; filename=\"gerarai-tesis-SAN.MC-v1.pdf\"" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(res.content))
    assert len(reader.pages) >= 1
    assert "Banco Santander" in reader.pages[0].extract_text()

    # Ticker inexistente -> 404
    res404 = client.get("/api/thesis/INEXISTENTE/pdf")
    assert res404.status_code == 404


def test_get_portfolio_pdf_endpoint(env):
    """Verifica el endpoint GET /api/portfolio/{id}/pdf."""
    client, _, port_id = env

    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment; filename=" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(res.content))
    assert len(reader.pages) >= 1
    page1 = reader.pages[0].extract_text()
    assert "Cartera Mixta Conservadora" in page1
    assert "SAN.MC" in page1

    # Cartera inexistente -> 404
    res404 = client.get("/api/portfolio/999999/pdf")
    assert res404.status_code == 404


def _page_text(pdf_bytes: bytes) -> tuple[str, str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page1 = reader.pages[0].extract_text()
    page2 = reader.pages[1].extract_text() if len(reader.pages) > 1 else ""
    return page1, page2


def test_portfolio_pdf_no_invented_rating_strategy_or_provenance(env):
    """Veracidad: el informe de cartera no inventa calificación, estado, estrategia ni procedencia oficial."""
    client, _, port_id = env
    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    page1, page2 = _page_text(res.content)

    # Sin insignia inventada de COMPRA ni estado PUBLISHED
    assert "COMPRA" not in page1
    assert "PUBLISHED" not in page1
    # Procedencia honesta: datos de la cartera, nunca "OFICIAL"
    assert "DATOS DE LA CARTERA REGISTRADA" in page1
    assert "Procedencia: OFICIAL" not in page1
    # Nada de estrategia inventada
    full = page1 + page2
    assert "alta calidad" not in full
    assert "márgenes de seguridad" not in full
    # Composición calculada con la posición real
    assert "SAN.MC" in full


def test_portfolio_pdf_cost_fallback_is_labelled(env):
    """Sin cotización, el valor se marca como coste de adquisición; nunca como precio de mercado."""
    client, factory, port_id = env
    from app.models.entities import Company as C, Position as P

    from app.models.entities import Portfolio as Pf
    with factory() as s:
        portfolio = s.query(Pf).filter(Pf.id == port_id).first()
        s.add(C(ticker="XYZ.MC", name="Sin Cotizar SA", exchange="BME", currency="EUR", sector="S", industry="I", company_type="operating", valuation_model="dcf"))
        s.commit()
        company2 = s.query(C).filter(C.ticker == "XYZ.MC").first()
        s.add(P(
            tenant_id=portfolio.tenant_id,
            portfolio_id=port_id,
            company_id=company2.id,
            quantity=10.0,
            average_cost=50.0,
            market_price=0,
            currency="EUR",
        ))
        s.commit()

    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    page1, page2 = _page_text(res.content)
    full = page1 + page2
    assert "coste de adquisición" in full
    assert "*" in page1


def test_thesis_pdf_provenance_and_citations_honest(env):
    """Sin evidencias registradas la procedencia lo dice; nunca se afirma OFICIAL."""
    client, _, _ = env
    res = client.get("/api/thesis/SAN.MC/pdf")
    assert res.status_code == 200
    page1, page2 = _page_text(res.content)
    assert "Procedencia: OFICIAL" not in page1
    assert "SIN FUENTES REGISTRADAS" in page1


def test_thesis_pdf_single_section_not_duplicated():
    """Una sola sección aparece en página 1 y no se repite en página 2."""
    data = ThesisPdfData(
        ticker="IBE.MC",
        company_name="Iberdrola S.A.",
        version=1,
        rating="hold",
        status="published",
        generated_on="2026-10-30",
        executive_summary="Resumen.",
        sections=[PdfSection(title="1. Única Sección", body="Contenido.")],
    )
    page1, page2 = _page_text(build_thesis_pdf(data))
    assert "1. Única Sección" in page1
    assert "1. Única Sección" not in page2


def test_thesis_pdf_citations_use_real_source_urls(env):
    """Las citas llevan la URL de la evidencia cuando existe, no un id interno."""
    from app.models.entities import Claim, ClaimEvidence, FundamentalModelVersion as FMV, ThesisVersion as TV

    client, factory, _ = env
    with factory() as s:
        thesis = s.query(TV).filter(TV.version == 1).first()
        # Modelo publicable: la puerta de publicación deja pasar la tesis
        s.add(FMV(
            tenant_id=thesis.tenant_id,
            company_id=thesis.company_id,
            version=1,
            engine_version="t",
            algorithm_version="t",
            framework_key="dcf",
            horizon_years=5,
            status="final",
            publishable=True,
            input_fingerprint="fp1",
            forecast_fingerprint="fp2",
            market_snapshot_fingerprint="fp3",
            valuation_snapshot_fingerprint="fp4",
            scenario_probabilities={},
        ))
        s.commit()
        claim = Claim(
            tenant_id=thesis.tenant_id,
            company_id=thesis.company_id,
            thesis_version_id=thesis.id,
            statement="El beneficio neto 2025 fue 12.574 M€",
            claim_type="fact",
        )
        s.add(claim)
        s.flush()
        s.add(ClaimEvidence(
            tenant_id=thesis.tenant_id,
            claim_id=claim.id,
            source_url="https://www.cnmv.es/doc/santander-iis-2025.pdf",
            evidence_type="supports",
            summary="Cifra del informe anual",
            source_tier="primary",
        ))
        s.commit()

    res = client.get("/api/thesis/SAN.MC/pdf")
    assert res.status_code == 200
    page1, page2 = _page_text(res.content)
    full = page1 + page2
    assert "https://www.cnmv.es/doc/santander-iis-2025.pdf" in full
    assert "FUENTES OFICIALES" in page1


def test_portfolio_pdf_usd_positions_not_labelled_eur(env):
    """Posiciones en USD sin valor base: el total se etiqueta USD, nunca EUR."""
    client, factory, port_id = env
    from app.models.entities import Company as C, Portfolio as Pf, Position as P

    with factory() as s:
        portfolio = s.query(Pf).filter(Pf.id == port_id).first()
        # La posición SAN.MC del fixture tiene currency USD por defecto y sin market_value_base
        s.query(P).filter(P.portfolio_id == port_id).delete()
        s.add(C(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD", sector="T", industry="I", company_type="operating", valuation_model="dcf"))
        s.commit()
        asts = s.query(C).filter(C.ticker == "ASTS").first()
        s.add(P(tenant_id=portfolio.tenant_id, portfolio_id=port_id, company_id=asts.id,
                quantity=100.0, average_cost=30.0, market_price=30.0, currency="USD"))
        s.commit()

    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    page1, _ = _page_text(res.content)
    assert "3.000,00 USD" in page1 or "3,000.00 USD" in page1
    assert "EUR" not in page1.split("Composición")[0].replace("ASTS", "")


def test_portfolio_pdf_mixed_currencies_no_fake_weights(env):
    """Divisas mezcladas sin valor base: pesos n/d y sin ranking de 'mayores posiciones'."""
    client, factory, port_id = env
    from app.models.entities import Company as C, Portfolio as Pf, Position as P

    with factory() as s:
        portfolio = s.query(Pf).filter(Pf.id == port_id).first()
        s.add(C(ticker="IBE.MC", name="Iberdrola", exchange="BME", currency="EUR", sector="U", industry="I", company_type="operating", valuation_model="dcf"))
        s.commit()
        ibe = s.query(C).filter(C.ticker == "IBE.MC").first()
        # SAN.MC del fixture está en USD; añadimos IBE.MC en EUR
        s.add(P(tenant_id=portfolio.tenant_id, portfolio_id=port_id, company_id=ibe.id,
                quantity=200.0, average_cost=11.5, market_price=11.5, currency="EUR"))
        s.commit()

    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    page1, page2 = _page_text(res.content)
    full = page1 + page2
    assert "n/d" in page1
    assert "Pesos no calculables" in full
    assert "Mayores posiciones por peso estimado" not in full


def test_pdf_canvas_has_fixed_unit_limits():
    """Regresión del layout: sin límites 0-1 fijos, matplotlib autoescala con los
    artistas y la cabecera oscura cubría media página mientras el título se
    solapaba con la tabla y el resumen salía del área visible."""
    import matplotlib.pyplot as plt

    from app.services.thesis_pdf_service import _new_page

    fig, ax = _new_page()
    try:
        assert ax.get_xlim() == (0.0, 1.0)
        assert ax.get_ylim() == (0.0, 1.0)
    finally:
        plt.close(fig)


def test_portfolio_pdf_texto_dentro_del_area_visible(env):
    """Todo el texto debe caer dentro del área visible de la página (regresión:
    con el autoescalado de ejes, resumen y secciones quedaban fuera y el título
    se solapaba con la tabla)."""
    client, _, port_id = env
    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    reader = PdfReader(io.BytesIO(res.content))
    for page in reader.pages:
        height = float(page.mediabox.height)
        ys: list[float] = []
        page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: ys.append(tm[5] + cm[5]) if t.strip() else None)
        assert ys, "la página no tiene texto"
        assert min(ys) >= -1.0, f"texto por debajo del área visible (y={min(ys):.1f})"
        assert max(ys) <= height + 1.0, f"texto por encima del área visible (y={max(ys):.1f} > {height:.1f})"
