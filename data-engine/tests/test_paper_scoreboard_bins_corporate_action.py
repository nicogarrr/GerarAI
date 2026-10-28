"""scoreboard(): los bins de conviction excluyen las cerradas con split sin ajustar.

Los grupos del scoreboard y calibration() ya las apartan («una cerrada con
split no es comparable»: la historia pre-split no se reescribe). Los bins de
conviction las contaban: un split 1:10 cerrado como pérdida del -90 % bajaba
la tasa de acierto de su bin.
"""
from decimal import Decimal

from app.models.paper_trading import PaperTrade
from app.services.paper_trading_service import scoreboard


def closed(conviction, exit_price, warning=None):
    row = PaperTrade(
        proposal_key=f"k{conviction}{exit_price}{warning}", ticker="ASTS", direction="long",
        horizon="short", thesis="t", conviction=Decimal(str(conviction)), proposed_entry=Decimal(100),
        stop=Decimal(80), target=Decimal(120), quantity=Decimal(1), author="LLM", inference_basis="b",
    )
    row.status, row.entry_price, row.exit_price = "closed", Decimal(100), Decimal(exit_price)
    row.currency, row.close_reason, row.corporate_action_warning = "USD", "target", warning
    return row


def test_conviction_bins_skip_closed_trades_with_corporate_action_warning():
    rows = [closed(0.9, 120), closed(0.9, 12, warning="split_cerrado_sin_ajustar")]
    data = scoreboard(rows)
    (group,) = data["groups"]
    assert group["closed"] == 1 and group["closed_distorted"] == 1
    high = data["conviction_bins"][2]
    assert (high["conviction_min"], high["closed"], high["hit_rate"]) == (0.75, 1, 1.0)


def test_conviction_bins_still_count_clean_losses():
    data = scoreboard([closed(0.6, 120), closed(0.6, 90)])
    middle = data["conviction_bins"][1]
    assert (middle["closed"], middle["hit_rate"]) == (2, 0.5)
