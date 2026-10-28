"""Costes modelados del track record simulado: comision + spread (SUPUESTO).

El supuesto se fija al ejecutar y queda persistido por trade; los historicos
sin costes nunca se retro-rellenan: su neto es N/D.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_cost_service import (
    PaperCostAssumptions,
    assumptions_from_settings,
    current_assumptions,
    execution_fee,
    pnl_net,
)
from app.services.paper_trading_service import apply_quote, pnl, scoreboard, trade_out

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
COSTS = PaperCostAssumptions(commission_flat=Decimal("1.00"), spread_bps=Decimal("5"), version="supuesto-v1|fija=1.00|spread_bps=5")


def body(**kwargs):
    return {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


def trade(**kwargs):
    return PaperTrade(**PaperProposal(**body(**kwargs)).model_dump(), author="LLM",
                      inference_label="inferencia", status="pending", created_at=NOW - timedelta(seconds=1))


def quote(price=100, at=NOW, currency="USD"):
    return {"live_c": price, "live_t": at.timestamp(), "currency": currency}


def test_execution_fee_flat_plus_spread():
    # notional 200 USD: 1,00 fija + 5 bps * 200 = 1,00 + 0,10 = 1,10
    assert execution_fee(Decimal("100"), Decimal("2"), COSTS) == Decimal("1.100000")
    zero = PaperCostAssumptions(commission_flat=Decimal(0), spread_bps=Decimal(0), version="v0")
    assert execution_fee(Decimal("100"), Decimal("2"), zero) == Decimal(0)


def test_assumptions_from_settings_defaults_and_override(monkeypatch):
    defaults = assumptions_from_settings(Settings())
    assert defaults.commission_flat == Decimal("1.00")
    assert defaults.spread_bps == Decimal("5")
    assert "supuesto" in defaults.version
    monkeypatch.setenv("PAPER_TRADE_COMMISSION_FLAT", "2.5")
    monkeypatch.setenv("PAPER_TRADE_SPREAD_BPS", "12")
    custom = assumptions_from_settings(Settings())
    assert custom.commission_flat == Decimal("2.5")
    assert custom.spread_bps == Decimal("12")
    assert "2.5" in custom.version and "12" in custom.version
    assert current_assumptions().commission_flat == Decimal("2.5")
    monkeypatch.setenv("PAPER_TRADE_SPREAD_BPS", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_entry_fill_stores_fee_and_version():
    row = trade()
    assert apply_quote(row, quote(98), NOW, costs=COSTS)
    assert row.entry_price == Decimal(98)
    assert row.entry_fee == Decimal("1.098000")  # 1,00 + 5bps de 196
    assert row.cost_assumption_version == COSTS.version
    assert row.exit_fee is None


def test_close_stores_exit_fee_and_net_pnl():
    row = trade()
    apply_quote(row, quote(100), NOW, costs=COSTS)
    later = NOW + timedelta(hours=1)
    apply_quote(row, quote(85, later), later, costs=COSTS)
    assert row.close_reason == "stop"
    assert row.exit_fee == Decimal("1.085000")  # 1,00 + 5bps de 170
    gross = pnl(row, row.exit_price)
    assert gross == Decimal(-30)
    assert pnl_net(row, row.exit_price) == gross - Decimal("1.1") - Decimal("1.085")


def test_unrealized_net_estimates_exit_fee_at_mark():
    row = trade()
    apply_quote(row, quote(100), NOW, costs=COSTS)
    later = NOW + timedelta(minutes=30)
    apply_quote(row, quote(110, later), later, costs=COSTS)
    net = pnl_net(row, row.mark_price)
    assert net == pnl(row, row.mark_price) - row.entry_fee - execution_fee(row.mark_price, row.quantity, COSTS)


def test_legacy_trade_without_fees_net_is_none():
    row = trade()
    apply_quote(row, quote(100), NOW, costs=None)  # sin supuesto persistido = legado
    later = NOW + timedelta(hours=1)
    apply_quote(row, quote(85, later), later, costs=None)
    assert row.entry_fee is None and row.exit_fee is None
    assert pnl(row, row.exit_price) == Decimal(-30)
    assert pnl_net(row, row.exit_price) is None


def test_trade_out_exposes_net_and_labels():
    row = trade()
    apply_quote(row, quote(100), NOW, costs=COSTS)
    later = NOW + timedelta(hours=1)
    apply_quote(row, quote(85, later), later, costs=COSTS)
    out = trade_out(row, later)
    assert out["entry_fee"] == Decimal("1.100000")
    assert out["exit_fee"] == Decimal("1.085000")
    assert out["cost_label"] == "supuesto"
    assert out["realized_pnl"] == Decimal(-30)
    assert out["realized_pnl_net"] == Decimal(-30) - Decimal("2.185")
    legacy = trade()
    apply_quote(legacy, quote(100), NOW, costs=None)
    out_legacy = trade_out(legacy, NOW)
    assert out_legacy["unrealized_pnl_net"] is None
    assert out_legacy["cost_label"] is None


def test_scoreboard_adds_net_columns_and_keeps_gross():
    priced = trade(proposal_key="k1")
    apply_quote(priced, quote(100), NOW, costs=COSTS)
    apply_quote(priced, quote(120, NOW + timedelta(hours=1)), NOW + timedelta(hours=1), costs=COSTS)
    legacy = trade(proposal_key="k2")
    apply_quote(legacy, quote(100), NOW, costs=None)
    apply_quote(legacy, quote(120, NOW + timedelta(hours=1)), NOW + timedelta(hours=1), costs=None)
    board = scoreboard([priced, legacy], NOW + timedelta(hours=2))
    group = board["groups"][0]
    assert group["closed"] == 2
    assert group["closed_net"] == 1  # el legado no tiene neto
    assert group["hit_rate"] == 1.0  # bruto: ambas ganan
    expected_net = (Decimal(40) - priced.entry_fee - priced.exit_fee)
    assert group["realized_pnl_net"] == expected_net
    assert group["realized_pnl"] == Decimal(80)
    assert group["hit_rate_net"] == 1.0
