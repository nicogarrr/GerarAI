"""Ramas de dramatiq_app sin cobertura: ingest_house_ptr y refresh_ir_pages.

ingest_house_ptr: lease ajeno no trabaja; el presupuesto de PDF se reparte
entre ano en curso y anterior (los PTR en papel, ``scanned``, no gastan
presupuesto); agotado el presupuesto no se pide el ano anterior; un fallo
pasa por _handle_actor_error con rollback; lease y sesion se liberan siempre.

refresh_ir_pages: empresa seguida sin ir_url no se sondea; los errores del
conector se declaran con ticker y fuente; un resultado con status "error" no
cuenta como empresa procesada; enlaces sin URL no se encolan; una URL repetida
se encola una vez; un ticker excluido de ingesta documental no encola.

NO prueba (declarado): ``if company.ticker.upper() not in tracked_tickers``
dentro del bucle de items es inalcanzable (el ``continue`` anterior ya descarta
las no seguidas); no se mide red ni Redis reales.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import politician_trades
from app.workers import dramatiq_app as worker

# --- ingest_house_ptr ---------------------------------------------------------


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(db=MagicMock(), lease="LEASE", released=[], acquired=[], rolled=[],
                        session_error=None, handled=[], calls=[])

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def acquire(key, **kw):
        e.acquired.append((key, kw["ttl_seconds"]))
        return e.lease

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(worker, "datetime", _Clock)
    return e


def _ingest_year(env, results):
    def fake(db, year, *, tenant_id=None, max_new=120, **kw):
        env.calls.append({"year": year, "tenant_id": tenant_id, "max_new": max_new})
        return results[year]
    return fake


def test_house_ptr_lease_ajeno_no_trabaja(env, monkeypatch):
    env.lease = None
    monkeypatch.setattr(politician_trades, "ingest_year", _ingest_year(env, {}))
    out = worker.ingest_house_ptr.fn(tenant_id=3, user_id="u")
    assert out == {"status": "skipped", "actor": "ingest_house_ptr", "reason": "lease_held"}
    assert env.calls == []
    assert env.acquired == [("ingest_house_ptr:3", 1800)]
    assert env.released == []  # sin lease propio no hay nada que liberar
    env.db.close.assert_called_once_with()


def test_house_ptr_reparte_presupuesto_entre_anos(env, monkeypatch):
    # 2026: 7 nuevos de los que 2 en papel -> 5 PDF gastados -> quedan 15.
    monkeypatch.setattr(politician_trades, "ingest_year", _ingest_year(env, {
        2026: {"year": 2026, "new": 7, "scanned": 2},
        2025: {"year": 2025, "new": 1, "scanned": 0},
    }))
    out = worker.ingest_house_ptr.fn(tenant_id=3, user_id="u", max_new=20)
    assert out["status"] == "ok" and [y["year"] for y in out["years"]] == [2026, 2025]
    assert env.calls == [
        {"year": 2026, "tenant_id": 3, "max_new": 20},
        {"year": 2025, "tenant_id": 3, "max_new": 15},
    ]
    assert env.released == [("ingest_house_ptr:3", "LEASE")]
    env.db.close.assert_called_once_with()


def test_house_ptr_presupuesto_agotado_no_pide_el_ano_anterior(env, monkeypatch):
    monkeypatch.setattr(politician_trades, "ingest_year", _ingest_year(env, {
        2026: {"year": 2026, "new": 5, "scanned": 0},
    }))
    out = worker.ingest_house_ptr.fn(tenant_id=3, user_id="u", max_new=5)
    assert [c["year"] for c in env.calls] == [2026]
    assert [y["year"] for y in out["years"]] == [2026]


def test_house_ptr_fallo_hace_rollback_y_libera(env, monkeypatch):
    boom = RuntimeError("indice caido")

    def fail(db, year, **kw):
        raise boom

    monkeypatch.setattr(politician_trades, "ingest_year", fail)
    out = worker.ingest_house_ptr.fn(tenant_id=3, user_id="u")
    assert out["status"] == "error" and env.handled[0][0] == "ingest_house_ptr"
    assert env.handled[0][1] is boom and env.handled[0][2] == {"tenant_id": 3}
    assert env.rolled == [env.db]
    assert env.released == [("ingest_house_ptr:3", "LEASE")]
    env.db.close.assert_called_once_with()


def test_house_ptr_sin_sesion_no_hay_nada_que_cerrar_ni_liberar(env):
    env.session_error = ValueError("tenant invalido")
    out = worker.ingest_house_ptr.fn(tenant_id=3, user_id="u")
    assert out["status"] == "error" and env.handled[0][1] is env.session_error
    assert env.rolled == [] and env.released == []
    env.db.close.assert_not_called()


# --- refresh_ir_pages ---------------------------------------------------------


class _Redis:
    def set(self, key, value, nx=False, ex=None):
        return True

    def get(self, key):
        return None

    def delete(self, key):
        return None

    def exists(self, key):
        return False


class _Service:
    def __init__(self, result, polled):
        self._result, self._polled = result, polled

    async def poll_ir(self, ir_url, *, ticker=None):
        self._polled.append((ir_url, ticker))
        return self._result

    def ingest_news_result(self, db, result, *, ticker=None):
        return {"created": 0}


def _item(url, title="comunicado"):
    return SimpleNamespace(url=url, title=title, published_at=None, metadata=None)


def _run_ir(monkeypatch, *, result=None, ir_url="https://ir.example/n", excluded=False):
    sent, polled, rolled = [], [], []
    company = SimpleNamespace(ticker="KRKNF", ir_url=ir_url)
    result = result or SimpleNamespace(items=[], errors=[], status="ok", source="ir")

    class _Send:
        @staticmethod
        def send(*args):
            sent.append(args)

    db = SimpleNamespace(info={}, commit=lambda: None, rollback=lambda: rolled.append(1), close=lambda: None)
    monkeypatch.setattr(worker, "_session", lambda t, u: db)
    monkeypatch.setattr(worker, "_companies", lambda d, ticker=None: [company])
    monkeypatch.setattr(worker, "_tracked_companies", lambda d: [SimpleNamespace(ticker="KRKNF")])
    monkeypatch.setattr(worker, "_document_urls_ingested", lambda d, urls: set())
    monkeypatch.setattr(worker, "_document_ingest_excluded", lambda tenant, ticker: excluded)
    monkeypatch.setattr(worker, "process_document", _Send)
    monkeypatch.setattr(worker, "_redis_client", lambda: _Redis())
    monkeypatch.setattr(worker.settings, "document_enqueue_max_per_poll", 50, raising=False)
    import app.services.feed_ingestion_service as fis

    monkeypatch.setattr(fis, "FeedIngestionService", lambda: _Service(result, polled))
    return worker.refresh_ir_pages(tenant_id=10, user_id=None), sent, polled


def test_ir_empresa_seguida_sin_ir_url_no_se_sondea(monkeypatch):
    out, sent, polled = _run_ir(monkeypatch, ir_url=None)
    assert polled == [] and sent == []
    assert out["companies_processed"] == 0 and out["errors"] == []


def test_ir_errores_del_conector_se_declaran_con_ticker_y_fuente(monkeypatch):
    result = SimpleNamespace(items=[_item("https://ir.example/a")], errors=["timeout pagina 2"],
                             status="ok", source="ir")
    out, sent, _ = _run_ir(monkeypatch, result=result)
    assert out["errors"] == [{"ticker": "KRKNF", "source": "ir", "message": "timeout pagina 2"}]
    assert out["companies_processed"] == 1
    assert [args[2] for args in sent] == ["https://ir.example/a"]  # el error no frena los enlaces validos


def test_ir_resultado_error_no_cuenta_como_procesada(monkeypatch):
    result = SimpleNamespace(items=[], errors=["403"], status="error", source="ir")
    out, _, polled = _run_ir(monkeypatch, result=result)
    assert polled == [("https://ir.example/n", "KRKNF")]
    assert out["companies_processed"] == 0
    assert out["errors"][0]["message"] == "403"


def test_ir_enlace_sin_url_no_se_encola(monkeypatch):
    result = SimpleNamespace(items=[_item(None), _item(""), _item("https://ir.example/ok")], errors=[],
                             status="ok", source="ir")
    out, sent, _ = _run_ir(monkeypatch, result=result)
    assert [args[2] for args in sent] == ["https://ir.example/ok"]
    assert out["documents_queued"] == 1


def test_ir_url_repetida_se_encola_una_vez(monkeypatch):
    result = SimpleNamespace(items=[_item("https://ir.example/x", "uno"), _item("https://ir.example/x", "dos")],
                             errors=[], status="ok", source="ir")
    out, sent, _ = _run_ir(monkeypatch, result=result)
    assert [args[1] for args in sent] == ["uno"]
    assert out["documents_queued"] == 1


def test_ir_ticker_excluido_de_ingesta_documental_no_encola(monkeypatch):
    result = SimpleNamespace(items=[_item("https://ir.example/a"), _item("https://ir.example/b")], errors=[],
                             status="ok", source="ir")
    out, sent, _ = _run_ir(monkeypatch, result=result, excluded=True)
    assert sent == []
    assert out["documents_skipped_excluded"] == 2 and out["documents_queued"] == 0
