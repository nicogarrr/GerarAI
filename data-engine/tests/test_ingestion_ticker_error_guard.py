"""Sincronizacion de dividendos y splits: un ticker que revienta no corta al resto.

``sync_company`` ya convierte los fallos del proveedor en «unavailable», pero
un fallo al GUARDAR las filas de un ticker (dato raro, restriccion de la BD)
salia del bucle: los tickers siguientes de la cartera se quedaban sin
dividendos/splits ese dia y en cada reintento (mismo orden, mismo fallo). Es
el patron que #4032 arreglo en el paper trading. Lo transitorio (BD o red
caidas) sigue relanzando para que Dramatiq reintente todo.
"""

import asyncio

import pytest

import app.workers.dramatiq_app as workers
from app.schemas.api import PortfolioDividendSyncOut
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.split_ingestion_service import SplitIngestionService


class _FakeDb:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        pass

    def close(self):
        pass


def _fake_sync(seen, failures):
    async def fake_sync(self, _db, *, ticker):  # noqa: ARG001
        seen.append(ticker)
        if ticker in failures:
            raise failures[ticker]
        return {"ticker": ticker, "status": "ok", "inserted": 1, "existing": 0}

    return fake_sync


@pytest.mark.parametrize("service_cls", [DividendIngestionService, SplitIngestionService])
def test_sync_portfolio_sigue_tras_un_ticker_que_falla(monkeypatch, service_cls):
    seen: list[str] = []
    monkeypatch.setattr(service_cls, "_portfolio_tickers", lambda self, _db: ["AAA", "BAD", "CCC"])
    monkeypatch.setattr(
        service_cls, "sync_company",
        _fake_sync(seen, {"BAD": ValueError("fila con importe imposible")}),
    )
    db = _FakeDb()

    result = asyncio.run(service_cls(fmp=object(), yahoo=object()).sync_portfolio(db))

    assert seen == ["AAA", "BAD", "CCC"]
    assert result["companies"] == 3
    assert result["synced"] == 2
    assert result["failed"] == 1
    assert [r["status"] for r in result["results"]] == ["ok", "failed", "ok"]
    assert "ValueError" in result["results"][1]["error"]
    assert result["provenance"]["coverage"] == "partial"
    assert db.rollbacks >= 1  # sesion limpia para el siguiente ticker
    if service_cls is DividendIngestionService:
        # POST /portfolio/dividends/sync lo devuelve con este contrato: el
        # estado «failed» no puede convertir la respuesta en un 500.
        PortfolioDividendSyncOut.model_validate(result)


@pytest.mark.parametrize("service_cls", [DividendIngestionService, SplitIngestionService])
def test_sync_portfolio_error_transitorio_relanza(monkeypatch, service_cls):
    monkeypatch.setattr(service_cls, "_portfolio_tickers", lambda self, _db: ["AAA", "BAD"])
    monkeypatch.setattr(
        service_cls, "sync_company", _fake_sync([], {"BAD": ConnectionError("postgres caido")})
    )
    with pytest.raises(ConnectionError):
        asyncio.run(service_cls(fmp=object(), yahoo=object()).sync_portfolio(_FakeDb()))


def _run_splits_actor(monkeypatch, failures):
    db = _FakeDb()
    seen: list[str] = []
    monkeypatch.setattr(workers, "_session", lambda *_a, **_k: db)
    monkeypatch.setattr(
        workers, "split_sync_tickers", lambda *_a, **_k: (["AAA", "BAD", "CCC"], None)
    )
    monkeypatch.setattr(SplitIngestionService, "sync_company", _fake_sync(seen, failures))
    result = workers.ingest_corporate_splits.fn(
        tenant_id=917_402, user_id="split-guard", scope="tracked", cursor=0
    )
    return db, seen, result


def test_actor_de_splits_sigue_tras_un_ticker_que_falla(monkeypatch):
    db, seen, result = _run_splits_actor(monkeypatch, {"BAD": ValueError("ratio imposible")})
    assert seen == ["AAA", "BAD", "CCC"]
    assert result["status"] == "ok"
    assert result["synced"] == 2
    assert result["failed"] == ["BAD"]
    assert result["inserted"] == 2
    assert db.rollbacks >= 1


def test_actor_de_splits_error_transitorio_relanza(monkeypatch):
    with pytest.raises(ConnectionError):
        _run_splits_actor(monkeypatch, {"BAD": ConnectionError("postgres caido")})
