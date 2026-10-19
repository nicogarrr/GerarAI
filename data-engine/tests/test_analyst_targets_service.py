"""Precios objetivo por analista: normalizacion y honestidad (sin red)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from app.services import analyst_targets_service as svc

TODAY = date(2026, 10, 19)


def rec(firm, when, target, prior=None, rating="Buy", action="Maintains"):
    return {
        "firm": firm,
        "date": datetime.fromisoformat(when),
        "rating": rating,
        "action": action,
        "price_target": target,
        "prior_target": prior,
    }


def test_keeps_latest_row_per_firm_and_orders_by_date_desc() -> None:
    rows = svc.normalize_rows(
        [
            rec("Citizens", "2026-09-01 10:00:00", 130.0),
            rec("Citizens", "2026-10-16 12:40:50", 90.0, prior=130.0, action="Lowers"),
            rec("Cantor Fitzgerald", "2026-10-15 10:40:53", 122.0),
        ],
        reference_price=50.0,
        today=TODAY,
    )
    assert [r.firm for r in rows] == ["Citizens", "Cantor Fitzgerald"]
    assert rows[0].price_target == 90.0 and rows[0].prior_target == 130.0
    assert rows[0].date == "2026-10-16"
    assert rows[0].upside_percent == 80.0
    assert rows[1].upside_percent == 144.0


def test_drops_rows_without_target_firm_or_readable_date_and_old_rows() -> None:
    rows = svc.normalize_rows(
        [
            rec("A", "2026-10-10 00:00:00", 0.0),
            rec("B", "2026-10-10 00:00:00", None),
            rec(None, "2026-10-10 00:00:00", 10.0),
            {"firm": "C", "date": "no-es-fecha", "price_target": 10.0},
            rec("D", "2025-01-01 00:00:00", 10.0),
            rec("E", "2026-10-10 00:00:00", 10.0),
        ],
        reference_price=None,
        today=TODAY,
    )
    assert [r.firm for r in rows] == ["E"]
    assert rows[0].upside_percent is None


def test_prior_target_zero_means_no_previous_target() -> None:
    rows = svc.normalize_rows(
        [rec("Barclays", "2026-10-09 13:18:08", 85.0, prior=0.0, action="Announces")],
        reference_price=None,
        today=TODAY,
    )
    assert rows[0].prior_target is None


def test_service_returns_empty_status_without_inventing_rows(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: {"records": [], "consensus": {}})
    result = asyncio.run(svc.AnalystTargetsService().get("zzzz"))
    assert result.status == "empty" and result.rows == []
    assert result.consensus is None and result.note


def test_service_failure_is_unavailable_and_not_cached(monkeypatch) -> None:
    calls = []

    def boom(symbol):
        calls.append(symbol)
        raise RuntimeError("yahoo caido")

    monkeypatch.setattr(svc, "_fetch_sync", boom)
    service = svc.AnalystTargetsService()
    first = asyncio.run(service.get("rklb"))
    asyncio.run(service.get("rklb"))
    assert first.status == "unavailable" and first.rows == [] and first.symbol == "RKLB"
    assert len(calls) == 2


def test_service_caches_successful_result_and_exposes_consensus(monkeypatch) -> None:
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {
            "records": [rec("TD Cowen", "2026-10-15 13:48:00", 90.0)],
            "consensus": {"current": 50.84, "high": 150.0, "low": 64.0, "mean": 102.15, "median": 102.5},
        }

    monkeypatch.setattr(svc, "_fetch_sync", fetch)
    service = svc.AnalystTargetsService()
    a = asyncio.run(service.get("RKLB"))
    b = asyncio.run(service.get("rklb"))
    assert a is b and len(calls) == 1
    assert a.status == "available" and a.reference_price == 50.84
    assert a.rows[0].upside_percent == 77.0
    assert a.consensus and a.consensus.high == 150.0
    assert a.source_url.endswith("/RKLB/analysis/")


def test_service_declares_currency_from_source(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": [rec("TD Cowen", "2026-10-15 13:48:00", 90.0)],
            "consensus": {"current": 50.84, "mean": 102.15},
            "currency": "USD",
        },
    )
    result = asyncio.run(svc.AnalystTargetsService().get("RKLB"))
    assert result.currency == "USD"


def test_service_without_declared_currency_keeps_none(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {"records": [], "consensus": {}, "currency": None},
    )
    result = asyncio.run(svc.AnalystTargetsService().get("zzzz"))
    assert result.currency is None


def test_consensus_only_is_available_with_aggregate_note(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": [],
            "consensus": {"current": 5.5, "mean": 9.07, "low": 7.0, "high": 11.0},
            "currency": "CAD",
        },
    )
    result = asyncio.run(svc.AnalystTargetsService().get("PNG.V"))
    assert result.status == "available"
    assert result.rows == [] and result.consensus and result.consensus.mean == 9.07
    assert result.note and "consenso agregado" in result.note
    assert result.currency == "CAD"
