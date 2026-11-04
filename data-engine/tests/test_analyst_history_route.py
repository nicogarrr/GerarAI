"""/api/companies/{ticker}/analyst-history: datos de mercado públicos, sin datos de tenant."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from app.services.analyst_history_service import AnalystHistory

client = TestClient(main.app)


def test_route_returns_service_payload(monkeypatch) -> None:
    seen: list[str] = []

    async def fake_get(symbol: str, **_kw) -> AnalystHistory:
        seen.append(symbol)
        return AnalystHistory(
            symbol=symbol.upper(), status="empty", fetched_at=1, note="Sin datos", note_code="no_history"
        )

    monkeypatch.setattr("app.api.routes.companies.analyst_history_service.get", fake_get)
    response = client.get("/api/companies/itx.mc/analyst-history")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "empty" and body["note_code"] == "no_history"
    assert body["min_samples"] == 5 and body["horizons"] == []
    assert seen == ["itx.mc"]
