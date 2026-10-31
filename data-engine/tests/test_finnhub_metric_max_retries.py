"""metric() acepta max_retries como quote(): valuation_metrics_service la llama con
max_retries=0 (7da8606c1) y sin el parametro cada refresco fallaba con TypeError."""
import asyncio

import app.services.connectors.finnhub as finnhub_mod


def test_metric_acepta_max_retries_y_lo_pasa_a_get(monkeypatch):
    llamadas = []

    async def fake_get(self, path, params, *, max_retries=None):
        llamadas.append((path, max_retries))
        return {"metric": {"peTTM": 12.0}}

    monkeypatch.setattr(finnhub_mod.FinnhubClient, "_get", fake_get)
    out = asyncio.run(finnhub_mod.FinnhubClient().metric("aapl", max_retries=0))
    assert out == {"peTTM": 12.0}
    assert llamadas == [("/stock/metric", 0)]


def test_metric_sin_max_retries_mantiene_el_default(monkeypatch):
    llamadas = []

    async def fake_get(self, path, params, *, max_retries=None):
        llamadas.append(max_retries)
        return {"metric": {}}

    monkeypatch.setattr(finnhub_mod.FinnhubClient, "_get", fake_get)
    asyncio.run(finnhub_mod.FinnhubClient().metric("AAPL"))
    assert llamadas == [None]
