"""Carril de texto de filings SEC -> evidencia de cuellos (respuestas grabadas)."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Document, DocumentChunk, Tenant
from app.services.bottleneck_service import THEMES
from app.services.sec_bottleneck_filings import (
    MAX_PASSAGES_PER_DOC,
    ingest_all,
    ingest_theme,
    matching_passages,
    parse_hits,
    theme_query,
)

# Respuesta EFTS grabada (forma documentada: hits.hits[]._source + _id "adsh:fichero").
EFTS_PAYLOAD = {
    "hits": {
        "total": {"value": 2},
        "hits": [
            {
                "_id": "0000950170-25-000001:d8k.htm",
                "_source": {
                    "adsh": "0000950170-25-000001",
                    "form": "8-K",
                    "file_date": "2026-10-15",
                    "display_names": ["ACME CHIPS INC  (ACM)"],
                    "ciks": ["0001234567"],
                },
            },
            {
                "_id": "0000950170-25-000002:d10q.htm",
                "_source": {
                    "adsh": "0000950170-25-000002",
                    "form": "10-Q",
                    "file_date": "2026-10-14",
                    "display_names": ["NO PASSAGES CORP"],
                    "ciks": ["0007654321"],
                },
            },
            {"_id": "incompleto", "_source": {"adsh": "", "form": ""}},
        ],
    }
}

# Documento de filing grabado: una frase con escasez real y una con alivio.
FILING_HTML = (
    "<html><body><p>ACME CHIPS INC reported that chip shortages persist across "
    "its supplier network.</p><p>The GPU shortage is easing in other segments. "
    "Revenue grew.</p></body></html>"
)
CLEAN_HTML = "<html><body><p>Revenue grew and margins expanded this quarter.</p></body></html>"


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text
        self.status_code = 200
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeClient:
    """Cliente grabado: EFTS por URL de busqueda, HTML por URL de Archives."""

    def __init__(self):
        self.get = AsyncMock(side_effect=self._get)

    async def _get(self, url, params=None, headers=None):
        if "search-index" in url:
            return FakeResponse(payload=EFTS_PAYLOAD)
        if "000095017025000001" in url:
            return FakeResponse(text=FILING_HTML)
        return FakeResponse(text=CLEAN_HTML)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_theme_query_covers_all_themes():
    for theme in THEMES:
        query = theme_query(theme)
        assert "supply constraint" in query and " AND " in query


def test_parse_hits_builds_official_urls_and_skips_incomplete():
    hits = parse_hits(EFTS_PAYLOAD)
    assert len(hits) == 2
    assert hits[0]["url"] == ("https://www.sec.gov/Archives/edgar/data/1234567/000095017025000001/d8k.htm")
    assert hits[0]["company"] == "ACME CHIPS INC  (ACM)"
    assert hits[0]["file_date"] == "2026-10-15"


def test_matching_passages_fail_closed():
    passages = matching_passages(
        "Chip shortages persist across suppliers. The chip shortage is easing. "
        "If chip shortages occur, output could slow. Revenue grew.",
        "Semiconductores",
    )
    assert passages == ["Chip shortages persist across suppliers."]
    # Tema distinto: co-ocurrencia exigida, nada que guardar.
    assert matching_passages("Chip shortages persist.", "Energía") == []
    # Tope de pasajes por documento.
    text = " ".join(["Chip shortages persist."] * (MAX_PASSAGES_PER_DOC + 2))
    assert len(matching_passages(text, "Semiconductores")) == MAX_PASSAGES_PER_DOC


def test_ingest_theme_stores_literal_passages_once(db):
    since = datetime(2026, 10, 8, tzinfo=UTC)
    first = asyncio.run(ingest_theme(db, 1, "Semiconductores", since=since, client=FakeClient()))
    db.commit()
    assert first["hits"] == 2 and first["documents"] == 1 and first["passages"] == 1
    document = db.scalar(select(Document).where(Document.source_type == "sec_filing"))
    assert document.source_url == (
        "https://www.sec.gov/Archives/edgar/data/1234567/000095017025000001/d8k.htm"
    )
    # sqlite devuelve naive: se compara la fecha (en Postgres es timestamptz).
    assert document.published_at is not None
    assert document.published_at.date().isoformat() == "2026-10-15"
    chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document.id))
    assert chunk.text == "ACME CHIPS INC reported that chip shortages persist across its supplier network."
    # Idempotente: segunda corrida no duplica.
    second = asyncio.run(ingest_theme(db, 1, "Semiconductores", since=since, client=FakeClient()))
    db.commit()
    assert second["documents"] == 0 and second["skipped_existing"] == 1
    assert len(list(db.scalars(select(Document).where(Document.source_type == "sec_filing")))) == 1


def test_ingest_all_fail_closed_per_theme(db, monkeypatch):
    async def boom(theme, *, since, client=None):
        raise RuntimeError("red caida")

    monkeypatch.setattr("app.services.sec_bottleneck_filings.ingest_theme", boom)
    result = asyncio.run(ingest_all(db, 1, now=datetime(2026, 10, 20, tzinfo=UTC)))
    assert all("error" in r for r in result["themes"].values())
    assert set(result["themes"]) == set(THEMES)


def test_scheduler_registers_six_hourly_ingestion_job():
    from app.workers import scheduler as scheduler_module

    job = scheduler_module.build_scheduler().get_job("sec_bottleneck_filings")
    assert job is not None and job.trigger.interval.total_seconds() == 21600


def test_actor_runs_ingestion_and_commits(monkeypatch):
    from app.workers import dramatiq_app

    calls = []

    async def fake_ingest(db, tenant, **kw):
        calls.append(tenant)
        return {"themes": {}, "since": "2026-10-13T00:00:00+00:00"}

    class _Db:
        info = {"tenant_id": 1}

        def close(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: _Db())
    monkeypatch.setattr("app.services.sec_bottleneck_filings.ingest_all", fake_ingest)
    result = dramatiq_app.ingest_sec_bottleneck_filings(tenant_id=1, user_id="owner")
    assert result["actor"] == "ingest_sec_bottleneck_filings" and result["status"] == "ok"
    assert calls == [1]
