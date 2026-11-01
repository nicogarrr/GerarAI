"""sync_paper_dividends: un ticker que revienta no deja sin dividendos al resto.

Los errores del proveedor ya los convierte sync_company en «unavailable», pero
un fallo al guardar las filas de un ticker (dato raro, restriccion de la BD)
cortaba el bucle: los tickers siguientes del paper book se quedaban sin
sincronizar ese dia y en cada reintento. Un error transitorio (BD caida) si
debe seguir relanzando para que Dramatiq reintente.
"""

import pytest

import app.workers.dramatiq_app as workers


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, tickers):
        self.tickers = tickers
        self.rollbacks = 0

    def execute(self, _stmt):
        return _FakeResult([(t,) for t in self.tickers])

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _run(monkeypatch, tickers, failures):
    db = _FakeDb(tickers)
    monkeypatch.setattr(workers, "_session", lambda *_a, **_k: db)
    seen: list[str] = []

    async def fake_sync(self, _db, *, ticker):  # noqa: ARG001
        seen.append(ticker)
        if ticker in failures:
            raise failures[ticker]
        return {"ticker": ticker, "status": "ok"}

    monkeypatch.setattr(
        "app.services.dividend_ingestion_service.DividendIngestionService.sync_company",
        fake_sync,
    )
    return db, seen, workers.sync_paper_dividends.fn(tenant_id=917_401, user_id="paper-div-guard")


def test_un_ticker_que_falla_no_corta_el_resto(monkeypatch):
    db, seen, result = _run(
        monkeypatch, ["AAA", "BAD", "CCC"], {"BAD": ValueError("fila con importe imposible")}
    )
    assert seen == ["AAA", "BAD", "CCC"]
    assert result["status"] == "ok"
    assert result["synced"] == ["AAA", "CCC"]
    assert result["failed"] == ["BAD"]
    assert db.rollbacks >= 1  # la sesion queda limpia para el siguiente ticker


def test_error_transitorio_sigue_relanzando(monkeypatch):
    with pytest.raises(ConnectionError):
        _run(monkeypatch, ["AAA", "BAD"], {"BAD": ConnectionError("postgres caido")})
