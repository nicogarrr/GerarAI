from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.paper_trading import PaperTrade
from app.services.paper_calibration_service import MIN_BIN, MIN_CLOSED, calibration

NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)


def closed_trade(conviction, exit_price, *, author="LLM", currency="USD", horizon="short", reason="target"):
    row = PaperTrade(
        proposal_key=f"k{conviction}{exit_price}{author}{currency}{horizon}{id(object())}",
        ticker="ASTS", direction="long", horizon=horizon, thesis="t",
        conviction=Decimal(str(conviction)), proposed_entry=Decimal(100), stop=Decimal(80),
        target=Decimal(120), quantity=Decimal(1), author=author, inference_basis="b",
    )
    row.status, row.entry_price, row.exit_price = "closed", Decimal(100), Decimal(exit_price)
    row.currency, row.close_reason = currency, reason
    return row


def test_no_rows_is_nd_not_zero():
    result = calibration([], NOW)
    assert result["brier"] is None and result["bins"] == []
    assert result["muestra_insuficiente"] is True
    assert result["cerradas_con_resultado"] == 0
    assert result["etiqueta"] == "INFERIDO"


def test_only_llm_closed_trades_with_pnl_count():
    open_row = closed_trade(0.9, 110)
    open_row.status = "open"
    rows = [closed_trade(0.9, 110), closed_trade(0.9, 110, author="USER"), open_row]
    result = calibration(rows, NOW)
    assert result["propuestas_llm"] == 2
    assert result["cerradas_con_resultado"] == 1


def test_brier_value_and_reference():
    rows = [closed_trade(0.8, 110), closed_trade(0.8, 90)]
    result = calibration(rows, NOW)
    # (0.8-1)^2 y (0.8-0)^2 -> (0.04 + 0.64) / 2
    assert result["brier"] == pytest.approx(0.34)
    assert result["brier_referencia_sin_informacion"] == pytest.approx(0.25)
    assert result["muestra_insuficiente"] is True and "Muestra insuficiente" in result["aviso"]


def test_small_bins_are_nd_and_large_bins_report_gap():
    rows = [closed_trade(0.8, 110) for _ in range(MIN_BIN - 1)] + [closed_trade(0.2, 90)]
    result = calibration(rows, NOW)
    by = {b["rango"]: b for b in result["bins"]}
    high = by["0.75-1.00"]
    assert high["cerradas"] == MIN_BIN - 1 and high["tasa_acierto"] is None and high["etiqueta"] == "N/D"
    rows = [closed_trade(0.8, 110) for _ in range(3)] + [closed_trade(0.8, 90) for _ in range(2)]
    high = {b["rango"]: b for b in calibration(rows, NOW)["bins"]}["0.75-1.00"]
    assert high["cerradas"] == 5
    assert high["tasa_acierto"] == pytest.approx(0.6)
    assert high["hueco"] == pytest.approx(0.6 - 0.8)
    assert high["pnl_medio_por_divisa"] == {"USD": Decimal(2)}


def test_pnl_never_sums_currencies_and_reports_close_reasons():
    rows = [closed_trade(0.6, 110), closed_trade(0.6, 90, currency="EUR", reason="stop"),
            closed_trade(0.6, 105, horizon="five_years", reason="horizon")]
    result = calibration(rows, NOW)
    cells = {(g["horizonte"], g["divisa"]): g for g in result["pnl_por_horizonte"]}
    assert set(cells) == {("short", "USD"), ("short", "EUR"), ("five_years", "USD")}
    assert cells[("short", "EUR")]["pnl_realizado"] == Decimal(-10)
    assert cells[("short", "USD")]["tasa_acierto"] is None  # n < MIN_BIN: N/D
    assert result["cierres_por_motivo"] == {
        "five_years:horizon": 1, "short:stop": 1, "short:target": 1,
    }


def test_ten_bins_with_enough_sample_and_conviction_one_included():
    rows = [closed_trade(1.0 if i % 2 else 0.05, 110 if i % 3 else 90) for i in range(MIN_CLOSED)]
    result = calibration(rows, NOW)
    assert result["muestra_insuficiente"] is False and result["aviso"] is None
    assert len(result["bins"]) == 10
    assert sum(b["cerradas"] for b in result["bins"]) == MIN_CLOSED


def test_basis_reflects_costs_dividends_and_splits():
    """La base declarada no puede seguir diciendo "sin dividendos": PR #2637
    aplica dividendos con fuente y ajusta splits; lo que sigue fuera es FX,
    cash ledger y financiacion de cortos."""
    base = calibration([], NOW)["base"]
    assert "dividendos declarados aplicados con fuente" in base
    assert "splits" in base
    assert "sin FX, dividendos" not in base


def test_closed_trade_with_corporate_action_warning_excluded():
    """Misma regla que scoreboard(): una cerrada con split (warning persistido)
    no entra en los bins de acierto ni en cerradas_con_resultado; su P&L no
    es comparable porque la historia pre-split no se reescribe."""
    clean = closed_trade(0.9, 110)
    warned = closed_trade(0.9, 110)
    warned.corporate_action_warning = "split_cerrado_sin_ajustar"
    result = calibration([clean, warned], NOW)
    assert result["cerradas_con_resultado"] == 1
    assert result["propuestas_llm"] == 2
