"""Supervivientes de mutacion en ``paper_cost_service`` (ronda 3).

El neto de un corto no estaba cubierto: un signo cambiado o un ``or True``
en la direccion daban el mismo resultado en todos los tests.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_cost_service import PaperCostAssumptions, execution_fee, pnl_net

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
COSTS = PaperCostAssumptions(commission_flat=Decimal("1.00"), spread_bps=Decimal("5"), version="v-test")
ZERO = PaperCostAssumptions(commission_flat=Decimal(0), spread_bps=Decimal(0), version="v0")


def short_trade(**kwargs):
    body = {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "short",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "110", "target": "80", "quantity": "3",
            "inference_basis": "Inferido a partir de los documentos oficiales"}
    row = PaperTrade(**PaperProposal(**body).model_dump(), author="LLM", inference_label="inferencia",
                     status="open", created_at=NOW - timedelta(days=1))
    row.entry_price = Decimal("100")
    row.entry_fee = Decimal("2")
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def test_short_open_net_gains_when_price_falls():
    # Corto de 3 a 100, precio 90: bruto +30; entrada 2; salida estimada sin costes 0.
    assert pnl_net(short_trade(), Decimal("90"), ZERO) == Decimal("28")


def test_short_open_net_loses_when_price_rises():
    # Precio 104: bruto -12 (no +12, ni -24 con un signo distinto de -1).
    assert pnl_net(short_trade(), Decimal("104"), ZERO) == Decimal("-14")


def test_short_closed_net_uses_persisted_exit_fee_and_dividends():
    row = short_trade(status="closed", exit_fee=Decimal("1.5"), dividends_total=Decimal("-0.5"))
    # bruto (100-80)*3 = 60; 60 - 2 - 1,5 - 0,5 = 56
    assert pnl_net(row, Decimal("80"), COSTS) == Decimal("56")


def test_net_is_none_without_entry_price_even_with_price():
    row = short_trade(entry_price=None)
    assert pnl_net(row, Decimal("90"), ZERO) is None


def test_execution_fee_rounds_half_up_at_the_sixth_decimal():
    # 0,5 bps de 0,01 = 0,0000005 -> HALF_UP da 0,000001 (HALF_EVEN daria 0).
    half = PaperCostAssumptions(commission_flat=Decimal(0), spread_bps=Decimal("0.5"), version="v")
    assert execution_fee(Decimal("0.01"), Decimal("1"), half) == Decimal("0.000001")
