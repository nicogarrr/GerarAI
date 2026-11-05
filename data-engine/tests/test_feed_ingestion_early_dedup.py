"""Dedup ANTES de descargar en ingest_document_url.

5-nov-2026 [medido piloto]: 677 reencolados de KRKNF descargaban cada
documento (hasta 30 s de fetch) antes de que ingest_bytes deduplicara por
checksum. Con la guarda, una URL ya ingerida por el tenant vuelve
"duplicate" sin red ni extraccion.
"""
from __future__ import annotations

from app.services.feed_ingestion_service import FeedIngestionService


class _FakeDB:
    def __init__(self, known_id):
        self._known_id = known_id
        self.info: dict = {}

    def scalar(self, statement):
        return self._known_id

    def commit(self):
        pass

    def rollback(self):
        pass


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_url_ya_ingerida_no_se_descarga(monkeypatch):
    async def forbidden_fetch(*args, **kwargs):
        raise AssertionError("descargo una URL ya ingerida")

    monkeypatch.setattr(
        "app.services.feed_ingestion_service.fetch_public_url_async", forbidden_fetch
    )
    db = _FakeDB(known_id=1234)
    result = _run(
        FeedIngestionService().ingest_document_url(
            db,
            ticker="KRKNF",
            title="ya la tengo",
            url="https://krakenrobotics.com/news-releases/ya",
            source_type="IR",
        )
    )
    assert result["status"] == "duplicate"
    assert result["document_id"] == 1234
    assert result["dedup"] == "source_url"


def test_url_nueva_si_se_descarga(monkeypatch):
    captured = {}

    async def fake_fetch(url, max_bytes, timeout):
        captured["url"] = url
        return b"html", "text/html", url

    class _FakeIngestion:
        def ingest_bytes(self, db, **kwargs):
            return {"status": "ok", "document_id": 7}

    monkeypatch.setattr(
        "app.services.feed_ingestion_service.fetch_public_url_async", fake_fetch
    )
    monkeypatch.setattr(
        "app.services.document_ingestion_service.DocumentIngestionService",
        lambda: _FakeIngestion(),
    )
    monkeypatch.setattr(
        "app.services.feed_ingestion_service._release_before_fetch", lambda db: None
    )
    db = _FakeDB(known_id=None)
    result = _run(
        FeedIngestionService().ingest_document_url(
            db,
            ticker="KRKNF",
            title="nueva",
            url="https://krakenrobotics.com/news-releases/nueva",
            source_type="IR",
        )
    )
    assert captured["url"].endswith("/nueva")
    assert result["status"] == "ok"
