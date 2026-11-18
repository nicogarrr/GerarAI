"""CNMV NOD v2: correcciones de la auditoria independiente (18-nov-2026).

1. Deriva HTML silenciosa: una pagina sin bloques solo devuelve vacio si el
   servidor declara "No se han encontrado resultados"; cualquier otro layout
   lanza CNMVNODParseError.
2. _companies_by_isin_and_ticker consumia db.scalars dos veces (el mapa por
   ticker quedaba siempre vacio): ahora materializa con .all() una vez.
3. El throttle de 1 s no serializaba hilos ni procesos: ahora es el pacer
   global "cnmv" (slots Redis + lock local), como finnhub/gdelt.
4. max_pages=0 no hace NINGUNA peticion, y un listado que excede max_pages
   llega con truncated=True (nunca a medias como completo).
5. Retry-After en 429/503 marca cooldown en el pacer global.
"""

from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Tenant
from app.services import cnmv_nod_ingestion
from app.services.connectors import cnmv_nod

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cnmv" / "nod_results_2026-11.html"
).read_text(encoding="utf-8")


# ---- 1. deriva silenciosa ----


def test_unknown_layout_without_blocks_raises():
    with pytest.raises(cnmv_nod.CNMVNODParseError):
        cnmv_nod._parse_page("<html><body><p>Bienvenido a la CNMV</p></body></html>")


def test_explicit_no_results_is_the_only_empty():
    entries, total = cnmv_nod._parse_page(
        "<html><body>No se han encontrado resultados</body></html>"
    )
    assert entries == [] and total == 0


# ---- 3. throttle serializado ----


def test_throttle_delegates_to_global_pacer(monkeypatch):
    calls = []
    monkeypatch.setattr(cnmv_nod._pacer, "wait_sync", lambda: calls.append(1))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FIXTURE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cnmv_nod.fetch_entries(date(2026, 11, 17), date(2026, 11, 18), client=client)
    assert calls == [1]  # cada GET pasa por el pacer global


def test_throttle_serializes_threads(monkeypatch):
    """Dos hilos concurrentes NO salen en el mismo hueco de 1 s.

    Reemplaza al repro del auditor sobre el global de modulo `_last_request_at`
    (el bug): ahora la propiedad la cumple el GlobalPacer local bajo lock.
    """
    import threading

    from app.services.connectors.global_pacing import GlobalPacer

    now = [1000.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    pacer = GlobalPacer(
        "cnmv-test",
        min_interval_seconds=1.0,
        redis_client_factory=lambda: None,
        monotonic=lambda: now[0],
        sleep=fake_sleep,
    )
    monkeypatch.setattr(cnmv_nod, "_pacer", pacer)
    barrier = threading.Barrier(2)
    finished_at: list[float] = []

    def work():
        barrier.wait(timeout=2)
        cnmv_nod._throttle()
        finished_at.append(now[0])

    threads = [threading.Thread(target=work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
    assert len(finished_at) == 2
    assert max(finished_at) - min(finished_at) >= 0.99  # slots separados >= 1 s


def test_pacer_is_global_not_module_global():
    from app.services.connectors.global_pacing import GlobalPacer

    assert isinstance(cnmv_nod._pacer, GlobalPacer)
    assert cnmv_nod._pacer.key == "cnmv"
    assert cnmv_nod._pacer.min_interval_seconds == 1.0
    assert not hasattr(cnmv_nod, "_last_request_at")


# ---- 4. presupuesto de paginas honesto ----


def test_max_pages_zero_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("max_pages=0 no debe hacer ninguna peticion")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetched = cnmv_nod.fetch_entries(
        date(2026, 11, 17), date(2026, 11, 18), client=client, max_pages=0
    )
    assert fetched.entries == []
    assert fetched.truncated is False
    assert fetched.fetched_pages == 0


def test_truncation_is_signaled_never_silent(monkeypatch):
    monkeypatch.setattr(cnmv_nod, "_throttle", lambda: None)
    page_one = FIXTURE.replace("Página 1 de 1", "Página 1 de 25")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page_one)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetched = cnmv_nod.fetch_entries(
        date(2026, 11, 17), date(2026, 11, 18), client=client, max_pages=1
    )
    assert fetched.truncated is True
    assert fetched.total_pages == 25
    assert fetched.fetched_pages == 1
    assert len(fetched.entries) == 2


# ---- 5. Retry-After ----


def test_retry_after_marks_global_cooldown(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(cnmv_nod, "_throttle", lambda: None)
    monkeypatch.setattr(cnmv_nod._pacer, "cool_down", lambda s: cooldowns.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"}, text="slow down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        cnmv_nod.fetch_entries(date(2026, 11, 17), date(2026, 11, 18), client=client)
    assert cooldowns == [30.0]


# ---- 2. universo de companies consumido una vez ----


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id=1, external_id="a"))
    db.commit()
    db.info["tenant_id"] = 1
    return db


def test_ticker_fallback_actually_finds_company(db=None):
    """Con ISIN ausente, la resolucion cae al ticker: antes el segundo

    recorrido del iterador scalars quedaba vacio y nunca encontraba nada."""
    db = _db()
    db.add(
        Company(
            ticker="EBRO",
            name="Ebro Foods",
            exchange="BME",
            company_type="compounders",
            valuation_model="dcf",
            isin=None,  # sin ISIN: solo el fallback por ticker puede resolverla
        )
    )
    db.commit()
    by_isin, by_ticker = cnmv_nod_ingestion._companies_by_isin_and_ticker(db)
    assert by_ticker["EBRO"].ticker == "EBRO"
    assert by_isin == {}


def test_ingest_signals_truncated_listing(monkeypatch, db=None):
    db = _db()
    fetch = cnmv_nod.CNMVNODFetch(entries=[], total_pages=25, fetched_pages=20, truncated=True)
    monkeypatch.setattr(cnmv_nod_ingestion, "fetch_entries", lambda *a, **k: fetch)
    result = cnmv_nod_ingestion.ingest_cnmv_nod(db, 1, date(2026, 11, 17), date(2026, 11, 18))
    assert result["truncated"] == 1
    assert result["received"] == 0
