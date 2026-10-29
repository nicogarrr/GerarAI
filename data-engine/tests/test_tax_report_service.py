"""TaxReportService contracts: FIFO lots, FX honesty, dividend grouping.

The tax report feeds an IRPF-style filing: a silently wrong number is worse
than a missing one. These contracts pin FIFO cost basis (including across
fiscal years), per-company dividend/withholding grouping, conversion at the
payment-date FX rate, and explicit incomplete states when no FX rate exists
- never a par conversion.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _tx(db, company, day, action, qty, price, currency="EUR", fees="0"):
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal(fees), currency=currency,
    ))
    db.commit()


def _eur_portfolio(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()


def test_fifo_consumes_oldest_lots_first(db):
    _eur_portfolio(db)
    c = _company(db, "AAA")
    _tx(db, c, date(2026, 1, 10), "buy", 10, 100)
    _tx(db, c, date(2026, 2, 10), "buy", 10, 120)
    _tx(db, c, date(2026, 6, 1), "sell", 15, 200)
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "AAA")
    assert row["proceeds_native"] == 3000.0
    assert row["cost_native"] == 1600.0  # 10x100 + 5x120
    assert row["gain_native"] == 1400.0


def test_cost_basis_spans_fiscal_years(db):
    _eur_portfolio(db)
    c = _company(db, "BBB")
    _tx(db, c, date(2025, 6, 1), "buy", 10, 100)
    _tx(db, c, date(2026, 3, 1), "sell", 10, 150)
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "BBB")
    assert row["cost_native"] == 1000.0
    assert row["gain_native"] == 500.0
    assert report["summary"]["sell_count"] == 1


def test_fifo_buy_fees_increase_lot_unit_cost(db):
    _eur_portfolio(db)
    c = _company(db, "ACQ")
    _tx(db, c, date(2026, 1, 10), "buy", 10, 100, fees="25")
    _tx(db, c, date(2026, 2, 10), "buy", 10, 120, fees="40")
    _tx(db, c, date(2026, 6, 1), "sell", 15, 200)
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "ACQ")
    assert row["proceeds_native"] == 3000.0
    assert row["cost_native"] == 1645.0  # (1000+25) + 5/10*(1200+40)
    assert row["gain_native"] == 1355.0


def test_wash_sale_defers_loss_on_top_of_buy_fees(db):
    _eur_portfolio(db)
    c = _company(db, "ACQWS")
    _tx(db, c, date(2026, 1, 5), "buy", 100, 10, fees="100")
    _tx(db, c, date(2026, 1, 10), "sell", 100, 8, fees="0")
    _tx(db, c, date(2026, 1, 20), "buy", 100, 8, fees="20")
    _tx(db, c, date(2026, 6, 15), "sell", 100, 11, fees="0")
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "ACQWS")
    first, second = row["sales"]
    assert first["raw_gain_native"] == -300.0
    assert first["blocked_loss_native"] == 300.0
    assert first["gain_native"] == 0.0
    assert second["cost_native"] == 1120.0  # 800 purchase + 20 fees + 300 deferred
    assert second["gain_native"] == -20.0


def test_dividend_and_withholding_grouped_per_company(db):
    _eur_portfolio(db)
    c = _company(db, "CCC")
    _tx(db, c, date(2026, 4, 1), "dividend", 1, 100)
    _tx(db, c, date(2026, 4, 1), "withholding", 1, 19)
    report = TaxReportService().compute_report(db, 2026)
    row = next(d for d in report["dividends"] if d["ticker"] == "CCC")
    assert row["dividends_base"] == 100.0
    assert row["withholding_base"] == 19.0
    assert {p["type"] for p in row["payments"]} == {"dividend", "withholding"}


def test_foreign_dividend_converted_at_payment_date_rate(db):
    _eur_portfolio(db)
    c = _company(db, "DDD")
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2026, 4, 13), rate=Decimal("0.90"), source="test"))
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2026, 4, 16), rate=Decimal("0.95"), source="test"))
    db.commit()
    # Tipo del 13/04 (2 días antes): el último publicado en o antes del pago;
    # nunca el del 16/04 (futuro). Un tipo de >7 días ya no se acepta.
    _tx(db, c, date(2026, 4, 15), "dividend", 1, 100, currency="USD")
    report = TaxReportService().compute_report(db, 2026)
    row = next(d for d in report["dividends"] if d["ticker"] == "DDD")
    assert row["dividends_native"] == 100.0
    assert row["dividends_base"] == 90.0  # latest rate on/before 2026-04-15


def test_missing_fx_dividend_is_explicit_never_par(db):
    _eur_portfolio(db)
    c = _company(db, "EEE")
    _tx(db, c, date(2026, 4, 15), "dividend", 1, 100, currency="USD")
    report = TaxReportService().compute_report(db, 2026)
    row = next(d for d in report["dividends"] if d["ticker"] == "EEE")
    assert row["dividends_base"] is None
    assert row["missing_fx"] is True
    assert report["summary"]["incomplete_fx"] is True
    assert "EEE" in report["summary"]["missing_fx"]
    assert report["summary"]["total_dividends_base"] is None


def test_missing_fx_realized_gain_reports_none(db):
    _eur_portfolio(db)
    c = _company(db, "FFF")
    _tx(db, c, date(2026, 1, 10), "buy", 10, 100, currency="USD")
    _tx(db, c, date(2026, 6, 1), "sell", 10, 150, currency="USD")
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "FFF")
    assert row["gain_native"] == 500.0
    assert row["gain_base"] is None
    assert report["summary"]["incomplete_fx"] is True


def test_prior_year_sale_does_not_leak_into_report(db):
    """The FIFO pass needs full history for basis, but a sale from a prior
    fiscal year must never appear in this year's realized totals."""
    _eur_portfolio(db)
    c = _company(db, "ZZ1")
    _tx(db, c, date(2025, 6, 1), "buy", 10, 100)
    _tx(db, c, date(2025, 8, 1), "sell", 10, 150)  # prior-year sale
    _tx(db, c, date(2026, 1, 10), "buy", 10, 100)
    _tx(db, c, date(2026, 3, 1), "sell", 10, 130)
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "ZZ1")
    assert report["summary"]["sell_count"] == 1
    assert row["sale_count"] == 1
    assert row["gain_native"] == 300.0  # only the 2026 sale
    assert [s["date"] for s in row["sales"]] == ["2026-03-01"]


def test_wash_sale_repurchase_within_two_months_blocks_and_defers_loss(db):
    """Sell at a loss, repurchase within 2 months: the loss is not computable
    and is deferred onto the repurchase lot's basis, surfacing when that lot
    is sold. Total economic gain is conserved across both sales."""
    _eur_portfolio(db)
    c = _company(db, "WS1")
    _tx(db, c, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, c, date(2026, 1, 10), "sell", 100, 8)   # loss -200
    _tx(db, c, date(2026, 1, 20), "buy", 100, 8)    # repurchase in window
    _tx(db, c, date(2026, 6, 15), "sell", 100, 11)  # sells the deferred lot
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "WS1")
    first, second = row["sales"]
    assert first["wash_sale_blocked"] is True
    assert first["gain_native"] == 0.0          # loss not computable
    assert first["blocked_loss_native"] == 200.0
    assert first["raw_gain_native"] == -200.0
    # Deferred loss raises the repurchase lot's basis: 800 + 200 = 1000.
    assert second["cost_native"] == 1000.0
    assert second["gain_native"] == 100.0       # 1100 proceeds - 1000 cost
    assert row["gain_native"] == 100.0          # -200 + 300 conserved
    assert row["blocked_loss_native"] == 200.0
    assert report["summary"]["total_blocked_loss_base"] == 200.0
    assert report["summary"]["wash_sale_rule"] == "es-irpf-2m"


def test_wash_sale_repurchase_after_window_lets_loss_compute(db):
    _eur_portfolio(db)
    c = _company(db, "WS2")
    _tx(db, c, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, c, date(2026, 1, 10), "sell", 100, 8)
    _tx(db, c, date(2026, 4, 1), "buy", 100, 8)  # > 2 months after the sale
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "WS2")
    (sale,) = row["sales"]
    assert sale["wash_sale_blocked"] is False
    assert sale["gain_native"] == -200.0
    assert sale["blocked_loss_native"] == 0.0
    assert sale["wash_sale_window_open"] is False


def test_wash_sale_partial_repurchase_blocks_proportionally(db):
    _eur_portfolio(db)
    c = _company(db, "WS3")
    _tx(db, c, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, c, date(2026, 1, 10), "sell", 100, 8)
    _tx(db, c, date(2026, 1, 20), "buy", 60, 8)  # only 60 of 100 repurchased
    _tx(db, c, date(2026, 6, 1), "buy", 1, 8)    # closes the data window
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "WS3")
    (sale,) = row["sales"]
    assert sale["wash_sale_blocked"] is True
    assert sale["blocked_loss_native"] == 120.0   # 60 shares x 2/share
    assert sale["gain_native"] == -80.0           # remaining loss computable
    assert sale["wash_sale_window_open"] is False


def test_wash_sale_never_blocks_gains(db):
    _eur_portfolio(db)
    c = _company(db, "WS4")
    _tx(db, c, date(2026, 1, 5), "buy", 100, 8)
    _tx(db, c, date(2026, 1, 10), "sell", 100, 10)  # gain +200
    _tx(db, c, date(2026, 1, 20), "buy", 100, 10)
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "WS4")
    (sale,) = row["sales"]
    assert sale["wash_sale_blocked"] is False
    assert sale["gain_native"] == 200.0
    assert sale["blocked_loss_native"] == 0.0


def test_wash_sale_backward_window_blocks_loss(db):
    """A buy in the two months BEFORE the loss sale also blocks it; the
    deferred loss lands on that still-held lot."""
    _eur_portfolio(db)
    c = _company(db, "WS5")
    _tx(db, c, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, c, date(2026, 1, 8), "buy", 100, 9)
    _tx(db, c, date(2026, 1, 10), "sell", 100, 8)  # FIFO sells the @10 lot
    _tx(db, c, date(2026, 6, 1), "sell", 100, 12)  # sells the @9 lot
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "WS5")
    first, second = row["sales"]
    assert first["wash_sale_blocked"] is True
    assert first["gain_native"] == 0.0
    assert first["blocked_loss_native"] == 200.0
    assert second["cost_native"] == 1100.0  # 900 + 200 deferred
    assert second["gain_native"] == 100.0


def test_wash_sale_window_boundary_is_inclusive(db):
    _eur_portfolio(db)
    inside = _company(db, "WS6")
    _tx(db, inside, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, inside, date(2026, 1, 10), "sell", 100, 8)
    _tx(db, inside, date(2026, 3, 10), "buy", 100, 8)  # exactly 2 months
    outside = _company(db, "WS7")
    _tx(db, outside, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, outside, date(2026, 1, 10), "sell", 100, 8)
    _tx(db, outside, date(2026, 3, 11), "buy", 100, 8)  # 2 months + 1 day
    report = TaxReportService().compute_report(db, 2026)
    sale_in = next(r for r in report["realized"] if r["ticker"] == "WS6")["sales"][0]
    sale_out = next(r for r in report["realized"] if r["ticker"] == "WS7")["sales"][0]
    assert sale_in["wash_sale_blocked"] is True
    assert sale_in["gain_native"] == 0.0
    assert sale_out["wash_sale_blocked"] is False
    assert sale_out["gain_native"] == -200.0


def test_wash_sale_backward_window_boundary_is_inclusive(db):
    """Espejo backward de test_wash_sale_window_boundary_is_inclusive: un
    remanente comprado EXACTAMENTE 2 meses antes de la venta en perdida es
    recompra (Manual AEAT 2025: "dentro de los dos meses anteriores"). La
    excepcion de compra inicial unica no aplica: hay saldo previo a la
    ventana. Se vende solo la mitad para que quede remanente en cartera
    (recompra = min(remanente, comprado en la ventana))."""
    _eur_portfolio(db)
    inside = _company(db, "WBA")
    _tx(db, inside, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, inside, date(2026, 1, 10), "buy", 100, 10)  # exactly 2 months
    _tx(db, inside, date(2026, 3, 10), "sell", 100, 8)  # FIFO consume el lote de ene-05
    outside = _company(db, "WBB")
    _tx(db, outside, date(2026, 1, 5), "buy", 100, 10)
    _tx(db, outside, date(2026, 1, 9), "buy", 100, 10)  # 2 months - 1 day
    _tx(db, outside, date(2026, 3, 10), "sell", 100, 8)
    report = TaxReportService().compute_report(db, 2026)
    sale_in = next(r for r in report["realized"] if r["ticker"] == "WBA")["sales"][0]
    sale_out = next(r for r in report["realized"] if r["ticker"] == "WBB")["sales"][0]
    assert sale_in["wash_sale_blocked"] is True
    assert sale_in["gain_native"] == 0.0
    assert sale_out["wash_sale_blocked"] is False
    assert sale_out["gain_native"] == -200.0


def test_wash_sale_open_window_flagged_when_data_runs_out(db):
    """A loss sale whose 2-month forward window extends past the latest
    available data stays provisionally computable but must be flagged."""
    _eur_portfolio(db)
    c = _company(db, "WS8")
    _tx(db, c, date(2026, 11, 1), "buy", 100, 10)
    _tx(db, c, date(2026, 12, 20), "sell", 100, 8)
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "WS8")
    (sale,) = row["sales"]
    assert sale["wash_sale_blocked"] is False
    assert sale["gain_native"] == -200.0
    assert sale["wash_sale_window_open"] is True
    assert row["wash_sale_window_open"] is True
    assert "WS8" in report["summary"]["wash_sale_window_open"]


def test_build_tax_summary_rows_without_fiscal_year(db: Session):
    """Regresion: GET /api/taxes/holdings llama sin fiscal_year (500 TypeError)."""
    from app.models.entities import Position
    from app.services.tax_report_service import build_tax_summary_rows

    company = _company(db, "AAPL")
    db.add(Position(company_id=company.id, quantity=Decimal("3")))
    db.commit()

    rows = build_tax_summary_rows(db)

    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["quantity"] == 3.0
    # F240: la UI de /taxes lista estas claves; los null quedan None (NA),
    # nunca 0 inventados.
    assert set(rows[0]) >= {
        "ticker",
        "quantity",
        "cost_basis",
        "market_value",
        "unrealized_pnl",
        "currency",
    }
    assert rows[0]["cost_basis"] is None
    assert rows[0]["market_value"] is None
    assert rows[0]["unrealized_pnl"] is None


def test_build_tax_summary_rows_passes_base_amounts_and_currency(db: Session):
    """F240: con importes cargados, la fila expone los valores base reales y
    la divisa base (nunca recalculados ni inventados)."""
    from app.models.entities import Position
    from app.services.tax_report_service import build_tax_summary_rows

    company = _company(db, "MSFT")
    db.add(
        Position(
            company_id=company.id,
            quantity=Decimal("6"),
            cost_basis_native=Decimal("2400"),
            cost_basis_base=Decimal("2200.50"),
            market_value_native=Decimal("2700"),
            market_value_base=Decimal("2480.75"),
            unrealized_pnl=Decimal("300"),
            unrealized_pnl_base=Decimal("280.25"),
            currency="USD",
            base_currency="EUR",
        )
    )
    db.commit()

    rows = build_tax_summary_rows(db)

    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "MSFT"
    assert row["cost_basis"] == 2200.50
    assert row["market_value"] == 2480.75
    assert row["unrealized_pnl"] == 280.25
    assert row["currency"] == "EUR"


def test_get_report_is_read_only_without_persisted_report(db):
    """GET path: calcula en memoria y NO escribe (ni TaxReport ni Portfolio)."""
    from sqlalchemy import func, select

    from app.models.entities import TaxReport

    company = _company(db, "AAPL")
    _tx(db, company, date(2025, 3, 10), "buy", 10, 100)

    data = TaxReportService().get_report(db, 2025)

    assert data["persisted"] is False
    assert data["generated_at"] is None
    assert db.scalar(select(func.count()).select_from(TaxReport)) == 0
    assert db.scalar(select(func.count()).select_from(Portfolio)) == 0


def test_regenerate_report_persists(db):
    """POST path: recalcula y persiste; un GET posterior devuelve lo guardado."""
    from sqlalchemy import func, select

    from app.models.entities import TaxReport

    company = _company(db, "AAPL")
    _tx(db, company, date(2025, 3, 10), "buy", 10, 100)

    service = TaxReportService()
    data = service.regenerate_report(db, 2025)
    assert data["persisted"] is True
    assert data["generated_at"] is not None
    assert db.scalar(select(func.count()).select_from(TaxReport)) == 1

    again = service.get_report(db, 2025)
    assert again["persisted"] is True
    assert again["summary"] == data["summary"]


def test_unattributed_dividend_without_fx_is_not_summed_as_zero(db):
    # Un dividendo no atribuido y SIN tipo de cambio: el subtotal de
    # dividendos no atribuidos no puede publicarse como 0.00 (sumaría la
    # fila ambigua como si no existiera). None, nunca un parcial.
    _eur_portfolio(db)
    db.add(Transaction(
        company_id=None, trade_date=date(2026, 3, 10), action="dividend",
        quantity=Decimal("0"), price=Decimal("25"),
        fees=Decimal("0"), currency="USD",
        raw_payload={"symbol": "MYST"},
    ))
    db.commit()
    report = TaxReportService().compute_report(db, 2026)
    assert report["summary"]["unattributed_dividends_base"] is None
    assert any(t.startswith("UNATTRIBUTED:MYST") for t in report["summary"]["unattributed_tickers"])


def test_unattributed_dividend_with_fx_is_summed(db):
    # Control: con FX real el subtotal sí se publica (25 USD x 0.9).
    _eur_portfolio(db)
    db.add(Transaction(
        company_id=None, trade_date=date(2026, 3, 10), action="dividend",
        quantity=Decimal("0"), price=Decimal("25"),
        fees=Decimal("0"), currency="USD",
        raw_payload={"symbol": "MYST"},
    ))
    db.add(FXRate(
        base_currency="EUR", quote_currency="USD",
        rate_date=date(2026, 3, 10), rate=Decimal("0.9"),
    ))
    db.commit()
    report = TaxReportService().compute_report(db, 2026)
    assert report["summary"]["unattributed_dividends_base"] == 22.5


def test_same_day_sale_imported_before_buys_matches_the_buys(db):
    """Caso ASTS/ZETA 9-oct: la venta tiene un id anterior a las compras del
    mismo día. Sin hora de ejecución, las compras van antes: no hay over_sell
    ni ganancia inventada."""
    _eur_portfolio(db)
    c = _company(db, "ZZZ")
    _tx(db, c, date(2026, 10, 9), "sell", 10, 110)  # id menor: importada antes
    _tx(db, c, date(2026, 10, 9), "buy", 4, 100)
    _tx(db, c, date(2026, 10, 9), "buy", 6, 100)

    report = TaxReportService().compute_report(db, 2026)
    bucket = next(b for b in report["realized"] if b["ticker"] == "ZZZ")
    assert bucket["over_sell"] is False
    assert Decimal(str(bucket["gain_base"])) == Decimal("100")
    assert report["summary"]["total_realized_gain_base"] == 100.0


def test_same_day_execution_time_wins_over_import_order(db):
    _eur_portfolio(db)
    c = _company(db, "TTT")
    _tx(db, c, date(2026, 5, 1), "buy", 10, 100)
    for action, qty, price, stamp in (
        ("sell", 10, 90, "20260601;100000"),
        ("buy", 10, 95, "20260601;150000"),
    ):
        db.add(Transaction(
            company_id=c.id, trade_date=date(2026, 6, 1), action=action,
            quantity=Decimal(qty), price=Decimal(price), fees=Decimal("0"),
            currency="EUR", raw_payload={"dateTime": stamp},
        ))
    db.commit()
    # Con hora, la venta de las 10:00 casa con el lote de mayo (no con el de las 15:00).
    report = TaxReportService().compute_report(db, 2026)
    bucket = next(b for b in report["realized"] if b["ticker"] == "TTT")
    assert bucket["over_sell"] is False
    # La pérdida de 100 queda bloqueada por la recompra de las 15:00 (regla de los 2 meses).
    assert Decimal(str(bucket["blocked_loss_native"])) == Decimal("100")


def test_over_sell_makes_realized_total_unreliable_not_exact(db):
    _eur_portfolio(db)
    c = _company(db, "OVS")
    _tx(db, c, date(2026, 3, 10), "sell", 5, 120)  # sin compras que la cubran
    summary = TaxReportService().compute_report(db, 2026)["summary"]
    assert summary["over_sell"] == ["OVS"]
    assert summary["total_realized_gain_base"] is None
    assert summary["net_taxable_base"] is None


def test_realized_gain_uses_sale_date_fx_once_dgt(db):
    """Zero native gain stays zero despite the purchase/sale FX change."""
    _eur_portfolio(db)
    c = _company(db, "FXL")
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2026, 1, 9), rate=Decimal("0.90"), source="test"))
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2026, 6, 1), rate=Decimal("0.80"), source="test"))
    db.commit()
    _tx(db, c, date(2026, 1, 10), "buy", 10, 100, currency="USD")
    _tx(db, c, date(2026, 6, 1), "sell", 10, 100, currency="USD")
    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["realized"] if r["ticker"] == "FXL")
    assert row["gain_native"] == 0.0
    assert row["gain_base"] == pytest.approx(0.0)
    sale = row["sales"][0]
    assert sale["cost_base"] == pytest.approx(800.0)
    assert sale["proceeds_base"] == pytest.approx(800.0)


def test_over_sell_sale_amounts_are_nd_not_invented(db):
    """Venta sin compras que la cubran: el exceso se valora a coste cero, así
    que el coste y la ganancia de ESA venta no se conocen. N/D en la venta y
    en el bloque del ticker; los datos observados (fecha, cantidad,
    transmisión) se conservan."""
    _eur_portfolio(db)
    c = _company(db, "OVS")
    _tx(db, c, date(2026, 3, 10), "sell", 5, 120)  # sin compras

    report = TaxReportService().compute_report(db, 2026)
    bucket = next(b for b in report["realized"] if b["ticker"] == "OVS")
    assert bucket["over_sell"] is True
    # Ganancia del ticker: N/D, no 600 con pinta de exacta.
    assert bucket["gain_native"] is None
    assert bucket["gain_base"] is None
    sale = bucket["sales"][0]
    assert sale["over_sell"] is True
    assert sale["gain_native"] is None
    assert sale["gain_base"] is None
    assert sale["cost_native"] is None
    assert sale["cost_base"] is None
    assert sale["raw_gain_native"] is None
    # Lo observado se conserva.
    assert sale["proceeds_native"] == 600.0
    assert sale["proceeds_base"] == 600.0
    assert sale["quantity"] == 5.0
    assert sale["date"] == "2026-03-10"
    assert sale["warning"] is not None and "over_sell" in sale["warning"]


def test_over_sell_bucket_gain_is_nd_but_other_tickers_keep_theirs(db):
    """Un ticker con over_sell no arrastra los demás: sus ganancias sí se
    calculan. Dentro del ticker afectado, la venta cubierta conserva su
    resultado y la descubierta sale N/D."""
    _eur_portfolio(db)
    ok = _company(db, "OKT")
    _tx(db, ok, date(2026, 1, 10), "buy", 10, 100)
    _tx(db, ok, date(2026, 6, 1), "sell", 10, 150)  # +500, cubierta
    ovs = _company(db, "OVS")
    _tx(db, ovs, date(2026, 1, 10), "buy", 10, 100)
    _tx(db, ovs, date(2026, 3, 1), "sell", 5, 150)   # +250, cubierta
    _tx(db, ovs, date(2026, 6, 1), "sell", 10, 120)  # quedan 5: over_sell 5

    report = TaxReportService().compute_report(db, 2026)
    ok_bucket = next(b for b in report["realized"] if b["ticker"] == "OKT")
    assert ok_bucket["over_sell"] is False
    assert ok_bucket["gain_base"] == 500.0

    bucket = next(b for b in report["realized"] if b["ticker"] == "OVS")
    assert bucket["over_sell"] is True
    # El bloque mezcla una venta con base desconocida: total N/D.
    assert bucket["gain_native"] is None
    assert bucket["gain_base"] is None
    covered, uncovered = bucket["sales"]
    assert covered["over_sell"] is False
    assert covered["gain_base"] == 250.0
    assert uncovered["over_sell"] is True
    assert uncovered["gain_base"] is None
    assert uncovered["cost_base"] is None
    assert uncovered["proceeds_base"] == 1200.0


def test_over_sell_casillas_row_is_nd_and_keeps_observed_proceeds(db):
    """Integración con la capa IRPF: la fila de casillas de una venta
    descubierta muestra N/D en adquisición y resultado, conserva la
    transmisión observada y anula las casillas globales."""
    _eur_portfolio(db)
    c = _company(db, "OVS")
    _tx(db, c, date(2025, 3, 10), "sell", 5, 120)  # sin compras

    report = TaxReportService().compute_report(db, 2025)
    block = report["filing"]["casillas"]["acciones_negociadas"]
    assert block["incomplete"] is True
    assert block["0328_transmision_global"] is None
    assert block["0331_adquisicion_global"] is None
    assert block["0339_suma_ganancias"] is None
    assert block["0340_suma_perdidas"] is None
    row = block["rows"][0]
    assert row["over_sell"] is True
    assert row["transmission_base"] == 600.0  # dato observado de la venta
    assert row["acquisition_base"] is None
    assert row["gain_base"] is None


def test_legacy_persisted_oversell_is_sanitized_on_get_and_export_without_write(db, monkeypatch):
    import asyncio
    import json
    from copy import deepcopy

    from app.api.routes.export import export_year
    from app.models import TaxReport

    original = [{"ticker": "OVS", "currency": "EUR", "over_sell": True, "gain_native": 600.0, "gain_base": 600.0,
                 "sales": [{"date": "2026-03-10", "quantity": 5, "proceeds_base": 600.0, "proceeds_native": 600.0,
                            "cost_base": 0.0, "cost_native": 0.0, "gain_base": 600.0, "gain_native": 600.0,
                            "raw_gain_native": 600.0, "over_sell": True}]}]
    stored = TaxReport(fiscal_year=2026, summary={}, dividends=[], realized=deepcopy(original), misc=[])
    db.add(stored)
    db.commit()
    monkeypatch.setattr(TaxReportService, "_build_filing", lambda *a, **k: {})
    read = TaxReportService().get_report(db, 2026)
    assert read["realized"][0]["gain_base"] is None
    assert read["realized"][0]["sales"][0]["cost_base"] is None
    assert read["realized"][0]["sales"][0]["proceeds_base"] == 600
    assert stored.realized == original
    assert not db.is_modified(stored, include_collections=True)

    response = export_year(2026, format="json", db=db)
    async def collect():
        chunks = [chunk async for chunk in response.body_iterator]
        return b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks)
    exported = json.loads(asyncio.run(collect()))
    assert exported["tax"]["realized"][0]["gain_base"] is None
    assert exported["tax"]["realized"][0]["sales"][0]["gain_native"] is None
    db.expire(stored)
    assert stored.realized == original



def test_over_sell_bucket_cost_is_nd_not_partial_zero(db):
    """Auditoría A: vender 5 a 120 sin compras dejaba el coste del ticker en
    0,00 (agregado) aunque la venta y la ganancia ya salían N/D. El coste del
    bloque mezcla una base desconocida: N/D; transmisión y cantidad reales."""
    _eur_portfolio(db)
    ovs = _company(db, "OVS")
    _tx(db, ovs, date(2026, 3, 10), "sell", 5, 120)
    report = TaxReportService().compute_report(db, 2026, include_filing=False)
    (bucket,) = report["realized"]
    assert bucket["over_sell"] is True
    assert bucket["cost_native"] is None
    assert bucket["gain_native"] is None and bucket["gain_base"] is None
    assert bucket["proceeds_native"] == 600.0
    assert bucket["sales"][0]["quantity"] == 5.0


def test_over_sell_bucket_cost_is_nd_even_with_partial_lots(db):
    _eur_portfolio(db)
    ovs = _company(db, "OVS")
    _tx(db, ovs, date(2026, 1, 5), "buy", 5, 100)
    _tx(db, ovs, date(2026, 6, 1), "sell", 10, 120)
    report = TaxReportService().compute_report(db, 2026, include_filing=False)
    (bucket,) = report["realized"]
    assert bucket["cost_native"] is None
    assert bucket["proceeds_native"] == 1200.0


def test_legacy_persisted_oversell_summary_totals_are_nd_on_read_and_export(db, monkeypatch):
    """Informe guardado antes del arreglo con plusvalía total y base imponible
    calculadas con coste cero: al leer (GET y exportación anual) salen N/D y
    el coste del ticker también; el JSON guardado no se reescribe."""
    import asyncio
    import json
    from copy import deepcopy

    from app.api.routes.export import export_year
    from app.models import TaxReport

    realized = [{"ticker": "OVS", "currency": "EUR", "over_sell": True, "proceeds_native": 600.0,
                 "cost_native": 0.0, "gain_native": 600.0, "gain_base": 600.0,
                 "sales": [{"date": "2026-03-10", "quantity": 5, "proceeds_base": 600.0, "proceeds_native": 600.0,
                            "cost_base": 0.0, "cost_native": 0.0, "gain_base": 600.0, "gain_native": 600.0,
                            "raw_gain_native": 600.0, "over_sell": True}]}]
    summary = {"fiscal_year": 2026, "base_currency": "EUR", "total_realized_gain_base": 600.0,
               "net_taxable_base": 600.0, "total_dividends_base": 0.0}
    stored = TaxReport(fiscal_year=2026, summary=deepcopy(summary), dividends=[],
                       realized=deepcopy(realized), misc=[])
    db.add(stored)
    db.commit()
    seen = {}

    def fake_filing(self, db, fiscal_year, data, tme=None):
        seen["summary"] = data["summary"]
        return {}

    monkeypatch.setattr(TaxReportService, "_build_filing", fake_filing)
    read = TaxReportService().get_report(db, 2026)
    assert read["summary"]["total_realized_gain_base"] is None
    assert read["summary"]["net_taxable_base"] is None
    assert read["summary"]["over_sell"] == ["OVS"]
    assert read["summary"]["total_dividends_base"] == 0.0
    # La capa IRPF (compensación de pérdidas) recibe el total ya anulado.
    assert seen["summary"]["total_realized_gain_base"] is None
    assert read["realized"][0]["cost_native"] is None
    assert read["realized"][0]["proceeds_native"] == 600.0
    assert stored.summary == summary
    assert stored.realized == realized

    response = export_year(2026, format="json", db=db)

    async def collect():
        chunks = [chunk async for chunk in response.body_iterator]
        return b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks)

    exported = json.loads(asyncio.run(collect()))
    assert exported["tax"]["summary"]["total_realized_gain_base"] is None
    assert exported["tax"]["summary"]["net_taxable_base"] is None
    assert exported["tax"]["realized"][0]["cost_native"] is None
    db.expire(stored)
    assert stored.summary == summary
