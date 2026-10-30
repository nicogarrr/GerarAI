"""Annual full export of the private portfolio as CSV or JSON.

A safety net: yearly snapshots of transactions, positions, plan metrics,
tax summaries and journal entries, downloadable in one file.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.portfolio import _trade_price_fallbacks
from app.core.database import get_db
from app.core.local_date import local_today
from app.models import (
    Company,
    DecisionJournalEntry,
    PlanContribution,
    Position,
    TaxReport,
    Transaction,
)
from app.services.ibkr_cost_reconciliation import mask_cost_under_review, reconcile_ibkr_costs
from app.services.investment_plan_service import InvestmentPlanService
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.tax_report_service import (
    TaxReportService,
    sanitize_realized_over_sells,
    sanitize_summary_over_sells,
)

router = APIRouter()


def _num(value) -> float | None:
    """None se queda None (nunca 0): un nulo es 'sin dato', no cero."""
    return float(value) if value is not None else None


def _csv_cell(value: object) -> object:
    """Escape anti formula-injection: celdas de texto que empiezan por
    ``= + - @ | %`` llevan prefijo ``'`` (convención Excel/Sheets)."""
    if not isinstance(value, str):
        return value
    # Spreadsheet importers may ignore leading whitespace, and control
    # characters/full-width operators can initiate formulas in some locales.
    # Preserve the text verbatim after the existing apostrophe escape.
    dangerous = {"=", "+", "-", "@", "|", "%", "＝", "＋", "－", "＠"}
    if value[:1] in {"\t", "\r", "\n"} or value.lstrip()[:1] in dangerous:
        return "'" + value
    return value


@router.get("/{year}")
def export_year(
    year: int,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    if year < 2000 or year > 2200:
        raise HTTPException(status_code=400, detail="year must be between 2000 and 2200")

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    transactions = db.execute(
        select(Transaction, Company)
        .join(Company, Transaction.company_id == Company.id)
        .where(Transaction.trade_date >= start, Transaction.trade_date <= end)
        .order_by(Transaction.trade_date)
    ).all()

    tx_rows = [
        {
            "date": t.trade_date.isoformat(),
            "ticker": company.ticker,
            "action": t.action,
            "quantity": float(t.quantity),
            "price": float(t.price),
            "fees": float(t.fees),
            "currency": t.currency,
            "external_id": t.external_id,
        }
        for t, company in transactions
    ]

    positions = db.execute(select(Position, Company).join(Company, Position.company_id == Company.id)).all()
    position_list = [position for position, _ in positions]
    # Mismas reglas de veracidad que /portfolio/positions: sin cotizacion real
    # (precio = ultima operacion) la plusvalia es desconocida (A3) y un coste
    # IBKR pendiente de conciliar no se exporta como dato.
    quote_fallbacks = _trade_price_fallbacks(db, position_list)
    cost_checks = reconcile_ibkr_costs(db, position_list)
    position_rows = []
    for p, company in positions:
        held = bool(p.valuation_hold_reason)
        quote_missing = company.id in quote_fallbacks
        pnl_known = not held and not quote_missing and p.average_cost > 0
        row = {
            "ticker": company.ticker,
            "quantity": float(p.quantity),
            "average_cost": _num(p.average_cost),
            "market_price": None if held else float(p.market_price),
            "valuation_hold_reason": p.valuation_hold_reason,
            "quote_missing": quote_missing,
            # Importes nativos (en `currency`) y en divisa base (`base_currency`)
            # por separado: el CSV ponia el valor en base junto a la divisa nativa.
            "market_value_native": None
            if held
            else _num(p.market_value_native if p.market_value_native is not None else p.market_value),
            "cost_basis_native": _num(p.cost_basis_native),
            "unrealized_pnl_native": _num(p.unrealized_pnl) if pnl_known else None,
            "market_value_base": _num(p.market_value_base),
            "cost_basis_base": _num(p.cost_basis_base),
            "unrealized_pnl_base": _num(p.unrealized_pnl_base) if pnl_known else None,
            "currency": p.currency,
            "base_currency": p.base_currency,
            # as_of opcional: None es 'sin fecha', nunca cadena vacía ni crash.
            "as_of": p.as_of.isoformat() if p.as_of else None,
        }
        mask_cost_under_review(row, cost_checks.get(p.id))
        review = row.pop("cost_reconciliation", None)
        row["cost_review_status"] = review.get("status") if review else None
        position_rows.append(row)
    journal_rows = []
    entries = db.scalars(
        select(DecisionJournalEntry).where(
            DecisionJournalEntry.decision_date >= start,
            DecisionJournalEntry.decision_date <= end,
        )
    ).all()
    for entry in entries:
        journal_rows.append(
            {
                "id": entry.id,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "decision_date": entry.decision_date.isoformat(),
                "decision": entry.decision,
                "rationale": entry.rationale,
                "status": entry.status,
                "price": float(entry.price) if entry.price is not None else None,
                "company_id": entry.company_id,
            }
        )

    plan_service = InvestmentPlanService()
    plan = plan_service.get_plan(db)
    yearly_contributions = (
        db.scalars(
            select(PlanContribution)
            .where(
                PlanContribution.plan_id == plan.id,
                PlanContribution.date >= start,
                PlanContribution.date <= end,
            )
            .order_by(PlanContribution.date, PlanContribution.id)
        ).all()
        if plan is not None
        else []
    )
    contributions = [
        {
            "date": c.date.isoformat(),
            "amount": float(c.amount),
            "currency": c.currency,
            "note": c.note,
        }
        for c in yearly_contributions
    ]

    tax = None
    tax_error = None
    tax_report = db.scalar(select(TaxReport).where(TaxReport.fiscal_year == year))
    if tax_report is not None:
        tax = {
            "summary": sanitize_summary_over_sells(tax_report.summary, tax_report.realized),
            "dividends": tax_report.dividends,
            "realized": sanitize_realized_over_sells(tax_report.realized),
            "misc": tax_report.misc,
        }
    else:
        try:
            tax = TaxReportService().compute_report(db, year)
        except Exception as exc:
            # El error fiscal se propaga en el payload (nunca None
            # silencioso): el consumidor sabe que el bloque tax falta.
            tax_error = f"{type(exc).__name__}: tax computation unavailable"
            tax = {"status": "unavailable", "error": tax_error}

    fx = PortfolioFXService()
    payload = {
        "year": year,
        "exported_at": local_today().isoformat(),
        "base_currency": (fx.portfolio(db).base_currency if fx.portfolio(db) else "EUR"),
        "transactions": tx_rows,
        "positions": position_rows,
        "plan_contributions": contributions,
        "tax": tax,
        "journal_entries": journal_rows,
    }

    if format == "json":
        content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="gerarai-export-{year}.json"'},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "date", "ticker", "value1", "value2", "value3", "value4", "value5"])
    for row in tx_rows:
        writer.writerow(
            [
                _csv_cell(cell)
                for cell in [
                    "transaction",
                    row["date"],
                    row["ticker"],
                    row["action"],
                    row["quantity"],
                    row["price"],
                    row["currency"],
                    row["fees"],
                ]
            ]
        )
    for row in position_rows:
        writer.writerow(
            [
                _csv_cell(cell)
                for cell in [
                    "position",
                    row["as_of"],
                    row["ticker"],
                    row["quantity"],
                    row["average_cost"],
                    row["market_value_native"],
                    row["currency"],
                    row["unrealized_pnl_native"],
                ]
            ]
        )
    for row in contributions:
        writer.writerow(
            [
                _csv_cell(cell)
                for cell in [
                    "contribution",
                    row["date"],
                    "",
                    row["amount"],
                    row["currency"],
                    row["note"],
                    "",
                    "",
                ]
            ]
        )
    # Journal export must retain decisions in CSV too, including free text.
    # Keep the existing eight-column schema: date, company id, decision,
    # rationale, status, price and entry id. Text uses the same formula guard.
    for row in journal_rows:
        writer.writerow(
            [
                _csv_cell(cell)
                for cell in [
                    "journal",
                    row["decision_date"],
                    row["company_id"],
                    row["decision"],
                    row["rationale"],
                    row["status"],
                    row["price"],
                    row["id"],
                ]
            ]
        )
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="gerarai-export-{year}.csv"'},
    )
