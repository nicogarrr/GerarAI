"""refresh_sec_filings con sesion SQLite real: contadores por empresa,
encolado de documentos con dedup/presupuesto/exclusion, cursor de lote
truncado que se reencola y fallos por empresa sin frenar el barrido.
Solo se sustituyen la red (poll_sec/ingest) y los send."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.feed_ingestion_service as fis
import app.workers.sec_batch as sec_batch
from app.models.entities import Base, Company, Document
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    e = SimpleNamespace(db=db, polls={}, doc_sends=[], requeue_sends=[])

    class FakeService:
        async def poll_sec(self, cik, ticker=None, limit=20):
            outcome = e.polls[ticker]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def ingest_news_result(self, db_, result, **kw):
            return {"created": 1}

    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    monkeypatch.setattr(worker, "process_document",
                        SimpleNamespace(send=lambda *a, **kw: e.doc_sends.append((a, kw))))
    original = worker.refresh_sec_filings
    monkeypatch.setattr(worker, "refresh_sec_filings", SimpleNamespace(
        fn=original.fn, send=lambda **kw: e.requeue_sends.append(kw)))
    e.original = original
    monkeypatch.setattr(worker.settings, "sec_document_jobs_enabled", False)
    return e


def _company(db, ticker, cik):
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik=cik, company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    return company


def _ok(*urls):
    items = [SimpleNamespace(url=u, title=f"t {u}", published_at=None, metadata={})
             for u in urls]
    return SimpleNamespace(errors=[], status="ok", items=items)


def test_empresas_ok_contadores_sin_jobs_documento(env):
    _company(env.db, "ACME", "0001")
    _company(env.db, "BETA", "0002")
    env.db.commit()
    env.polls = {"ACME": _ok("https://sec.gov/1"), "BETA": _ok("https://sec.gov/2")}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["companies_processed"] == 2
    assert out["news_ingested"] == 2 and out["truncated"] is False
    # F359: con los jobs SEC apagados no se encola nada y el contador lo deja visible.
    assert out["documents_queued"] == 0
    assert out["documents_skipped_sec_blocked"] == 2
    assert env.doc_sends == []


def test_fallo_de_una_empresa_se_registra_y_el_barrido_continua(env):
    _company(env.db, "ACME", "0001")
    _company(env.db, "BETA", "0002")
    env.db.commit()
    env.polls = {"ACME": RuntimeError("timeout"), "BETA": _ok()}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and out["companies_processed"] == 1
    assert out["errors"][0]["ticker"] == "ACME"
    assert out["errors"][0]["type"] == "RuntimeError"


def test_documentos_se_encolan_con_dedup_en_la_misma_corrida(env, monkeypatch):
    monkeypatch.setattr(worker.settings, "sec_document_jobs_enabled", True)
    _company(env.db, "ACME", "0001")
    env.db.commit()
    env.polls = {"ACME": _ok("https://sec.gov/1", "https://sec.gov/1", "https://sec.gov/2")}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["documents_queued"] == 2  # la URL repetida no se reencola
    assert len(env.doc_sends) == 2
    assert env.doc_sends[0][0][0] == "ACME"


def test_presupuesto_de_documentos_agotado_marca_cap(env, monkeypatch):
    monkeypatch.setattr(worker.settings, "sec_document_jobs_enabled", True)
    _company(env.db, "ACME", "0001")
    env.db.commit()
    env.polls = {"ACME": _ok("https://sec.gov/1", "https://sec.gov/2")}
    out = env.original.fn(tenant_id=1, user_id="u", document_budget=1)
    assert out["documents_queued"] == 1 and out["documents_enqueue_capped"] is True


def test_exclusion_operativa_bloquea_el_encolado(env, monkeypatch):
    monkeypatch.setattr(worker.settings, "sec_document_jobs_enabled", True)
    monkeypatch.setattr(worker.settings, "document_ingest_exclusions", "1:ACME")
    _company(env.db, "ACME", "0001")
    env.db.commit()
    env.polls = {"ACME": _ok("https://sec.gov/1", "https://sec.gov/2")}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["documents_skipped_excluded"] == 1 and env.doc_sends == []


def test_url_ya_ingerida_no_se_reencola(env, monkeypatch):
    monkeypatch.setattr(worker.settings, "sec_document_jobs_enabled", True)
    _company(env.db, "ACME", "0001")
    env.db.add(Document(source_type="sec", source_url="https://sec.gov/1",
                        title="doc", tenant_id=1))
    env.db.commit()
    env.polls = {"ACME": _ok("https://sec.gov/1", "https://sec.gov/3")}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["documents_skipped_known"] == 1 and out["documents_queued"] == 1


def test_lote_truncado_se_reencola_con_cursor(env, monkeypatch):
    monkeypatch.setattr(sec_batch, "BATCH_SIZE", 1)
    _company(env.db, "ACME", "0001")
    _company(env.db, "BETA", "0002")
    env.db.commit()
    env.polls = {"ACME": _ok(), "BETA": _ok()}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["truncated"] is True and out["status"] == "partial"
    assert out["next_cursor"] == "ACME" and out["companies_attempted"] == 1
    assert env.requeue_sends[0]["start_after"] == "ACME"
    assert env.requeue_sends[0]["tenant_id"] == 1


def test_error_de_sesion_devuelve_payload_estructurado(env, monkeypatch):
    def boom(tenant, user):
        raise ValueError("sin base de datos")

    monkeypatch.setattr(worker, "_session", boom)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_sec_filings"


def test_resultado_error_con_errores_e_item_sin_url(env, monkeypatch):
    monkeypatch.setattr(worker.settings, "sec_document_jobs_enabled", True)
    _company(env.db, "ACME", "0001")
    env.db.commit()
    env.polls = {"ACME": SimpleNamespace(
        errors=["SEC 403"], status="error",
        items=[SimpleNamespace(url=None, title="sin url", published_at=None, metadata={})])}
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["companies_processed"] == 0  # status=error no cuenta
    assert out["news_ingested"] == 1  # la ingesta corre igual (partial data)
    assert out["errors"][0]["message"] == "SEC 403"
    assert out["documents_queued"] == 0  # item sin url se salta
