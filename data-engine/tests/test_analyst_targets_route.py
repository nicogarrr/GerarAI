"""Fallback del listado revisado en /api/companies/{ticker}/analyst-targets."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

import main
from app.services.analyst_targets_service import (
    AnalystConsensus,
    AnalystTargets,
)

client = TestClient(main.app)


def _targets(symbol: str, status: str, currency: str | None, mean: float | None) -> AnalystTargets:
    return AnalystTargets(
        symbol=symbol,
        status=status,  # type: ignore[arg-type]
        currency=currency,
        fetched_at=int(time.time()),
        consensus=AnalystConsensus(mean=mean) if mean is not None else None,
        rows=[],
        note=None if status == "available" else "sin cobertura",
    )


def test_reviewed_listing_fallback_declares_symbol_and_currency(monkeypatch) -> None:
    async def fake_get(symbol: str) -> AnalystTargets:
        if symbol == "KRKNF":
            return _targets("KRKNF", "empty", "USD", None)
        if symbol == "PNG.V":
            return _targets("PNG.V", "available", "CAD", 9.07)
        raise AssertionError(symbol)

    monkeypatch.setattr("app.api.routes.companies.analyst_targets_service.get", fake_get)
    response = client.get("/api/companies/KRKNF/analyst-targets")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "KRKNF"
    assert body["status"] == "available"
    assert body["currency"] == "CAD"
    assert "PNG.V" in body["source"] and "CAD" in body["source"]


def test_fallback_never_adopts_a_currency_mismatch(monkeypatch) -> None:
    async def fake_get(symbol: str) -> AnalystTargets:
        if symbol == "KRKNF":
            return _targets("KRKNF", "empty", "USD", None)
        if symbol == "PNG.V":
            return _targets("PNG.V", "available", "USD", 9.07)  # divisa discordante
        raise AssertionError(symbol)

    monkeypatch.setattr("app.api.routes.companies.analyst_targets_service.get", fake_get)
    response = client.get("/api/companies/KRKNF/analyst-targets")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "empty"


def test_primary_available_skips_fallback(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_get(symbol: str) -> AnalystTargets:
        calls.append(symbol)
        return _targets(symbol, "available", "USD", 102.15)

    monkeypatch.setattr("app.api.routes.companies.analyst_targets_service.get", fake_get)
    response = client.get("/api/companies/RKLB/analyst-targets")
    assert response.status_code == 200, response.text
    assert calls == ["RKLB"]
    assert response.json()["symbol"] == "RKLB"
