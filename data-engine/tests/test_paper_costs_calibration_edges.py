"""Costes legados = N/D y calibracion que no inventa muestras."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_calibration_service import calibration
from app.services.paper_cost_service import pnl_net

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def body(**kwargs):
    return {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


def trade(**kwargs):
    return PaperTrade(**PaperProposal(**body(**kwargs)).model_dump(), author="LLM",
                      inference_label="inferencia", status="pending", created_at=NOW - timedelta(days=1))


def test_closed_before_cost_model_has_no_net():
    legacy = trade()
    legacy.status = "closed"
    legacy.entry_price, legacy.exit_price = Decimal(100), Decimal(110)
    legacy.entry_fee = Decimal("1.00")  # nacio con costes de entrada
    legacy.exit_fee = None  # pero cerro antes del modelo de costes de salida
    assert pnl_net(legacy, legacy.exit_price) is None  # neto N/D, no estimado


def test_trade_without_any_fees_has_no_net():
    legacy = trade()
    legacy.status = "closed"
    legacy.entry_price, legacy.exit_price = Decimal(100), Decimal(110)
    assert pnl_net(legacy, legacy.exit_price) is None


def test_closed_net_subtracts_both_fees_and_counts_null_dividends_as_zero():
    row = trade()
    row.status = "closed"
    row.entry_price, row.exit_price = Decimal(100), Decimal(110)
    row.entry_fee = row.exit_fee = Decimal("1.00")
    row.dividends_total = None  # aun no computado: equivale a 0, no a N/D
    assert pnl_net(row, row.exit_price) == Decimal(18)  # 20 bruto - 2 comisiones
    row.dividends_total = Decimal("0.5")
    assert pnl_net(row, row.exit_price) == Decimal("18.5")


def test_calibration_skips_closed_trade_without_entry():
    row = trade()
    row.status = "closed"  # cerrada sin entrada posible: pnl None, no es muestra
    result = calibration([row])
    assert result["brier"] is None
    assert result["muestra_insuficiente"] is True
    assert result["etiqueta"] == "INFERIDO"
