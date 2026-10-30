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
