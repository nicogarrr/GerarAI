"""OOM de refresh_bottlenecks (prod, 2026-11-09 02:47/02:58 CET): memoria
acotada en la agregacion y una sola corrida a la vez.

Medicion (dataset sintetico, tracemalloc, N documentos+chunks de ~1 KB que
casan con los 6 temas + N noticias):
- antes: pico 15,1 MB con N=4000+4000 y 28,1 MB con N=8000+8000 (1,86x al
  doblar: aggregate() retenia cada Evidence con su texto por tema).
- despues: 6,3 MB y 8,3 MB (1,32x: quedan solo claves de identidad, orígenes,
  ids y min/max de fechas; el texto muere tras extract_themes).
El identity map NO acumula entidades con yield_per (SQLAlchemy 2.1): medido
aparte, no era el camino dominante.
"""

from __future__ import annotations

import tracemalloc
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, NewsEvent, Tenant
from app.services import bottleneck_service as bs
from app.workers import dramatiq_app
from tests.test_coalesce_on_success import FakeRedis

TEXT = "Semiconductors shortage hits capacity constraints. " * 18  # ~1 KB


def _session_with_news(n: int) -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.add(Tenant(id=1, external_id="oom-lab", name="lab"))
    db.flush()
    db.add_all([
        NewsEvent(
            title=f"news {i} chips shortage", url=f"https://n{i}.example.com",
            summary=TEXT, date=datetime(2026, 1, 2, tzinfo=UTC),
        )
        for i in range(n)
    ])
    db.flush()
    return db


def _peak_refresh(n: int) -> int:
    db = _session_with_news(n)
    try:
        tracemalloc.start()
        bs.refresh_signals(db)
        _, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()
        db.close()


def test_refresh_signals_memory_grows_sublinearly():
    """El pico al doblar el dataset debe crecer MUCHO menos que el dataset:
    con los textos retenidos por tema escalaba ~1,9x por duplicar filas."""
    small = _peak_refresh(4000)
    large = _peak_refresh(8000)
    assert large < small * 1.6, f"pico N=8000 {large} vs N=4000 {small}"


def test_aggregate_does_not_retain_texts():
    """aggregate() ya no guarda los Evidence: tras consumir el generador las
    referencias al texto deben quedar libres (solo claves/ids por tema)."""
    def stream():
        for i in range(2000):
            yield bs.Evidence(
                f"news_event:{i}", TEXT, datetime(2026, 1, 1, tzinfo=UTC),
                "example.com", (f"k{i}",),
            )
    tracemalloc.start()
    out = bs.aggregate(stream())
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # 2000 textos de ~1 KB retenidos serian >2 MB solo de texto; el
    # acumulador en flujo queda muy por debajo aun contando ids y claves.
    assert peak < 1_500_000, f"pico aggregate {peak}"
    assert out["Semiconductores"]["evidence_ids"][0] == "news_event:0"
    assert len(out["Semiconductores"]["evidence_ids"]) == 2000


# --- Candado de corrida unica (_single_flight) -------------------------------


def test_single_flight_skips_second_runner(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)
    client.set("running:job", "otro-proceso", nx=True, ex=3600)
    calls = []

    @dramatiq_app._single_flight("job", 3600)
    def job():
        calls.append(1)
        return {"status": "ok"}

    assert job() == {"status": "skipped", "actor": "job", "reason": "already_running"}
    assert calls == []


def test_single_flight_runs_and_releases(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)

    @dramatiq_app._single_flight("job", 3600)
    def job():
        return {"status": "ok"}

    assert job()["status"] == "ok"
    assert "running:job" not in client.store  # candado liberado al terminar
    assert job()["status"] == "ok"  # la siguiente corrida entra


def test_single_flight_releases_on_exception(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)

    @dramatiq_app._single_flight("job", 3600)
    def job():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        job()
    assert "running:job" not in client.store  # el reintento puede reclamar


def test_single_flight_fail_open_when_redis_down(monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: FakeRedis(raises=True))

    @dramatiq_app._single_flight("job", 3600)
    def job():
        return {"status": "ok"}

    assert job()["status"] == "ok"


def test_refresh_bottlenecks_actor_has_the_guard(monkeypatch):
    """El actor real: con el candado tomado ni siquiera abre sesion de BD."""
    client = FakeRedis()
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)
    client.set("running:refresh_bottlenecks", "otra-copia", nx=True, ex=3600)

    def _no_session(*args, **kwargs):
        raise AssertionError("no debia abrir sesion con el candado tomado")

    monkeypatch.setattr(dramatiq_app, "_session", _no_session)
    result = dramatiq_app.refresh_bottlenecks.fn(tenant_id=1)
    assert result["status"] == "skipped"
    assert result["reason"] == "already_running"
