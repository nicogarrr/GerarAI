"""Regression tests for point-in-time enforcement in ValuationService."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import valuation_service
from app.services.moat_service import MoatService
from app.valuation.point_in_time import LookaheadError


class _EngineReturning:
    def __init__(self, result: dict) -> None:
        self.result = result

    def build_context(self, db, company, current_price, as_of=None, **_):
        return object()

    def currency_input_units(self, context) -> list[str | None]:
        return []  # This point-in-time fixture supplies no monetary inputs.

    def value(self, context) -> dict:
        return self.result


def test_value_company_fails_closed_on_future_trace_period(monkeypatch) -> None:
    engine = _EngineReturning(
        {
            "ticker": "PIT",
            "model_type": "test",
            "status": "ok",
            "publishable": True,
            "trace": {"periods": {"revenue": "FY2999"}},
        }
    )
    company = SimpleNamespace(id=1, ticker="PIT")
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: engine)
    monkeypatch.setattr(valuation_service, "resolve_engine_key", lambda _company: "test")
    monkeypatch.setattr(valuation_service, "_position_price", lambda _db, _company_id, _as_of=None: 100.0)
    monkeypatch.setattr(valuation_service, "_free_data_trace", lambda _db, _company: None)
    monkeypatch.setattr(MoatService, "assess", lambda *_args, **_kwargs: {})

    with pytest.raises(LookaheadError, match="FY2999"):
        valuation_service.ValuationService().value_company(
            object(), company, as_of=date(2026, 9, 23)
        )


def test_value_company_accepts_trace_period_on_or_before_as_of(monkeypatch) -> None:
    engine = _EngineReturning(
        {
            "ticker": "PIT",
            "model_type": "test",
            "status": "ok",
            "publishable": True,
            "trace": {"periods": {"revenue": "FY2025"}},
        }
    )
    company = SimpleNamespace(id=1, ticker="PIT")
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: engine)
    monkeypatch.setattr(valuation_service, "resolve_engine_key", lambda _company: "test")
    monkeypatch.setattr(valuation_service, "_position_price", lambda _db, _company_id, _as_of=None: 100.0)
    monkeypatch.setattr(valuation_service, "_free_data_trace", lambda _db, _company: None)
    monkeypatch.setattr(MoatService, "assess", lambda *_args, **_kwargs: {})

    result = valuation_service.ValuationService().value_company(
        object(), company, as_of=date(2025, 12, 31)
    )

    assert result["status"] == "ok"
    assert result["publishable"] is True
