"""Ramas de app/api/routes/insider.py sin red ni PG: cada ruta con sus
servicios sustituidos, el degradado a 'unavailable' y la cola 13F."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import insider as mod
from app.core.database import get_db
from app.models.entities import Base, Company, Document, InsiderFiling, InsiderTransaction, Tenant


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    db.commit()
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/insider")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    mod._first_13f_sync_at.clear()
    yield TestClient(app), db
    mod._first_13f_sync_at.clear()


def _boom(*_a, **_k):
    raise RuntimeError("fallo")


def test_signals_sin_notify_no_notifica(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(
        mod.insider_service, "get_signals_for_ticker",
        lambda *a, **k: {"ticker": "ACME", "signals": []},
    )
    out = client.get("/api/insider/signals", params={"ticker": "acme"}).json()
    assert "notification" not in out


def test_signals_con_notify_anade_notificacion(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(
        mod.insider_service, "get_signals_for_ticker",
        lambda *a, **k: {"ticker": "ACME", "signals": [{"x": 1}]},
    )
    seen = {}

    def _notify(ticker, signals):
        seen["args"] = (ticker, signals)
        return {"sent": False}

    monkeypatch.setattr(mod.insider_service, "maybe_notify_insider_buy", _notify)
    out = client.get("/api/insider/signals", params={"ticker": "acme", "notify": "true"}).json()
    assert out["notification"] == {"sent": False}
    assert seen["args"] == ("ACME", [{"x": 1}])


def test_feed_ok_y_degradado(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(mod.insider_feed, "build_feed", lambda db, **k: {"status": "ok", "count": 0})
    assert client.get("/api/insider/feed").json() == {"status": "ok", "count": 0}
    monkeypatch.setattr(mod.insider_feed, "build_feed", _boom)
    out = client.get("/api/insider/feed", params={"side": "buy", "days": 30}).json()
    assert out["status"] == "unavailable"
    assert out["reason"] == "RuntimeError"
    assert (out["side"], out["days"], out["count"]) == ("buy", 30, 0)
    assert out["proposed_sales"] == [] and out["transactions"] == []


def test_summary_delega_en_el_servicio(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(mod.insider_summary, "insider_summary", lambda db, t: {"ticker": t})
    assert client.get("/api/insider/summary", params={"ticker": "ACME"}).json() == {"ticker": "ACME"}


def test_ownership_signals_sin_holders_o_con_otra_razon_no_encola(env, monkeypatch):
    client, _ = env
    calls = []
    monkeypatch.setattr(mod, "_queue_first_13f_sync", lambda db: calls.append(1) or True)
    for payload in ({"holders": None}, {"holders": {"reason": "sin_datos"}}, {}):
        monkeypatch.setattr(mod, "ownership_signals", lambda db, t, p=payload: dict(p))
        client.get("/api/insider/ownership-signals", params={"ticker": "ACME"})
    assert calls == []


def test_ownership_signals_sin_sincronizar_encola_y_lo_dice(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(
        mod, "ownership_signals", lambda db, t: {"holders": {"reason": "sin_sincronizar"}}
    )
    monkeypatch.setattr(mod, "_queue_first_13f_sync", lambda db: True)
    holders = client.get("/api/insider/ownership-signals", params={"ticker": "A"}).json()["holders"]
    assert holders["sync"] == "queued"
    assert "13F" in holders["detail"]
    monkeypatch.setattr(mod, "_queue_first_13f_sync", lambda db: False)
    holders = client.get("/api/insider/ownership-signals", params={"ticker": "A"}).json()["holders"]
    assert "sync" not in holders


class _Db:
    info = {"tenant_id": 7, "user_id": 3}


def test_queue_13f_envia_una_vez_y_respeta_el_enfriamiento(monkeypatch):
    import app.workers.dramatiq_app as dq

    sent = []
    monkeypatch.setattr(
        dq.sync_investor_holdings, "send", lambda **k: sent.append(k), raising=False
    )
    mod._first_13f_sync_at.clear()
    assert mod._queue_first_13f_sync(_Db()) is True
    assert mod._queue_first_13f_sync(_Db()) is True  # dentro del enfriamiento
    assert sent == [{"tenant_id": 7, "user_id": 3}]
    mod._first_13f_sync_at.clear()


def test_queue_13f_sin_broker_devuelve_false_y_no_marca_enfriamiento(monkeypatch):
    import app.workers.dramatiq_app as dq

    monkeypatch.setattr(dq.sync_investor_holdings, "send", _boom, raising=False)
    mod._first_13f_sync_at.clear()
    assert mod._queue_first_13f_sync(_Db()) is False
    assert mod._first_13f_sync_at == {}


def test_filings_con_transacciones_y_divisa(env):
    client, db = env
    filing = InsiderFiling(
        tenant_id=1, accession_number="0001234567-24-000001", form="4",
        issuer_cik="1234567", issuer_ticker="ACME", filing_date=date(2024, 3, 1),
        parser_version="1.1",
    )
    db.add(filing)
    db.flush()
    cases = (("4", None), ("4", {"security_title": "Common", "currency": "EUR"}), ("3", {}))
    for i, (form, dq_) in enumerate(cases):
        db.add(InsiderTransaction(
            tenant_id=1, filing_id=filing.id, form=form, fingerprint=f"fp{i}",
            accession_number=filing.accession_number, insider="Ana", role="CEO",
            code="P", shares=Decimal("10"), price=Decimal("2"), tx_date=date(2024, 2, 28),
            data_quality=dq_, issuer_ticker="ACME",
        ))
    db.commit()
    out = client.get("/api/insider/filings", params={"ticker": "acme"}).json()
    assert out["status"] == "ok" and out["total"] == 1
    txs = out["filings"][0]["transactions"]
    assert [t["currency"] for t in txs] == ["USD", "EUR", None]
    assert txs[1]["security_title"] == "Common"


def test_filings_degrada_si_falla_la_base(env, monkeypatch):
    client, db = env
    monkeypatch.setattr(db, "scalars", _boom)
    out = client.get("/api/insider/filings", params={"ticker": "acme"}).json()
    assert out["status"] == "unavailable" and out["reason"] == "RuntimeError"
    assert out["filings"] == [] and out["foreign_issuer"] is None


def test_operations_ok_y_degradado(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(mod.insider_operations, "insider_operations", lambda db, days: {"days": days})
    assert client.get("/api/insider/operations", params={"days": 30}).json() == {"days": 30}
    monkeypatch.setattr(mod.insider_operations, "insider_operations", _boom)
    out = client.get("/api/insider/operations").json()
    assert out["status"] == "unavailable" and out["companies"] == []


def test_filings_sin_filings_devuelve_lista_vacia(env):
    client, _ = env
    out = client.get("/api/insider/filings", params={"ticker": "nada"}).json()
    assert out["status"] == "ok" and out["count"] == 0 and out["total"] == 0
    assert out["filings"] == [] and out["foreign_issuer"] is None


@pytest.mark.parametrize(
    ("forms", "expected"),
    [
        (None, None),  # empresa sin documentos SEC
        (["8-K", ""], None),  # solo formularios no concluyentes
        (["10-K", "6-K"], False),  # 10-K manda sobre 6-K
        (["40-f", "6-K"], True),  # solo formularios de FPI (normaliza caja)
    ],
)
def test_foreign_issuer_deriva_de_los_formularios(env, forms, expected):
    _, db = env
    company = Company(
        ticker="XYZ", name="Xyz", exchange="NYSE", company_type="large_cap",
        valuation_model="dcf",
    )
    db.add(company)
    db.flush()
    for form in forms or []:
        db.add(Document(
            company_id=company.id, title=f"doc {form}", source_type="SEC",
            metadata_={"form": form},
        ))
    db.commit()
    assert mod._foreign_issuer(db, "XYZ") is expected
    assert mod._foreign_issuer(db, "NOEXISTE") is None
