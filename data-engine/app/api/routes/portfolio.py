import math
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db
from app.models import (
    CashBalance,
    Company,
    FundamentalModelVersion,
    FXRate,
    Position,
    ThesisVersion,
    Transaction,
)
from app.services.async_bridge import run_from_any_context
from app.services.company_resolver import resolve_company
from app.services.connectors.ibkr import IBKRFlexClient
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.dividend_projection_service import DividendProjectionService
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService, IBKRPnlNotReadyError
from app.services.market_refresh_service import MarketRefreshService
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.portfolio_ledger_service import (
    PortfolioLedgerService,
    PortfolioMixedCurrencyError,
    PortfolioOversellError,
)
from app.services.portfolio_snapshot_service import PortfolioSnapshotService
from app.services.risk_service import RiskService
from app.services.tax_report_service import CASH_UNIT_QUANTITIES
from app.services.tearsheet_service import TearsheetService
from app.services.tracked_analysis import enqueue_tracked_analysis, tracked_statuses

router = APIRouter()


class IBKRXmlImportRequest(BaseModel):
    xml: str = Field(min_length=20)


class IBKRCsvImportRequest(BaseModel):
    csv: str = Field(min_length=10)


# Umbral fiscal: más de 365 días en cartera = largo plazo.
LONG_TERM_HOLDING_DAYS = 365


def _fiscal_info(db: Session, company_id: int, as_of: date) -> dict:
    """Antigüedad de la posición y bucket fiscal (corto/largo plazo).

    La antigüedad se mide desde la primera compra registrada en el ledger;
    sin compras registradas no hay bucket (None).
    """
    first_buy = db.scalar(
        select(func.min(Transaction.trade_date)).where(
            Transaction.company_id == company_id,
            Transaction.action == "buy",
        )
    )
    if first_buy is None:
        return {"first_buy_date": None, "holding_days": None, "fiscal_bucket": None}
    holding_days = (as_of - first_buy).days
    return {
        "first_buy_date": first_buy.isoformat(),
        "holding_days": holding_days,
        "fiscal_bucket": "largo_plazo" if holding_days > LONG_TERM_HOLDING_DAYS else "corto_plazo",
    }


def _fiscal_info_batch(
    db: Session, as_of_by_company: dict[int, date]
) -> dict[int, dict]:
    """Primera compra por compañía en UNA query (anti N+1 de /positions).

    Respeta el ``as_of`` propio de cada posición para el cálculo de
    holding_days, igual que :func:`_fiscal_info` fila a fila.
    """
    if not as_of_by_company:
        return {}
    first_buys = {
        row[0]: row[1]
        for row in db.execute(
            select(Transaction.company_id, func.min(Transaction.trade_date))
            .where(
                Transaction.company_id.in_(set(as_of_by_company)),
                Transaction.action == "buy",
            )
            .group_by(Transaction.company_id)
        ).all()
    }
    result: dict[int, dict] = {}
    for company_id, as_of in as_of_by_company.items():
        first_buy = first_buys.get(company_id)
        if first_buy is None:
            result[company_id] = {
                "first_buy_date": None,
                "holding_days": None,
                "fiscal_bucket": None,
            }
            continue
        holding_days = (as_of - first_buy).days
        result[company_id] = {
            "first_buy_date": first_buy.isoformat(),
            "holding_days": holding_days,
            "fiscal_bucket": (
                "largo_plazo" if holding_days > LONG_TERM_HOLDING_DAYS else "corto_plazo"
            ),
        }
    return result


class PortfolioTransactionInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")
    action: Literal["buy", "sell", "dividend", "interest", "fee", "cash_misc"]
    quantity: Decimal = Field(ge=0)
    price: Decimal = Field(ge=0)
    trade_date: date
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=10)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("trade_date")
    @classmethod
    def _no_future_trade_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("trade_date cannot be in the future")
        return value


class PortfolioPriceInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    price: Decimal = Field(gt=0)
    as_of: date | None = None


class PortfolioConfigurationInput(BaseModel):
    base_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")


class FXRateInput(BaseModel):
    base_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    quote_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    rate: Decimal = Field(gt=0)
    rate_date: date
    source: str = Field(default="manual", min_length=1, max_length=80)


def _transaction_payload(transaction: Transaction, company: Company) -> dict:
    return {
        "id": transaction.id,
        "ticker": company.ticker,
        "action": transaction.action,
        "quantity": float(transaction.quantity),
        "price": float(transaction.price),
        "fees": float(transaction.fees),
        "currency": transaction.currency,
        "trade_date": transaction.trade_date.isoformat(),
        "notes": (transaction.raw_payload or {}).get("notes"),
        "created_at": transaction.created_at.isoformat(),
        "updated_at": transaction.updated_at.isoformat(),
    }


@router.get("/summary")
def portfolio_summary(db: Session = Depends(get_db)) -> dict:
    risk = RiskService().dashboard(db)
    return {
        "total_value": risk["total_value"],
        "equity_value": risk["equity_value"],
        "cash_assets_base": risk["cash_assets_base"],
        "margin_debt_base": risk["margin_debt_base"],
        "cash": risk["cash"],
        "top_1_weight": risk["top_1_weight"],
        "top_5_weight": risk["top_5_weight"],
        "alerts": risk["alerts"],
        "status": risk["status"],
        "base_currency": risk["base_currency"],
        "cash_native": risk["cash_native"],
        "missing_fx": risk["missing_fx"],
        "data_as_of": risk.get("data_as_of"),
        "cash_as_of": risk.get("cash_as_of"),
        "fx_rates": risk.get("fx_rates", []),
        "valuation_dates_differ": risk.get("valuation_dates_differ", False),
        "provenance": risk.get("provenance"),
    }


@router.get("/intelligence")
def portfolio_intelligence(
    years: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    return PortfolioIntelligenceService().build(db, years=years)


@router.get("/data-quality")
def portfolio_data_quality(db: Session = Depends(get_db)) -> dict:
    from app.services.portfolio_quality_service import portfolio_quality
    return portfolio_quality(db)


@router.get("/snapshots")
def portfolio_snapshots(
    start: date | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": snapshot.id,
            "portfolio_id": snapshot.portfolio_id,
            "snapshot_date": snapshot.snapshot_date,
            "base_currency": snapshot.base_currency,
            "positions_value_base": snapshot.positions_value_base,
            "cash_value_base": snapshot.cash_value_base,
            "total_value_base": snapshot.total_value_base,
            "net_external_flow_base": snapshot.net_external_flow_base,
            "daily_return": snapshot.daily_return,
            "cumulative_twr": snapshot.cumulative_twr,
            "pricing_coverage": snapshot.pricing_coverage,
            "source": snapshot.source,
            "metadata": snapshot.metadata_,
        }
        for snapshot in PortfolioSnapshotService().history(db, start=start, limit=limit)
    ]


@router.post("/snapshots/capture")
def capture_portfolio_snapshot(
    as_of: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    snapshot = PortfolioSnapshotService().capture(
        db,
        as_of=as_of,
        source="manual_capture",
    )
    db.commit()
    db.refresh(snapshot)
    return {
        "id": snapshot.id,
        "snapshot_date": snapshot.snapshot_date,
        "total_value_base": snapshot.total_value_base,
        "pricing_coverage": snapshot.pricing_coverage,
        "daily_return": snapshot.daily_return,
        "cumulative_twr": snapshot.cumulative_twr,
        "metadata": snapshot.metadata_,
    }


@router.get("/configuration")
def portfolio_configuration(db: Session = Depends(get_db)) -> dict:
    portfolio = PortfolioFXService().portfolio(db)
    return {
        "id": portfolio.id if portfolio else None,
        "name": portfolio.name if portfolio else "Main",
        "base_currency": portfolio.base_currency if portfolio else "EUR",
        "is_default": portfolio.is_default if portfolio else True,
    }


@router.put("/configuration")
def update_portfolio_configuration(
    payload: PortfolioConfigurationInput,
    db: Session = Depends(get_db),
) -> dict:
    service = PortfolioFXService()
    ledger = PortfolioLedgerService()
    try:
        portfolio = service.set_base_currency(db, payload.base_currency)
        company_ids = list(db.scalars(select(Position.company_id)).all())
        for company_id in company_ids:
            ledger.rebuild_position(db, company_id)
        db.commit()
        return {
            "id": portfolio.id,
            "name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "is_default": portfolio.is_default,
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/fx-rates")
def list_fx_rates(
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": row.id,
            "base_currency": row.base_currency,
            "quote_currency": row.quote_currency,
            "rate": float(row.rate),
            "rate_date": row.rate_date.isoformat(),
            "source": row.source,
        }
        for row in db.scalars(
            select(FXRate)
            .order_by(desc(FXRate.rate_date), FXRate.base_currency, FXRate.quote_currency)
            .limit(limit)
            .offset(offset)
        ).all()
    ]


@router.post("/fx-rates", status_code=201)
def upsert_fx_rate(payload: FXRateInput, db: Session = Depends(get_db)) -> dict:
    service = PortfolioFXService()
    ledger = PortfolioLedgerService()
    try:
        row = service.upsert_rate(
            db,
            base_currency=payload.base_currency,
            quote_currency=payload.quote_currency,
            rate=payload.rate,
            rate_date=payload.rate_date,
            source=payload.source,
        )
        company_ids = list(db.scalars(select(Position.company_id)).all())
        for company_id in company_ids:
            ledger.rebuild_position(db, company_id)
        db.commit()
        db.refresh(row)
        return {
            "id": row.id,
            "base_currency": row.base_currency,
            "quote_currency": row.quote_currency,
            "rate": float(row.rate),
            "rate_date": row.rate_date.isoformat(),
            "source": row.source,
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/dividends/sync")
async def sync_portfolio_dividends(db: Session = Depends(get_db)) -> dict:
    """Ingest declared dividends for every held company from the data provider.

    Deduped per (company, ex_date, amount). Provider failures mark the symbol
    unavailable; nothing is fabricated. Dividend cash stays a manual ledger
    entry.
    """
    # La ingesta mezcla sqlalchemy y el proveedor entre sus awaits: hilo del
    # pool con la corutina puenteado, no el event loop.
    return await run_in_threadpool(
        lambda: run_from_any_context(DividendIngestionService().sync_portfolio(db))
    )


@router.get("/dividends")
def portfolio_dividends(db: Session = Depends(get_db)) -> dict:
    """Trailing-12-month declared dividend yield per position and portfolio.

    Coverage is explicit: positions without ingested dividend records show
    null yields instead of zeros.
    """
    return DividendIngestionService().portfolio_yields(db)


@router.get("/dividends/projection")
def portfolio_dividend_projection(
    months: Annotated[int, Query(ge=1, le=24)] = 12,
    db: Session = Depends(get_db),
) -> dict:
    """Proyeccion mes a mes de dividendos con retencion de origen e IRPF.

    INFERIDO: replica mecanica de lo declarado en los ultimos 12 meses
    desplazado +1 ano; posiciones sin datos declarados quedan en cobertura,
    nunca como 0,00.
    """
    return DividendProjectionService().project(db, months=months)


@router.get("/tearsheet")
def portfolio_tearsheet(db: Session = Depends(get_db)) -> dict:
    """Tearsheet del portfolio: Sharpe, Sortino, drawdown, win rate y exposición.

    Lee la serie de retornos de los snapshots persistidos (ver
    ``TearsheetService``); sin portfolio o sin historial suficiente las
    métricas llegan a None en lugar de fallar.
    """
    return TearsheetService().build(db)


@router.get("/positions")
def positions(
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(Position, Company)
        .join(Company, Position.company_id == Company.id)
        .order_by(Company.ticker)
        .limit(limit)
        .offset(offset)
    ).all()
    fiscal = _fiscal_info_batch(
        db, {company.id: position.as_of for position, company in rows}
    )
    analysis_states = tracked_statuses(db, [company.ticker for _, company in rows])
    payloads = []
    for position, company in rows:
        fiscal_info = fiscal.get(company.id) or _fiscal_info(db, company.id, position.as_of)
        has_cost = position.average_cost > 0 and (position.cost_basis_base or 0) > 0
        payloads.append(
            {
                "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "analysis": analysis_states.get(company.ticker),
            "quantity": float(position.quantity),
            "average_cost": float(position.average_cost),
            "market_price": float(position.market_price),
            "market_value": float(position.market_value),
            "unrealized_pnl": float(position.unrealized_pnl) if position.average_cost > 0 else None,
            "realized_pnl": float(position.realized_pnl),
            "cost_basis": float(
                position.cost_basis_native
                if position.cost_basis_native is not None
                else position.quantity * position.average_cost
            ),
            "as_of": position.as_of.isoformat(),
            "currency": position.currency,
            "native_currency": position.currency,
            "base_currency": position.base_currency,
            "market_value_native": (
                float(position.market_value_native)
                if position.market_value_native is not None
                else float(position.market_value)
            ),
            "market_value_base": (
                float(position.market_value_base)
                if position.market_value_base is not None
                else None
            ),
            "cost_basis_native": (
                float(position.cost_basis_native)
                if position.cost_basis_native is not None
                else float(position.quantity * position.average_cost)
            ),
            "cost_basis_base": (
                float(position.cost_basis_base)
                if position.cost_basis_base is not None
                else None
            ),
            "unrealized_pnl_native": float(position.unrealized_pnl) if position.average_cost > 0 else None,
            "unrealized_pnl_base": (
                float(position.unrealized_pnl_base)
                if has_cost and position.unrealized_pnl_base is not None
                else None
            ),
            "realized_pnl_base": (
                float(position.realized_pnl_base)
                if position.realized_pnl_base is not None
                else None
            ),
            "fx_rate": float(position.fx_rate) if position.fx_rate is not None else None,
            "source": position.source,
            "first_buy_date": fiscal_info["first_buy_date"],
            "holding_days": fiscal_info["holding_days"],
            "fiscal_bucket": fiscal_info["fiscal_bucket"],
            }
        )
    return payloads


@router.get("/transactions")
def transactions(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(Transaction, Company)
        .join(Company, Transaction.company_id == Company.id)
        .where(Transaction.action.in_(["buy", "sell"]))
        .order_by(desc(Transaction.trade_date), desc(Transaction.created_at))
        .limit(limit)
        .offset(offset)
    ).all()
    return [_transaction_payload(transaction, company) for transaction, company in rows]


@router.post("/transactions", status_code=201)
def create_transaction(
    payload: PortfolioTransactionInput, db: Session = Depends(get_db)
) -> dict:
    _reject_noncanonical_cash_row(payload)
    service = PortfolioLedgerService()
    try:
        transaction = service.create_transaction(
            db,
            ticker=payload.ticker,
            action=payload.action,
            quantity=payload.quantity,
            price=payload.price,
            trade_date=payload.trade_date,
            fees=payload.fees,
            currency=payload.currency,
            notes=payload.notes,
        )
        db.commit()
        db.refresh(transaction)
        company = db.get(Company, transaction.company_id)
        assert company is not None
        if payload.action == "buy":
            try:
                enqueue_tracked_analysis(db, company.ticker)
            except Exception:
                db.rollback()  # Never roll back the already committed purchase record.
        return _transaction_payload(transaction, company)
    except PortfolioOversellError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Insufficient shares for sale"
        ) from exc
    except PortfolioMixedCurrencyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422, detail="Position cannot mix transaction currencies"
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _reject_noncanonical_cash_row(payload: PortfolioTransactionInput) -> None:
    """400 for a cash row that breaks the ledger's cash convention.

    ``PortfolioTransactionInput`` is shared by buy/sell and cash verbs, but a
    cash row stores the AMOUNT in ``price`` with ``quantity`` 0 or 1 (the
    shape ``PortfolioLedgerService`` documents and the IBKR importer writes:
    ``quantity=1, price=amount``). ``{"action": "dividend", "quantity": 100,
    "price": "0.25"}`` is therefore ambiguous - 25 units at 0,25 (6,25) or a
    25 dividend typed as a per-share amount - and the tax report, the
    attribution and XIRR used to disagree by 100x on it. Reject it instead of
    storing a figure that feeds a filed tax return.
    """
    if payload.action in {"buy", "sell"}:
        return
    if payload.quantity not in CASH_UNIT_QUANTITIES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Action '{payload.action}' is a cash movement: put the amount in "
                "'price' and use quantity 0 or 1 (quantity "
                f"{payload.quantity} is ambiguous)"
            ),
        )


@router.put("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: int,
    payload: PortfolioTransactionInput,
    db: Session = Depends(get_db),
) -> dict:
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.action not in {"buy", "sell"}:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Defence in depth: there is no DB CHECK constraint on Transaction.action,
    # and the input model also allows dividend/interest/fee/cash_misc.
    # rebuild_position replays ONLY buy/sell, so accepting a cash action here
    # would drop the leg from the replay, delete the position and answer 200 -
    # silently destroying the buy/sell the user was editing. This mirrors the
    # validation create_transaction performs for the same stored action.
    if payload.action not in {"buy", "sell"}:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only buy/sell transactions can be updated; create a separate "
                f"cash transaction for '{payload.action}'"
            ),
        )
    service = PortfolioLedgerService()
    original_company_id = transaction.company_id
    company = service.ensure_company(db, payload.ticker)
    transaction.company_id = company.id
    transaction.action = payload.action
    transaction.quantity = payload.quantity
    transaction.price = payload.price
    transaction.trade_date = payload.trade_date
    transaction.fees = payload.fees
    transaction.currency = payload.currency.upper()
    transaction.raw_payload = {"notes": payload.notes} if payload.notes else {}
    try:
        if original_company_id is not None:
            service.rebuild_position(db, original_company_id)
        if company.id != original_company_id:
            service.rebuild_position(db, company.id)
        db.commit()
        db.refresh(transaction)
        return _transaction_payload(transaction, company)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/transactions/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)) -> None:
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.action not in {"buy", "sell"}:
        raise HTTPException(status_code=404, detail="Transaction not found")
    company_id = transaction.company_id
    db.delete(transaction)
    db.flush()
    if company_id is not None:
        PortfolioLedgerService().rebuild_position(db, company_id)
    db.commit()


@router.delete("/holdings/{ticker}", status_code=204)
def delete_holding(ticker: str, db: Session = Depends(get_db)) -> None:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Holding not found")
    deleted = PortfolioLedgerService().delete_holding(db, company.id)
    if not deleted:
        db.rollback()
        raise HTTPException(status_code=404, detail="Holding not found")
    db.commit()


@router.patch("/prices")
def update_price(payload: PortfolioPriceInput, db: Session = Depends(get_db)) -> dict:
    company = db.scalar(select(Company).where(Company.ticker == payload.ticker.upper()))
    if not company:
        raise HTTPException(status_code=404, detail="Holding not found")
    try:
        position = PortfolioLedgerService().update_market_price(
            db, company_id=company.id, price=payload.price, as_of=payload.as_of
        )
        db.commit()
        return {"ticker": company.ticker, "market_price": float(position.market_price)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/refresh-market")
def refresh_portfolio_market_data(
    as_of: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    # Handler sync: FastAPI lo ejecuta en su threadpool. MarketRefreshService
    # intercala awaits de red con trabajo SQLAlchemy sync pesado (reescritura
    # de precios de TODO el universo de companias del tenant + revalorizacion);
    # como corutina del loop, esos tramos sync congelaban el event loop entero.
    # El puente compartido le da su propio loop dentro del hilo del pool.
    from app.services.async_bridge import run_from_any_context

    try:
        return run_from_any_context(MarketRefreshService().refresh(db, as_of=as_of))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cash")
def cash(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "currency": row.currency,
            "balance": float(row.balance),
            "settled_cash": float(row.settled_cash),
            "interest_rate": float(row.interest_rate),
            "source": row.source,
        }
        for row in db.scalars(select(CashBalance)).all()
    ]


def _require_ibkr_owner(db: Session):
    """Global Flex credentials must never be usable from another tenant."""
    settings = get_settings()
    owner = settings.ibkr_flex_tenant_id
    if type(owner) is not int or owner <= 0 or type(db.info.get("tenant_id")) is not int or db.info["tenant_id"] != owner:
        raise HTTPException(status_code=403, detail="La importación Flex no está habilitada para esta cuenta.")
    if not (settings.ibkr_flex_account_id or "").strip():
        raise HTTPException(status_code=503, detail="Falta configurar la cuenta IBKR esperada.")
    return settings


@router.post("/import/ibkr")
async def import_ibkr(db: Session = Depends(get_db)) -> dict:
    # _require_ibkr_owner y la importacion del XML son sqlalchemy/parseo
    # sincronos: hilo del pool. fetch_latest_xml es red async y se queda.
    settings = await run_in_threadpool(_require_ibkr_owner, db)
    client = IBKRFlexClient()
    if not client.configured():
        return {
            "status": "not_configured",
            "message": "Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID, then run the IBKR Flex connector.",
        }
    xml_text = await client.fetch_latest_xml()
    try:
        return await run_in_threadpool(
            IBKRImportService().import_flex_xml,
            db,
            xml_text,
            expected_account_id=settings.ibkr_flex_account_id,
            max_statement_age_days=5,
        )
    except IBKRPnlNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "3600"}) from exc
    except IBKRImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/ibkr/xml")
def import_ibkr_xml(payload: IBKRXmlImportRequest, db: Session = Depends(get_db)) -> dict:
    settings = _require_ibkr_owner(db)
    try:
        return IBKRImportService().import_flex_xml(
            db, payload.xml, expected_account_id=settings.ibkr_flex_account_id, max_statement_age_days=5,
        )
    except IBKRImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/ibkr/csv")
def import_ibkr_csv(payload: IBKRCsvImportRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return IBKRImportService().import_ibkr_csv(db, payload.csv)
    except IBKRImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_SCENARIO_KEYS = ("bear", "base", "bull")
_DEFAULT_HORIZON_YEARS = 5


def _published_thesis_by_company(db: Session, company_ids: list[int]) -> tuple[dict[int, ThesisVersion], set[int]]:
    """Tesis vigente = ultima PUBLICADA por empresa. Un draft no es verdad vigente."""
    rows = db.execute(
        select(ThesisVersion)
        .where(ThesisVersion.company_id.in_(company_ids))
        .order_by(ThesisVersion.company_id, ThesisVersion.version.desc())
    ).scalars().all()
    published: dict[int, ThesisVersion] = {}
    draft_only: set[int] = set()
    for row in rows:
        if row.status == "published":
            published.setdefault(row.company_id, row)
        elif row.company_id not in published:
            draft_only.add(row.company_id)
    return published, draft_only


def _publishable_model_by_company(db: Session, company_ids: list[int]) -> dict[int, FundamentalModelVersion]:
    """Modelo vigente = ultima version publicable; un no-publicable no fija horizonte."""
    rows = db.execute(
        select(FundamentalModelVersion)
        .where(FundamentalModelVersion.company_id.in_(company_ids))
        .order_by(FundamentalModelVersion.company_id, FundamentalModelVersion.version.desc())
    ).scalars().all()
    publishable: dict[int, FundamentalModelVersion] = {}
    for row in rows:
        if row.publishable:
            publishable.setdefault(row.company_id, row)
    return publishable


def _validated_probabilities(raw: dict | None) -> tuple[dict[str, float] | None, float | None, bool]:
    """Probabilidades por escenario, validadas y SIN renormalizar huecos.

    Solo entradas finitas en [0, 1]; la masa devuelta es su suma y debe ser
    <= 1. Renormalizar un hueco (p.ej. solo bull=0.5 -> bull 100%) ocultaria
    el escenario desconocido: el esperado se calcula con masa explicita.
    """
    if not raw:
        return None, None, False
    probs: dict[str, float] = {}
    invalid = False
    for key in _SCENARIO_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            invalid = True
            continue
        if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
            invalid = True
            continue
        probs[key] = parsed
    if not probs:
        return None, None, invalid
    mass = sum(probs.values())
    if mass <= 0.0 or mass > 1.0 + 1e-9:
        return None, None, True
    return probs, mass, invalid


_OFFICIAL_PRICE_SOURCES = frozenset({"ibkr_flex", "market_refresh"})


def _price_veracity(source: str | None) -> str:
    """OFICIAL solo con procedencia conocida; manual y desconocidas se rotulan."""
    if source == "manual":
        return "MANUAL/NO OFICIAL"
    if source in _OFFICIAL_PRICE_SOURCES:
        return "OFICIAL"
    return "NO VERIFICADA"


def _scenario_returns(intrinsic: float | None, price: float, horizon: int) -> tuple[float, float] | None:
    """(CAGR, retorno total) del valor intrinseco contra precio. None si no computable."""
    if intrinsic is None or not math.isfinite(intrinsic) or price <= 0 or intrinsic <= 0 or horizon <= 0:
        return None
    total_return = intrinsic / price - 1.0
    cagr = (intrinsic / price) ** (1.0 / horizon) - 1.0
    return cagr, total_return


def _intrinsic_for_comparison(
    thesis: ThesisVersion, position: Position, company: Company
) -> tuple[dict[str, float | None] | None, str]:
    """Valores intrinsecos en terminos COMPARABLES con el precio cotizado.

    Comparar exige evidencia:
    - listed_share_values (ADR con ratio aplicado por el motor): comparables.
    - value_per_share_basis == "ordinary_share" informado por el motor y sin
      adr_ratio: accion ordinaria, comparable.
    - Tesis legacy sin base informada: NUNCA se asume la base (un ADR no
      identificado quedaria mezclado): N/D.
    - Moneda de la posicion distinta de la de la compania: sin conversion
      verificada, comparar seria un mismatch silencioso: N/D.
    """
    if company.currency and position.currency and company.currency != position.currency:
        return None, "currency_mismatch"
    basis = thesis.valuation_basis if isinstance(thesis.valuation_basis, dict) else {}
    listed = basis.get("listed_share_values") if isinstance(basis, dict) else None
    if isinstance(listed, dict) and any(listed.get(key) is not None for key in _SCENARIO_KEYS):
        return (
            {key: (float(listed[key]) if listed.get(key) is not None else None) for key in _SCENARIO_KEYS},
            "listed_share",
        )
    if basis.get("adr_ratio"):
        return None, "adr_without_listed_values"
    if basis.get("value_per_share_basis") == "ordinary_share":
        return (
            {
                "bear": float(thesis.bear_value) if thesis.bear_value is not None else None,
                "base": float(thesis.base_value) if thesis.base_value is not None else None,
                "bull": float(thesis.bull_value) if thesis.bull_value is not None else None,
            },
            "ordinary_share",
        )
    return None, "legacy_basis_unverified"


@router.get("/forecast")
def portfolio_forecast(db: Session = Depends(get_db)) -> dict:
    """Prevision de rentabilidad de la cartera desde el valor intrinseco.

    Determinista (ningun numero lo escribe un LLM). Reglas de veracidad:
    - Solo tesis PUBLICADAS y modelos publicables (un draft no es vigente).
    - Solo se suman valores en moneda base (market_value_base): sin
      conversion la posicion es N/D y queda excluida, nunca suma silenciosa.
    - Probabilidades validadas en [0, 1] y SIN renormalizar huecos: el
      esperado usa masa explicita y etiquetada.
    - Cada escenario agregado lleva su cobertura; covered_only divide por la
      cobertura DE ESE escenario, nunca presenta parciales como cartera
      completa.
    - ADR: se comparan valores por accion cotizada; sin ellos, N/D.
    - El CAGR de convergencia es HIPOTESIS etiquetada (los intrinsecos son
      valores presentes descontados), no un objetivo a 5 anos.
    """
    rows = db.execute(
        select(Position, Company)
        .join(Company, Position.company_id == Company.id)
        .order_by(Company.ticker)
    ).all()
    empty = {
        "as_of": None,
        "base_currency": None,
        "portfolio": None,
        "positions": [],
        "excluded": [],
        "assumptions": ["Sin posiciones: no hay prevision que calcular."],
    }
    if not rows:
        return empty

    valued: list[tuple[Position, Company, float]] = []
    fx_excluded: list[dict] = []
    for position, company in rows:
        if position.market_value_base is None:
            fx_excluded.append(
                {
                    "ticker": company.ticker,
                    "name": company.name,
                    "weight": None,
                    "currency": position.currency,
                    "reason": "Sin valor en moneda base (conversion N/D): no se suma a la cartera.",
                }
            )
            continue
        valued.append((position, company, float(position.market_value_base)))
    base_currencies = {position.base_currency for position, _, _ in valued if position.base_currency}
    if len(base_currencies) > 1:
        out = dict(empty)
        out["excluded"] = fx_excluded
        out["assumptions"] = [
            "Monedas base mezcladas entre posiciones: agregados de cartera N/D (no se suman monedas distintas)."
        ]
        return out
    if not valued:
        out = dict(empty)
        out["excluded"] = fx_excluded
        out["assumptions"] = ["Ninguna posicion tiene valor en moneda base: agregados N/D."]
        return out

    base_currency = base_currencies.pop() if base_currencies else valued[0][0].base_currency
    total_value = sum(value for _, _, value in valued)
    if total_value <= 0:
        return empty

    company_ids = [company.id for _, company, _ in valued]
    theses, draft_only = _published_thesis_by_company(db, company_ids)
    models = _publishable_model_by_company(db, company_ids)

    positions_out: list[dict] = []
    excluded_out: list[dict] = list(fx_excluded)
    any_invalid_probs = False
    for position, company, value in valued:
        weight = value / total_value
        thesis = theses.get(company.id)
        model = models.get(company.id)
        base_info = {
            "ticker": company.ticker,
            "name": company.name,
            "weight": weight,
            "currency": position.currency,
        }
        if thesis is None:
            suffix = " (hay borrador sin publicar)" if company.id in draft_only else ""
            excluded_out.append({**base_info, "reason": f"Sin tesis publicada vigente{suffix}: excluida de la prevision."})
            continue
        intrinsic, basis_label = _intrinsic_for_comparison(thesis, position, company)
        if intrinsic is None:
            reason = {
                "adr_without_listed_values": "ADR sin valores por accion cotizada: comparacion con el precio no verificada (N/D).",
                "currency_mismatch": "Moneda de la posicion distinta de la moneda de cotizacion de la compania: comparacion sin conversion verificada (N/D).",
            }.get(basis_label, "Base de valoración no verificada (tesis sin value_per_share_basis del motor): comparación con el precio N/D, nunca asumida.")
            excluded_out.append({**base_info, "reason": reason})
            continue
        if model is not None:
            basis_dict = thesis.valuation_basis if isinstance(thesis.valuation_basis, dict) else {}
            if basis_dict.get("model_input_fingerprint") != model.input_fingerprint:
                # Modelo no ligado a ESTA tesis publicada: su horizonte y sus
                # probabilidades podrian ser de otra epoca de inputs. N/D.
                model = None
        price = float(position.market_price)
        horizon = model.horizon_years if model is not None else _DEFAULT_HORIZON_YEARS
        cagrs: dict[str, float] = {}
        total_returns: dict[str, float] = {}
        for key in _SCENARIO_KEYS:
            result = _scenario_returns(intrinsic[key], price, horizon)
            if result is not None:
                cagrs[key], total_returns[key] = result
        if not cagrs:
            excluded_out.append({**base_info, "reason": "Tesis sin valores intrinsecos computables."})
            continue
        raw_probs = thesis.scenario_probabilities or (
            model.scenario_probabilities if model is not None else None
        )
        probabilities, mass, invalid = _validated_probabilities(raw_probs)
        any_invalid_probs = any_invalid_probs or invalid
        expected_cagr: float | None = None
        used_mass: float | None = None
        partial_expected: float | None = None
        if probabilities is not None and mass is not None:
            terms = [
                (probabilities[key], cagrs[key])
                for key in _SCENARIO_KEYS
                if key in probabilities and key in cagrs
            ]
            if terms:
                # SIN renormalizar: el hueco de probabilidad queda visible
                # en used_mass, nunca repartido entre los demas escenarios.
                # El esperado solo existe con masa completa (==1): con masa
                # parcial el resultado se expone como partial_expected_cagr y
                # el esperado queda N/D (el resto nunca es cero implicito).
                partial_expected = sum(prob * cagr for prob, cagr in terms)
                used_mass = sum(prob for prob, _ in terms)
                # Esperado completo solo con masa 1 SIN entradas invalidas
                # descartadas y con valor en todo escenario con masa>0
                # (used_mass solo suma escenarios con CAGR computable).
                if abs(used_mass - 1.0) <= 1e-9 and not invalid:
                    expected_cagr = partial_expected
        positions_out.append(
            {
                **base_info,
                "weight_scope": "valued_subset" if fx_excluded else "total_portfolio",
                "price": price,
                "price_as_of": position.as_of.isoformat(),
                "price_source": position.source,
                "price_veracity": _price_veracity(position.source),
                "intrinsic": intrinsic,
                "comparison_basis": basis_label,
                "probabilities": probabilities,
                "probability_mass": used_mass,
                "horizon_years": horizon,
                "thesis_version": thesis.version,
                "thesis_status": thesis.status,
                "model_version": model.version if model is not None else None,
                "cagr": cagrs,
                "total_return": total_returns,
                "expected_cagr": expected_cagr,
                "partial_expected_cagr": partial_expected,
                "contribution_expected": (
                    weight * expected_cagr if expected_cagr is not None else None
                ),
            }
        )

    covered_weight = sum(item["weight"] for item in positions_out)
    if fx_excluded:
        # El denominador real de la cartera es desconocido (hay posiciones sin
        # conversion a moneda base): los agregados de cartera total son N/D,
        # nunca "100% del subset valorado" vendido como cartera completa.
        covered_weight = None
    # Agregados por escenario: CONTRIBUCIONES ponderadas del subset cubierto
    # (suma peso x CAGR), NUNCA "rentabilidad de cartera". horizon_scope
    # etiqueta mezcla de horizontes (proxy anual, no CAGR buy-and-hold).
    portfolio_scenarios: dict[str, dict] | None = {}
    covered_scenarios: dict[str, dict] = {}
    for key in _SCENARIO_KEYS:
        with_scenario = [item for item in positions_out if key in item["cagr"]]
        if not with_scenario:
            continue
        coverage = sum(item["weight"] for item in with_scenario)
        contrib_cagr = sum(item["weight"] * item["cagr"][key] for item in with_scenario)
        contrib_total = sum(
            item["weight"] * item["total_return"][key] for item in with_scenario
        )
        scenario_horizons = {item["horizon_years"] for item in with_scenario}
        horizon_scope = "uniform" if len(scenario_horizons) == 1 else "mixed"
        portfolio_scenarios[key] = {
            "contribution_cagr": contrib_cagr,
            "contribution_total_return": contrib_total,
            "coverage": coverage,
            "horizon_scope": horizon_scope,
        }
        if coverage > 0:
            covered_scenarios[key] = {
                "cagr": contrib_cagr / coverage,
                "total_return": contrib_total / coverage,
                "coverage": coverage,
                "horizon_scope": horizon_scope,
            }
    if fx_excluded:
        # Denominador de cartera desconocido: agregados de cartera N/D (el
        # subset explícito sigue disponible en covered_only).
        portfolio_scenarios = None
    with_expected = [item for item in positions_out if item["expected_cagr"] is not None]
    expected_coverage = (
        (sum(item["weight"] for item in with_expected) if with_expected else None)
        if not fx_excluded
        else None
    )
    # Esperado de cartera TOTAL: solo si cubre el 100% de la cartera valorada
    # y no hay FX ausente. Con cobertura parcial, sumar parciales y llamarlo
    # esperado de cartera seria una etiqueta falsa: N/D.
    expected_cagr = (
        sum(item["contribution_expected"] for item in with_expected)
        if (
            with_expected
            and not fx_excluded
            and expected_coverage is not None
            and abs(expected_coverage - 1.0) <= 1e-9
        )
        else None
    )
    covered_expected = (
        sum(item["contribution_expected"] for item in with_expected) / expected_coverage
        if with_expected and expected_coverage
        else None
    )

    dates = sorted({item["price_as_of"] for item in positions_out} | {p.as_of.isoformat() for p, _, _ in valued})
    manual = [item["ticker"] for item in positions_out if item["price_veracity"] == "MANUAL/NO OFICIAL"]
    unverified = [item["ticker"] for item in positions_out if item["price_veracity"] == "NO VERIFICADA"]
    assumptions = [
        "Precios: última sincronización de cada posición, con su fuente y fecha en cada fila. OFICIAL solo con procedencia conocida (IBKR Flex o refresco de mercado)."
        + (f" MANUAL/NO OFICIAL en: {', '.join(manual)}." if manual else "")
        + (f" NO VERIFICADA en: {', '.join(unverified)}." if unverified else ""),
        "Valores intrínsecos y probabilidades: solo tesis publicadas y modelos publicables; los borradores nunca cuentan.",
        "HIPÓTESIS etiquetada (INFERENCIA, no objetivo del modelo): los intrínsecos son valores presentes descontados; el CAGR supone convergencia del precio al intrínseco en el horizonte del modelo vigente (5 años sin modelo).",
        "Escenarios: son contribuciones ponderadas del subset valorado (peso x CAGR), nunca la rentabilidad total de la cartera. La cobertura es la fracción de cartera usada. Si los horizontes de convergencia se mezclan, es un proxy anual ponderado, no un CAGR de comprar y mantener. Nunca se da un esperado de cartera completa con huecos.",
        "El esperado del CAGR es la media de los CAGR por escenario ponderada por probabilidad (no es el CAGR del valor esperado: no coinciden). Solo se da con probabilidad total del 100 % y sin entradas invalidas descartadas; con menos, solo se muestra el parcial y la probabilidad usada."
        + (" Probabilidades invalidas (fuera de [0, 1] o no finitas) descartadas en alguna posicion." if any_invalid_probs else ""),
        (
            f"Cobertura de cartera N/D: {len(fx_excluded)} posicion(es) sin conversion a moneda base; "
            "pesos y agregados cubiertos usan SOLO el subset valorado, nunca la cartera completa."
            if fx_excluded
            else f"Cobertura con tesis publicada: {covered_weight:.1%} de la cartera; el resto se lista en excluded."
        ),
        "El esperado de la cartera total solo se da cuando cubre el 100 % de la cartera valorada y no hay posiciones sin conversión; con cobertura parcial es N/D y se muestran las contribuciones por posición.",
    ]
    return {
        "as_of": dates[-1],
        "base_currency": base_currency,
        "portfolio": {
            "total_value_base": total_value,
            "position_count": len(valued),
            "covered_count": len(positions_out),
            "excluded_count": len(excluded_out),
            "covered_weight": covered_weight,
            "scenarios": portfolio_scenarios,
            "expected_cagr": expected_cagr,
            "expected_coverage": expected_coverage,
            "covered_only": {
                "scenarios": covered_scenarios,
                "expected_cagr": covered_expected,
            },
        },
        "positions": positions_out,
        "excluded": excluded_out,
        "assumptions": assumptions,
    }
