"""Seguridad de la superficie de importacion CSV/XLSX y exportacion EPUB.

Cubre los huecos encontrados en la revision de la superficie VAL-DATA:
- Subida de archivo sin tope de tamano (POST /api/portfolio/import/file):
  un archivo grande agotaba la memoria del worker.
- Preview JSON sin tope de tamano (POST /api/portfolio/import/preview).
- Parseo sin tope de filas (CSV o XLSX con cientos de miles de filas).
- XLSX sin guarda anti zip-bomb (la ingesta de documentos ya la tenia).
- Filename EPUB sin saneado en Content-Disposition (el PDF si lo tenia).
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.thesis import router as thesis_router
from app.core.database import Base, get_db
from app.models.entities import Company, Portfolio, Tenant, ThesisSection, ThesisVersion
from app.services.transaction_import_service import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    parse_file_rows,
)


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as s:
        tenant = Tenant(external_id="tenant-sec-test", name="Tenant Sec Test", metadata_={})
        s.add(tenant)
        s.commit()
        tenant_id = tenant.id

        portfolio = Portfolio(
            tenant_id=tenant_id,
            name="Cartera Seguridad",
            base_currency="EUR",
            is_default=True,
            created_at=datetime.now(UTC),
        )
        s.add(portfolio)

        company = Company(
            ticker='A"B',
            name="Ticker con comilla",
            exchange="BME",
            currency="EUR",
            company_type="operating",
            valuation_model="dcf",
        )
        s.add(company)
        s.commit()

        thesis = ThesisVersion(
            tenant_id=tenant_id,
            company_id=company.id,
            version=3,
            status="published",
            rating="buy",
            thesis_markdown="# Tesis\n\nCuerpo.",
            executive_summary="Resumen.",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(thesis)
        s.commit()
        s.add(
            ThesisSection(
                tenant_id=tenant_id,
                company_id=company.id,
                thesis_version_id=thesis.id,
                section_key="resumen",
                title="Resumen",
                body="Cuerpo de la seccion.",
                order_index=1,
            )
        )
        s.commit()

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tenant_id
            yield session

    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/portfolio")
    app.include_router(thesis_router, prefix="/api/thesis")
    app.dependency_overrides[get_db] = _db
    client = TestClient(app, raise_server_exceptions=True)
    yield client


def test_upload_file_rejects_oversized(env):
    """Un archivo mayor que MAX_IMPORT_BYTES se rechaza con 413, no se lee entero."""
    client = env
    big = b"a" * (MAX_IMPORT_BYTES + 1)
    resp = client.post(
        "/api/portfolio/import/file",
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert resp.status_code == 413
    assert "10" in resp.json()["detail"]


def test_upload_file_just_under_limit_is_parsed(env):
    """Un archivo grande pero dentro del tope sigue funcionando."""
    client = env
    row = b"SAN.MC,2024-01-15,buy,10,3.5\n"
    body = b"ticker,date,action,quantity,price\n" + row * 2000
    assert len(body) < MAX_IMPORT_BYTES
    resp = client.post(
        "/api/portfolio/import/file",
        files={"file": ("ok.csv", body, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["valid_rows_count"] == 2000


def test_preview_endpoint_rejects_oversized_content(env):
    """El preview JSON acota el campo content (validacion 422 de pydantic)."""
    client = env
    resp = client.post(
        "/api/portfolio/import/preview",
        json={"filename": "big.csv", "content": "a" * (MAX_IMPORT_BYTES + 1)},
    )
    assert resp.status_code == 422


def test_parse_file_rows_rejects_too_many_rows():
    """Un CSV con mas filas que MAX_IMPORT_ROWS se rechaza con error claro."""
    rows = ["SAN.MC,2024-01-15,buy,10,3.5"] * (MAX_IMPORT_ROWS + 1)
    csv_text = "ticker,date,action,quantity,price\n" + "\n".join(rows)
    with pytest.raises(ValueError, match="filas"):
        parse_file_rows(csv_text.encode("utf-8"), "many.csv")


def test_parse_file_rows_xlsx_zip_bomb_rejected():
    """Un 'xlsx' con una entrada con compresion anomala se rechaza antes de openpyxl."""
    buf = io.BytesIO()
    payload = b"0" * (2 * 1024 * 1024)  # 2 MB de ceros: DEFLATE lo deja en ~2 KB
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", payload)
    with pytest.raises(ValueError, match="compresion anomala|ZIP"):
        parse_file_rows(buf.getvalue(), "bomb.xlsx")


def test_parse_file_rows_rejects_encrypted_zip():
    """Un OOXML cifrado no se admite (misma politica que la ingesta de documentos)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"<workbook/>")
    raw = bytearray(buf.getvalue())
    # Marcar el flag de cifrado (bit 0) en la cabecera local del ZIP.
    assert raw[6] == 0 or True
    raw[6] |= 1  # general purpose bit flag en la local file header
    with pytest.raises(ValueError):
        parse_file_rows(bytes(raw), "encrypted.xlsx")


def test_epub_export_sanitizes_filename_header(env):
    """Un ticker con comillas no rompe la cabecera Content-Disposition del EPUB."""
    client = env
    resp = client.get("/api/thesis/A%22B/epub")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    assert '"' not in cd.split("filename=", 1)[1].strip('"')
    assert cd == 'attachment; filename="gerarai-thesis-A-B-v3.epub"'
