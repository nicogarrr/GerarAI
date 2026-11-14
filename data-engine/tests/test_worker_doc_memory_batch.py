"""process_document_structured, consolidate_memory y backfill_watchlist_theses.

Contratos fijados:
- process_document_structured parsea published_at ISO con «Z», trabaja bajo
  el slot de ingesta y el contexto docling, y clasifica errores;
- consolidate_memory deduplica por (empresa, ambito, tipo, contenido
  normalizado) conservando la mayor importancia y enlazando el duplicado;
- backfill_watchlist_theses delega y cierra la sesion, error estructurado.

Run from data-engine/:
    pytest tests/test_worker_doc_memory_batch.py -v
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(db=MagicMock(), rolled=[], handled=[], session_error=None)
    e.db.info = {"tenant_id": 1}

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return e


# --- process_document_structured ---------------------------------------------


def _patch_ingest_path(monkeypatch, seen):
    @contextmanager
    def dummy_ctx():
        yield

    class Slot:
        @contextmanager
        def hold(self):
            seen.append("slot")
            yield

    monkeypatch.setattr("app.workers.ingest_slot.document_ingest_slot", lambda: Slot())
    monkeypatch.setattr("app.services.docling_pipeline.docling_heavy_context", dummy_ctx)

    class Service:
        def ingest_document_url(self, db, **kwargs):
            seen.append(kwargs)
            return {"status": "ok", "document_id": 7}

    monkeypatch.setattr("app.services.feed_ingestion_service.FeedIngestionService", Service)
    monkeypatch.setattr(worker, "_run", lambda coro: {"status": "ok", "document_id": 7})


def test_structured_ok_parsea_fecha_y_usa_slot(env, monkeypatch):
    seen = []
    _patch_ingest_path(monkeypatch, seen)

    out = worker.process_document_structured.fn(
        "ABC", "Memoria", "https://x.test/memoria.pdf", "annual_report",
        published_at="2026-01-31T00:00:00Z", tenant_id=1, user_id="u",
    )

    assert out["status"] == "ok"
    assert seen[0] == "slot"
    sent = seen[1]
    assert sent["ticker"] == "ABC" and sent["published_at"].year == 2026
    assert sent["published_at"].tzinfo is not None
    env.db.close.assert_called_once_with()


def test_structured_error_clasificado_y_sesion_cerrada(env, monkeypatch):
    seen = []
    _patch_ingest_path(monkeypatch, seen)
    boom = TimeoutError("docling")
    monkeypatch.setattr(worker, "_run", lambda coro: (_ for _ in ()).throw(boom))

    out = worker.process_document_structured.fn(
        "ABC", "Memoria", "https://x.test/m.pdf", "annual_report", tenant_id=1, user_id="u",
    )

    assert out["status"] == "error"
    env.db.close.assert_called_once_with()


# --- consolidate_memory --------------------------------------------------------


def _item(i, content, importance=1, company=5):
    return SimpleNamespace(
        id=i, company_id=company, scope="company", memory_type="fact",
        content=content, importance=importance, metadata_={}, status="active",
    )


def test_consolidate_deduplica_normalizando(env):
    env.db.scalars.return_value.all.return_value = [
        _item(1, "La  empresa\ncrece", importance=2),
        _item(2, "la empresa crece", importance=5),
        _item(3, "otro hecho distinto"),
    ]

    out = worker.consolidate_memory.fn(tenant_id=1, user_id="u")

    assert out == {"status": "ok", "actor": "consolidate_memory", "active_scanned": 3, "duplicates_consolidated": 1}
    canonical, dup = env.db.scalars.return_value.all.return_value[0], env.db.scalars.return_value.all.return_value[1]
    assert canonical.importance == 5
    assert "last_consolidated_at" in canonical.metadata_
    assert dup.status == "consolidated"
    assert dup.metadata_["consolidated_into"] == 1
    env.db.commit.assert_called_once_with()
    env.db.close.assert_called_once_with()


def test_consolidate_sin_duplicados_no_toca(env):
    env.db.scalars.return_value.all.return_value = [_item(1, "a"), _item(2, "b")]

    out = worker.consolidate_memory.fn(tenant_id=1, user_id="u")

    assert out["duplicates_consolidated"] == 0
    assert all(i.status == "active" for i in env.db.scalars.return_value.all.return_value)


def test_consolidate_error_clasificado(env):
    boom = KeyError("tabla")
    env.db.scalars.side_effect = boom

    out = worker.consolidate_memory.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.handled and env.handled[0][1] is boom
    env.db.close.assert_called_once_with()


# --- backfill_watchlist_theses -------------------------------------------------


def test_backfill_theses_delega_y_cierra(env, monkeypatch):
    monkeypatch.setattr(
        "app.services.tracked_analysis.backfill_watchlist_theses",
        lambda db: {"status": "ok", "enqueued": 4},
    )

    out = worker.backfill_watchlist_theses.fn(tenant_id=1, user_id="u")

    assert out == {"actor": "backfill_watchlist_theses", "status": "ok", "enqueued": 4}
    env.db.close.assert_called_once_with()


def test_backfill_theses_error_clasificado(env, monkeypatch):
    boom = ConnectionError("pg")
    def fail(db):
        raise boom

    monkeypatch.setattr("app.services.tracked_analysis.backfill_watchlist_theses", fail)

    out = worker.backfill_watchlist_theses.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    env.db.close.assert_called_once_with()
