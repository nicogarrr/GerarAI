"""El control vs consenso se aplica antes de publicar y deja la explicación."""

from __future__ import annotations

from types import SimpleNamespace

from app.services import thesis_consensus_service
from app.valuation.consensus_context import AnalystInputs, ConsensusSnapshot


def _valuation(**overrides):
    base = {
        "base_value": 100.0,
        "expected_value": 100.0,
        "current_price": 80.0,
        "currency": "USD",
        "publishable": True,
        "publication_blockers": [],
        "trace": {"engine": "standard_dcf", "price_currency": "USD", "price_source": "market"},
    }
    base.update(overrides)
    return base


def _company(ticker: str = "SYNTH") -> SimpleNamespace:
    return SimpleNamespace(ticker=ticker, id=1)


def _consensus(mean: float, *, currency: str = "USD", low: float | None = None, high: float | None = None):
    return ConsensusSnapshot(
        symbol="SYNTH",
        status="available",
        mean=mean,
        median=mean,
        low=low,
        high=high,
        currency=currency,
        source="Yahoo Finance",
        source_url="https://finance.yahoo.com/quote/SYNTH",
    )


def _db() -> SimpleNamespace:
    return SimpleNamespace(info={"tenant_id": 1})


def test_gap_above_35_forces_review_and_blocks_publication(monkeypatch) -> None:
    monkeypatch.setattr(thesis_consensus_service, "load_consensus", lambda db, company: _consensus(50))
    monkeypatch.setattr(
        thesis_consensus_service,
        "analyst_inputs_for_dcf",
        lambda db, company: AnalystInputs(),
    )
    valuation = _valuation()
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=True
    )
    assert result["status"] == "revisar"
    assert result["gap_pct"] == 1.0
    assert valuation["publishable"] is False
    assert "consenso_sin_conciliar" in valuation["publication_blockers"]
    assert result["data_rows"]


def test_gap_inside_35_is_reported_without_blocking(monkeypatch) -> None:
    monkeypatch.setattr(thesis_consensus_service, "load_consensus", lambda db, company: _consensus(90))
    monkeypatch.setattr(
        thesis_consensus_service,
        "analyst_inputs_for_dcf",
        lambda db, company: AnalystInputs(),
    )
    valuation = _valuation()
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=True
    )
    assert result["status"] == "dentro"
    assert valuation["publishable"] is True
    assert valuation["publication_blockers"] == []


def test_currency_mismatch_is_not_compared(monkeypatch) -> None:
    monkeypatch.setattr(
        thesis_consensus_service, "load_consensus", lambda db, company: _consensus(50, currency="EUR")
    )
    valuation = _valuation()
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=True
    )
    assert result["status"] == "no_comparable"
    assert valuation["publishable"] is True
    assert valuation["publication_blockers"] == []


def test_disabled_does_not_fetch_consensus(monkeypatch) -> None:
    called = False

    def fail(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("no debía llamarse")

    monkeypatch.setattr(thesis_consensus_service, "load_consensus", fail)
    valuation = _valuation()
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=False
    )
    assert result == {"status": "disabled"}
    assert called is False


def test_real_valuation_currency_dict_is_comparable(monkeypatch) -> None:
    """ValuationService escribe currency como dict; no debe leerse como texto."""
    monkeypatch.setattr(thesis_consensus_service, "load_consensus", lambda db, company: _consensus(90))
    monkeypatch.setattr(
        thesis_consensus_service,
        "analyst_inputs_for_dcf",
        lambda db, company: AnalystInputs(),
    )
    valuation = _valuation(
        currency={"price_currency": "USD", "reporting_currency": "USD", "status": "same"},
        value_currency="USD",
    )
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=True
    )
    assert result["status"] == "dentro"


def test_gbx_consensus_is_normalized_to_major_currency(monkeypatch) -> None:
    monkeypatch.setattr(
        thesis_consensus_service,
        "load_consensus",
        lambda db, company: _consensus(9000.0, currency="GBX"),
    )
    monkeypatch.setattr(
        thesis_consensus_service,
        "analyst_inputs_for_dcf",
        lambda db, company: AnalystInputs(),
    )
    valuation = _valuation(value_currency="GBP", currency={"price_currency": "GBP"})
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=True
    )
    assert result["status"] == "dentro"
    assert result["comparison"]["factor"] == 0.01
    assert result["comparison"]["consensus_mean"] == 90.0


def test_median_only_consensus_is_used(monkeypatch) -> None:
    snapshot = ConsensusSnapshot(
        symbol="SYNTH",
        status="available",
        mean=None,
        median=90.0,
        low=80.0,
        high=100.0,
        currency="USD",
        source="Yahoo Finance",
    )
    monkeypatch.setattr(thesis_consensus_service, "load_consensus", lambda db, company: snapshot)
    monkeypatch.setattr(
        thesis_consensus_service,
        "analyst_inputs_for_dcf",
        lambda db, company: AnalystInputs(),
    )
    valuation = _valuation()
    result = thesis_consensus_service.apply_consensus_control(
        _db(), _company(), valuation, enabled=True
    )
    assert result["status"] == "dentro"
    assert result["consensus_basis"] == "median"
