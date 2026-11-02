"""Transcripción pegada y documento por URL: un título, un texto o un tipo de
fuente de solo espacios pasaba el mínimo de longitud y se guardaba un documento
vacío en la Biblioteca. Ahora es un 422 de validación, como en #4169."""

import pytest
from fastapi.testclient import TestClient

import main
from app.api.routes.sources import ManualTranscriptImportRequest, UrlIngestRequest
from app.core.csrf import generate_csrf_token
from app.core.database import init_db


def _client() -> TestClient:
    init_db()
    client = TestClient(main.app)
    client.headers["X-CSRF-Token"] = generate_csrf_token()
    return client


def _transcript(**overrides) -> dict:
    base = {
        "ticker": "ZZZZNONE",  # no registrado: si valida, el handler responde 404
        "title": "Resultados 3T",
        "text": "texto suficientemente largo para pasar el minimo",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [{"title": "     "}, {"title": " \t\n "}, {"text": " " * 40}, {"text": "  ab  " + " " * 30}],
)
def test_transcripcion_con_textos_en_blanco_da_422(overrides):
    response = _client().post("/api/sources/transcripts/import-text", json=_transcript(**overrides))
    assert response.status_code == 422


def test_transcripcion_normal_sigue_validando():
    response = _client().post("/api/sources/transcripts/import-text", json=_transcript())
    assert response.status_code == 404  # pasa la validación y llega al handler


@pytest.mark.parametrize("overrides", [{"title": "     "}, {"source_type": "   "}])
def test_url_con_textos_en_blanco_da_422(overrides):
    body = {"ticker": "ZZZZNONE", "title": "Informe", "url": "https://example.com/a", **overrides}
    response = _client().post("/api/sources/documents/ingest-url", json=body)
    assert response.status_code == 422


def test_modelos_aceptan_textos_con_espacios_alrededor():
    transcript = ManualTranscriptImportRequest(
        ticker="MSFT", title="  Res 3T  ", text="  " + "x" * 20 + "  "
    )
    assert transcript.title == "  Res 3T  "  # no recorta: solo exige contenido
    url = UrlIngestRequest(ticker="MSFT", title=" Informe ", url="https://example.com/a")
    assert url.source_type == "url"
