"""Cotas de entrada de POST /api/sources/transcripts/import-text.

ManualTranscriptImportRequest persistia source_url y period sin cota en
columnas String(1000)/String(40): en SQLite pasaba y en Postgres el INSERT
rompe con un 500 en vez de un 422 de validacion (misma familia que el tope
de ingest-file). El texto se acota a 10M chars, alineado con el tope de
10MB que RawBodyMiddleware aplica a cuerpos firmados, para que un cuerpo
gigante reciba un 422 claro en vez de un 413 seco.
"""

import pytest
from fastapi.testclient import TestClient

import main
from app.core.csrf import generate_csrf_token
from app.core.database import init_db


def _client() -> TestClient:
    init_db()
    client = TestClient(main.app)
    client.headers["X-CSRF-Token"] = generate_csrf_token()
    return client


def _payload(**overrides) -> dict:
    base = {
        "ticker": "ZZZZNONE",  # no registrado: el handler responde 404 si valida
        "title": "Transcript bounds test",
        "text": "texto suficientemente largo para pasar el minimo",
    }
    base.update(overrides)
    return base


def test_source_url_beyond_document_column_rejected():
    response = _client().post(
        "/api/sources/transcripts/import-text",
        json=_payload(source_url="https://example.com/" + "a" * 1200),
    )
    assert response.status_code == 422


def test_period_beyond_transcript_column_rejected():
    response = _client().post(
        "/api/sources/transcripts/import-text",
        json=_payload(period="2026-Q" + "1" * 100),
    )
    assert response.status_code == 422


def test_text_beyond_signed_body_budget_rejected():
    from app.api.routes.sources import ManualTranscriptImportRequest

    with pytest.raises(Exception, match="text"):
        ManualTranscriptImportRequest(
            ticker="MSFT",
            title="bounds",
            text="x" * (10 * 1024 * 1024 + 1),
        )


def test_valid_payload_reaches_the_handler():
    # 404 del handler (ticker no registrado), no 422: la validacion paso.
    response = _client().post(
        "/api/sources/transcripts/import-text",
        json=_payload(period="2026-Q3", source_url="https://example.com/t"),
    )
    assert response.status_code == 404
