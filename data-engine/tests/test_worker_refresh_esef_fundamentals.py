"""refresh_esef_fundamentals con sesion SQLite real: fase build (sin dir,
snapshot fresco global, build ok, 429 con Retry) y fase ingest (emisor
sin Company contado nunca inventado, error por emisor sin frenar el
chunk, auto-encolado por cursor). SOLO tests: no se toca codigo del
carril externa; se sustituyen red, servicio y script de build."""

import json
import sys
from datetime import date
from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.esef_issuer_mapping as mapping
import app.services.financial_ingestion_service as fis
from app.models.entities import Base, Company
from app.services.connectors.esef import EsefRateLimited
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    e = SimpleNamespace(db=db, sends=[], snapshot_dir=str(tmp_path), refresh_calls={})
    import app.core.config as config

    monkeypatch.setattr(config, "get_settings",
                        lambda: SimpleNamespace(esef_snapshot_dir=e.snapshot_dir))
    original = worker.refresh_esef_fundamentals
    monkeypatch.setattr(worker, "refresh_esef_fundamentals", SimpleNamespace(
        fn=original.fn, send=lambda *a, **kw: e.sends.append((a, kw))))
    e.original = original

    class FakeIngestion:
        async def refresh_from_esef(self, db=None, company=None):
            outcome = e.refresh_calls.get(company.ticker, "ok")
            if isinstance(outcome, Exception):
                raise outcome
            return {"ok": True}

    monkeypatch.setattr(fis, "FinancialIngestionService", FakeIngestion)
    return e


def _company(db, ticker):
    db.add(Company(ticker=ticker, name=f"{ticker} SA", exchange="BME", currency="EUR",
                   sector="T", industry="T", company_type="holding",
                   valuation_model="unassigned", special_sources=[], special_risks=[],
                   factor_tags=[]))


def _fresh_manifest(env):
    from pathlib import Path

    Path(env.snapshot_dir, "manifest.json").write_text(
        json.dumps({"fetched_at": date.today().isoformat()}))


def test_build_sin_directorio_configurado_skips(env):
    env.snapshot_dir = ""
    out = env.original.fn(tenant_id=1, user_id="u", phase="build")
    assert out["status"] == "skipped"
    assert out["reason"] == "esef_snapshot_dir_not_configured"


def test_build_con_snapshot_fresco_no_reconstruye_y_encola_ingesta(env):
    _fresh_manifest(env)
    out = env.original.fn(tenant_id=1, user_id="u", phase="build")
    assert out["status"] == "ok" and out["reason"] == "snapshot_fresh"
    assert env.sends[0][1] == {"phase": "ingest", "cursor": 0}


def _fake_build_module(monkeypatch, manifest=None, error=None):
    async def build(base, countries, day, client, package_fetcher=None):
        if error is not None:
            raise error
        return manifest

    module = SimpleNamespace(_fetch_package=lambda *a: None, build=build)
    monkeypatch.setitem(sys.modules, "build_esef_snapshots", module)


def test_build_ok_devuelve_recuento_y_encola_ingesta(env, monkeypatch):
    _fake_build_module(monkeypatch, manifest={"issuers": {"A": {}}, "unresolved": {"B": {}}})
    out = env.original.fn(tenant_id=1, user_id="u", phase="build")
    assert out["status"] == "ok" and out["phase"] == "build"
    assert out["issuers"] == 1 and out["unresolved"] == 1
    assert env.sends[0][1] == {"phase": "ingest", "cursor": 0}


def test_build_429_reencola_tras_la_ventana(env, monkeypatch):
    _fake_build_module(monkeypatch, error=EsefRateLimited("https://x", 120.0))
    with pytest.raises(dramatiq.Retry):
        env.original.fn(tenant_id=1, user_id="u", phase="build")


def test_ingest_emisores_ok_sin_company_y_error_por_emisor(env, monkeypatch):
    monkeypatch.setattr(mapping, "reviewed_tickers", lambda: ["AAA", "BBB", "CCC"])
    _company(env.db, "AAA")
    _company(env.db, "BBB")
    env.db.commit()
    env.refresh_calls = {"BBB": RuntimeError("snapshot ausente")}
    out = env.original.fn(tenant_id=1, user_id="u", phase="ingest", cursor=0)
    assert out["status"] == "ok" and out["phase"] == "ingest"
    assert out["results"] == {"AAA": "ok", "BBB": "error:RuntimeError",
                              "CCC": "no_company"}
    assert out["next_cursor"] is None and out["reviewed_total"] == 3


def test_ingest_se_autoencola_por_chunks(env, monkeypatch):
    monkeypatch.setattr(worker, "ESEF_REINGEST_CHUNK", 1)
    monkeypatch.setattr(mapping, "reviewed_tickers", lambda: ["AAA", "BBB"])
    _company(env.db, "AAA")
    _company(env.db, "BBB")
    env.db.commit()
    out = env.original.fn(tenant_id=1, user_id="u", phase="ingest", cursor=0)
    assert out["results"] == {"AAA": "ok"}
    assert out["next_cursor"] == 1
    assert env.sends[0][1] == {"phase": "ingest", "cursor": 1}


def test_error_de_sesion_devuelve_payload(env, monkeypatch):
    def boom(tenant, user):
        raise ValueError("sin base de datos")

    monkeypatch.setattr(worker, "_session", boom)
    out = env.original.fn(tenant_id=1, user_id="u", phase="build")
    assert out["status"] == "error" and out["actor"] == "refresh_esef_fundamentals"


def test_error_inesperado_en_ingest_rollback_y_payload(env, monkeypatch):
    def boom():
        raise RuntimeError("mapping roto")

    monkeypatch.setattr(mapping, "reviewed_tickers", boom)
    out = env.original.fn(tenant_id=1, user_id="u", phase="ingest", cursor=0)
    assert out["status"] == "error" and out["actor"] == "refresh_esef_fundamentals"
