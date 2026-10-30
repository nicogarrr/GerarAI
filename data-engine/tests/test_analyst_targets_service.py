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


def _fake_yf(monkeypatch, currency):
    import sys
    import types

    class FakeTicker:
        upgrades_downgrades = None
        analyst_price_targets = {"mean": 4945.0, "current": 4170.0}
        fast_info = {"currency": currency}

        def __init__(self, symbol):
            pass

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))


def test_subunit_currency_is_not_collapsed_to_the_main_currency(monkeypatch) -> None:
    # CGEO.L: Yahoo da objetivos en peniques ("GBp"); "GBP" los haria x100.
    _fake_yf(monkeypatch, "GBp")
    assert svc._fetch_sync("CGEO.L")["currency"] == "GBX"
    _fake_yf(monkeypatch, "ZAc")
    assert svc._fetch_sync("SOL.JO")["currency"] == "ZAC"
    _fake_yf(monkeypatch, "GBP")
    assert svc._fetch_sync("X.L")["currency"] == "GBP"
    _fake_yf(monkeypatch, "usd")
    assert svc._fetch_sync("AAPL")["currency"] == "USD"


def test_fetch_sync_runs_the_three_yahoo_reads_concurrently(monkeypatch) -> None:
    """Las tres lecturas (upgrades_downgrades, analyst_price_targets,
    fast_info) son independientes; en serie la celda "Obj. analistas"
    tardaba ~8 s en asentar (medido en prod, CGEO.L 19 oct 2026). Barrera
    de 3: si alguna lectura se ejecutara en serie, la barrera romperia por
    timeout y el test fallaria."""
    import sys
    import threading
    import types

    barrier = threading.Barrier(3)

    class _Frame:
        def __len__(self) -> int:
            return 0

    class _FastInfo:
        def get(self, key):
            assert key in ("currency", "quoteType")
            return {"currency": "GBp", "quoteType": "EQUITY"}.get(key)

    class _Ticker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        @property
        def upgrades_downgrades(self):
            barrier.wait(timeout=5)
            return _Frame()

        @property
        def analyst_price_targets(self):
            barrier.wait(timeout=5)
            return {"mean": 5000.0, "current": 4255.0}

        @property
        def fast_info(self):
            barrier.wait(timeout=5)
            return _FastInfo()

    fake = types.SimpleNamespace(Ticker=_Ticker)
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    data = svc._fetch_sync("CGEO.L")
    assert data["records"] == []
    assert data["consensus"] == {"mean": 5000.0, "current": 4255.0}
    assert data["currency"] == "GBX"


def test_non_equity_symbol_is_rejected_instead_of_showing_another_instruments_targets(
    monkeypatch,
) -> None:
    """SPCK es el ETF; sus objetivos no son los de una accion individual."""
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": [rec("Firma X", "2026-10-15 13:48:00", 90.0)],
            "consensus": {"current": 30.0, "mean": 40.0},
            "currency": "USD",
            "quote_type": "ETF",
        },
    )
    result = asyncio.run(svc.AnalystTargetsService().get("SPCK"))
    assert result.status == "empty" and result.rows == [] and result.consensus is None
    assert result.note and "ETF" in result.note and "SPCK" in result.note


def test_equity_symbol_passes_the_guard(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": [rec("TD Cowen", "2026-10-15 13:48:00", 90.0)],
            "consensus": {"current": 50.84},
            "currency": "USD",
            "quote_type": "EQUITY",
        },
    )
    result = asyncio.run(svc.AnalystTargetsService().get("RKLB"))
    assert result.status == "available" and result.rows


def test_unknown_quote_type_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": [rec("TD Cowen", "2026-10-15 13:48:00", 90.0)],
            "consensus": {"current": 50.84},
            "currency": "USD",
            "quote_type": None,
        },
    )
    result = asyncio.run(svc.AnalystTargetsService().get("RKLB"))
    assert result.status == "available"


def test_non_equity_label_names_known_types() -> None:
    assert svc.non_equity_label("EQUITY") is None
    assert svc.non_equity_label(None) is None
    assert svc.non_equity_label("etf") == "un ETF"
    assert svc.non_equity_label("MUTUALFUND") == "un fondo"
    assert "WEIRDKIND" in (svc.non_equity_label("WEIRDKIND") or "")


def test_quote_type_failure_keeps_the_currency(monkeypatch) -> None:
    """Si yfinance falla al leer quoteType, la divisa no se pierde (#3067)."""
    import sys
    import types

    class FastInfo(dict):
        def get(self, key, default=None):
            if key == "quoteType":
                raise KeyError(key)
            return super().get(key, default)

    class FakeTicker:
        fast_info = FastInfo(currency="GBp")

        def __init__(self, symbol):
            pass

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    assert svc._fetch_currency_and_type("CGEO.L") == {"currency": "GBX", "quote_type": None}


def test_non_equity_labels_carry_spanish_accents() -> None:
    assert svc.non_equity_label("INDEX") == "un índice"
    assert svc.non_equity_label("OPTION") == "una opción"


def test_spcx_listed_equity_is_not_blocked_by_former_etf_identity(monkeypatch) -> None:
    """Nasdaq DTN2026-8: SpaceX uses SPCX from 2026-06-12, not the former ETF."""
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: {
        "records": [rec("Example firm", "2026-10-15 13:48:00", 190.0)],
        "consensus": {"current": 150.0},
        "currency": "USD",
        "quote_type": "EQUITY",
    })
    result = asyncio.run(svc.AnalystTargetsService().get("SPCX"))
    assert result.status == "available"
    assert result.rows[0].price_target == 190.0


def test_stale_provider_etf_metadata_is_not_overridden_for_spcx(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: {
        "records": [rec("Example firm", "2026-10-15 13:48:00", 40.0)],
        "consensus": {"current": 30.0, "mean": 40.0},
        "currency": "USD",
        "quote_type": "ETF",
    })
    result = asyncio.run(svc.AnalystTargetsService().get("SPCX"))
    assert result.status == "empty"
    assert not result.rows and result.consensus is None


def test_reused_symbol_discards_pre_listing_rows() -> None:
    rows = svc.normalize_rows([
        rec("Former ETF", "2026-06-11 13:00:00", 40.0),
        rec("New equity", "2026-06-12 13:00:00", 190.0),
    ], reference_price=150.0, today=TODAY, listed_from=date(2026, 6, 12))
    assert [row.firm for row in rows] == ["New equity"]
