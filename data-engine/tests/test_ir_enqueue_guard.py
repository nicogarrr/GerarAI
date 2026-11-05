"""Guardas de encolado de process_document (avalancha KRKNF, 5-nov-2026).

[medido piloto] 677 process_document de KRKNF (tenant 10, que NO la sigue)
reencolados cada hora: refresh_ir_pages recorria el universo GLOBAL de
companias con ir_url y encolaba cada comunicado sin comprobar si ya estaba
ingerido ni tope por pasada. Guardas:

1. Solo se encolan documentos de empresas que el tenant sigue (watchlist) o
   tiene en cartera (_tracked_companies). La NOTICIA se ingiere igual.
2. Una URL ya ingerida (Document.source_url del tenant) no se reencola.
3. Tope por pasada (document_enqueue_max_per_poll): el resto entra en ticks
   siguientes; se declara documents_enqueue_capped.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.workers import dramatiq_app
from app.workers.dramatiq_app import refresh_ir_pages


class _FakeRedis:
    """Claim del coalesce siempre concedido; fail-open no aplica aqui."""

    def set(self, key, value, nx=False, ex=None):
        return True

    def get(self, key):
        return None

    def delete(self, key):
        return None

    def exists(self, key):
        return False


class _FakeDB:
    def __init__(self):
        self.info: dict = {}

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _FakeService:
    def __init__(self, items):
        self._items = items

    async def poll_ir(self, ir_url, *, ticker=None):
        return SimpleNamespace(items=self._items, errors=[], status="ok", source="ir")

    def ingest_news_result(self, db, result, *, ticker=None):
        return {"created": 0}


def _items(n: int, prefix: str = "https://ir.example/news-"):
    return [
        SimpleNamespace(url=f"{prefix}{i}", title=f"comunicado {i}", published_at=None, metadata=None)
        for i in range(n)
    ]


def _run_ir(monkeypatch, *, tracked: list[str], known_urls: set[str], n_items: int, cap: int = 50):
    sent: list[tuple] = []
    companies = [SimpleNamespace(ticker="KRKNF", ir_url="https://ir.example/news")]

    class _FakeProcessDocument:
        @staticmethod
        def send(*args):
            sent.append(args)

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: _FakeDB())
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db_, ticker=None: companies)
    monkeypatch.setattr(
        dramatiq_app,
        "_tracked_companies",
        lambda db_: [SimpleNamespace(ticker=t) for t in tracked],
    )
    monkeypatch.setattr(
        dramatiq_app,
        "_document_url_ingested",
        lambda db_, url: url in known_urls,
    )
    monkeypatch.setattr(dramatiq_app, "process_document", _FakeProcessDocument)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(
        dramatiq_app.settings, "document_enqueue_max_per_poll", cap, raising=False
    )
    import app.services.feed_ingestion_service as fis

    monkeypatch.setattr(fis, "FeedIngestionService", lambda: _FakeService(_items(n_items)))

    result = refresh_ir_pages(tenant_id=10, user_id=None)
    return result, sent


def test_empresa_no_seguida_no_encola_documentos(monkeypatch):
    result, sent = _run_ir(monkeypatch, tracked=[], known_urls=set(), n_items=3)
    assert sent == []
    assert result["documents_queued"] == 0
    assert result["documents_skipped_untracked"] == 1  # empresa omitida ANTES de sondear sus tres URLs


def test_empresa_seguida_encola_y_omite_ya_ingeridas(monkeypatch):
    known = {"https://ir.example/news-0", "https://ir.example/news-2"}
    result, sent = _run_ir(monkeypatch, tracked=["KRKNF"], known_urls=known, n_items=4)
    assert [args[1] for args in sent] == ["comunicado 1", "comunicado 3"]
    assert result["documents_queued"] == 2
    assert result["documents_skipped_known"] == 2
    assert result["documents_skipped_untracked"] == 0


def test_tope_por_pasada_se_declara_y_no_se_supera(monkeypatch):
    result, sent = _run_ir(monkeypatch, tracked=["KRKNF"], known_urls=set(), n_items=7, cap=3)
    assert len(sent) == 3
    assert result["documents_queued"] == 3
    assert result["documents_enqueue_capped"] is True


def test_untracked_company_never_polled(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("polled global company")
    monkeypatch.setattr(_FakeService, "poll_ir", forbidden)
    result, sent = _run_ir(monkeypatch, tracked=[], known_urls=set(), n_items=3)
    assert sent == [] and result["documents_queued"] == 0
    assert result.get("errors", []) == []
