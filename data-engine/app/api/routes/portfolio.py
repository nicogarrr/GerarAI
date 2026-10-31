import logging
import math
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from app.core.cache import invalidate_market_data_cache, invalidate_portfolio_cache
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import safe_detail
from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.core.ui_errors import ui_error
from app.models import (
    CashBalance,
    Company,
    FundamentalModelVersion,
    FXRate,
    MarketPrice,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    ThesisVersion,
    Transaction,
)
from app.schemas.api import (
    CashBalanceOut,
    FXRateOut,
    PortfolioConfigurationOut,
    PortfolioConfigurationUpdateOut,
    PortfolioDataQualityOut,
    PortfolioDividendProjectionOut,
    PortfolioDividendSyncOut,
    PortfolioDividendYieldsOut,
    PortfolioForecastOut,
    PortfolioIbkrCsvImportOut,
    PortfolioIbkrXmlImportOut,
    PortfolioImportCommitOut,
    PortfolioIntelligenceOut,
    PortfolioPositionItemOut,
    PortfolioPriceUpdateOut,
    PortfolioRefreshMarketOut,
    PortfolioSnapshotCaptureOut,
    PortfolioSnapshotOut,
    PortfolioSummaryOut,
    PortfolioTearsheetOut,
    PortfolioTransactionBatchOut,
    PortfolioTransactionCreateOut,
    PortfolioTransactionOut,
    PortfolioTransactionPageOut,
)
from app.schemas.pagination import PageInfo, PaginatedResponse
from app.services.async_bridge import run_from_any_context
from app.services.audit_service import record_audit_event
from app.services.company_resolver import resolve_company
from app.services.connectors.ibkr import IBKRFlexClient
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.dividend_projection_service import DividendProjectionService
from app.services.fx_attribution import split_unrealized_pnl
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService, IBKRPnlNotReadyError
from app.services.market_refresh_service import MarketRefreshService
from app.services.portfolio_fx_service import TAX_CURRENCY, PortfolioFXService
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.portfolio_ledger_service import (
    PortfolioLedgerService,
    PortfolioMixedCurrencyError,
    PortfolioOversellError,
    ValuationHeldError,
)
from app.services.portfolio_snapshot_service import PortfolioSnapshotService
from app.services.tax_report_service import (
    CASH_UNIT_QUANTITIES,
    ZERO_COST_REVIEW_LABEL,
    is_zero_cost_buy,
)
from app.services.tearsheet_service import TearsheetService
from app.services.thesis_pdf_service import export_portfolio_pdf_report
from app.services.tracked_analysis import enqueue_tracked_analysis, tracked_statuses
from app.services.transaction_import_service import (
    MAX_IMPORT_BYTES,
    TransactionImportCommitRequest,
    TransactionImportPreviewResponse,
    TransactionImportService,
)
from app.valuation.currency import canonical_currency_code

logger = logging.getLogger(__name__)

router = APIRouter()


# Un extracto Flex anual completo cabe con mucho en 15 MB; sin tope, un body
# gigante se parsea entero en memoria (mismo vector que /import/file).
MAX_IBKR_IMPORT_BYTES = 15 * 1024 * 1024


class IBKRXmlImportRequest(BaseModel):
    xml: str = Field(min_length=20, max_length=MAX_IBKR_IMPORT_BYTES)


class IBKRCsvImportRequest(BaseModel):
    csv: str = Field(min_length=10, max_length=MAX_IBKR_IMPORT_BYTES)


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
            *tenant_filters(db, Transaction),
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
                *tenant_filters(db, Transaction),
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


def _holding_as_of(db: Session, rows) -> dict[int, date]:
    """Fecha hasta la que se cuenta la antigüedad de cada posición.

    Abierta (cantidad > 0): hasta HOY (Europe/Madrid), no hasta el último
    precio/snapshot: sin cotización reciente ``as_of`` quedaba en la fecha de
    compra y una posición de 2 años salía «Corto plazo · 0d». Cerrada
    (cantidad <= 0): hasta la última venta (fecha de cierre), o ``as_of`` si
    no hay ventas registradas.
    """
    today = local_today()
    result: dict[int, date] = {}
    closed: dict[int, date] = {}
    for position, company in rows:
        if position.quantity is not None and position.quantity > 0:
            result[company.id] = today
        else:
            closed[company.id] = position.as_of
    if closed:
        last_sells = dict(
            db.execute(
                select(Transaction.company_id, func.max(Transaction.trade_date))
                .where(
                    Transaction.company_id.in_(set(closed)),
                    Transaction.action == "sell",
                    *tenant_filters(db, Transaction),
                )
                .group_by(Transaction.company_id)
            ).all()
        )
        for company_id, as_of in closed.items():
            result[company_id] = last_sells.get(company_id) or as_of
    return result


MAX_NUMERIC_20_6 = Decimal("99999999999999.999999")
MAX_NUMERIC_20_2 = Decimal("999999999999999999.99")
MAX_NUMERIC_20_4 = Decimal("9999999999999999.9999")
MIN_NUMERIC_20_4 = Decimal("0.0001")
MIN_NUMERIC_20_6 = Decimal("0.000001")


class PortfolioTransactionInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")
    action: Literal["buy", "sell", "dividend", "interest", "fee", "cash_misc"]
    # Topes = lo que cabe en Transaction (Numeric(20, 6) / Numeric(20, 4) en fees).
    # Sin ellos, "1e400" pasaba la validación, se guardaba como precio nulo y
    # cada transacción posterior del ticker daba 500 al recalcular la posición.
    quantity: Decimal = Field(ge=0, le=MAX_NUMERIC_20_6)
    price: Decimal = Field(ge=0, le=MAX_NUMERIC_20_6)
    trade_date: date
    fees: Decimal = Field(default=Decimal("0"), ge=0, le=MAX_NUMERIC_20_4)
    currency: str = Field(default="USD", min_length=3, max_length=10)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("quantity", "price")
    @classmethod
    def _not_rounded_to_zero(cls, value: Decimal) -> Decimal:
        # La columna guarda 6 decimales: 0,0000004 pasaba (> 0) y quedaba en
        # el libro como 0, una compra de cero acciones o a precio cero.
        if value > 0 and value.quantize(MIN_NUMERIC_20_6, rounding=ROUND_HALF_EVEN) == 0:
            raise ValueError("must be at least 0.000001 (6 decimal places)")
        return value

    @field_validator("fees")
    @classmethod
    def _fees_fit_four_decimals(cls, value: Decimal) -> Decimal:
        # La columna guarda 4 decimales (comisiones IBKR tipo 0,355): mas
        # decimales se redondearian en silencio al guardar.
        if value != value.quantize(MIN_NUMERIC_20_4, rounding=ROUND_HALF_EVEN):
            raise ValueError("fees allow at most 4 decimal places")
        return value

    @field_validator("trade_date")
    @classmethod
    def _no_future_trade_date(cls, value: date) -> date:
        if value > local_today():
            raise ValueError("trade_date cannot be in the future")
        return value


def _not_in_the_future(value: date | None) -> date | None:
    # Un precio o un tipo de cambio fechado en el futuro (2062 por 2026) se
    # guardaba sin aviso: la fila FX quedaba invisible hasta esa fecha y luego
    # ganaba a las reales; el precio dejaba la posicion con fecha futura.
    if value is not None and value > local_today():
        raise ValueError("date cannot be in the future")
    return value


class PortfolioPriceInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    price: Decimal = Field(gt=0)
    as_of: date | None = None

    _as_of_not_future = field_validator("as_of")(_not_in_the_future)


class CreatePortfolioInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_currency: str = Field(default="EUR", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")


class PortfolioConfigurationInput(BaseModel):
    base_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")


class FXRateInput(BaseModel):
    base_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    quote_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    rate: Decimal = Field(gt=0)
    rate_date: date
    source: str = Field(default="manual", min_length=1, max_length=80)

    _rate_date_not_future = field_validator("rate_date")(_not_in_the_future)


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
        # Compra a precio 0 aceptada pero marcada para revisión (regalo / spin-off).
        "review_flag": ZERO_COST_REVIEW_LABEL if is_zero_cost_buy(transaction) else None,
        "created_at": transaction.created_at.isoformat(),
        "updated_at": transaction.updated_at.isoformat(),
    }


@router.get("", response_model=None)
@router.get("/", response_model=None)
def list_portfolios(db: Session = Depends(get_db)) -> list[dict]:
    tenant_id = db.info.get("tenant_id")
    query = select(Portfolio)
    if tenant_id is not None:
        query = query.where(Portfolio.tenant_id == tenant_id)
    portfolios = list(db.scalars(query.order_by(Portfolio.id)).all())
    return [
        {
            "id": p.id,
            "name": p.name,
            "base_currency": p.base_currency,
            "is_default": p.is_default,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in portfolios
    ]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
@router.post("/", status_code=status.HTTP_201_CREATED, response_model=None)
def create_portfolio(
    body: CreatePortfolioInput,
    db: Session = Depends(get_db),
) -> dict:
    tenant_id = db.info.get("tenant_id")
    clean_name = body.name.strip()
    clean_currency = body.base_currency.strip().upper()

    existing_query = select(Portfolio).where(Portfolio.name == clean_name)
    if tenant_id is not None:
        existing_query = existing_query.where(Portfolio.tenant_id == tenant_id)

    existing = db.scalars(existing_query).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cartera con este nombre para el usuario.",
        )

    portfolio = Portfolio(
        name=clean_name,
        base_currency=clean_currency,
        is_default=False,
    )
    if tenant_id is not None:
        portfolio.tenant_id = tenant_id

    db.add(portfolio)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cartera con este nombre para el usuario.",
        ) from exc

    db.refresh(portfolio)
    record_audit_event(
        db,
        action="portfolio_created",
        resource_type="portfolio",
        resource_id=str(portfolio.id),
        after_state={"name": portfolio.name, "base_currency": portfolio.base_currency},
    )
    db.commit()
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "base_currency": portfolio.base_currency,
        "is_default": portfolio.is_default,
        "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
    }


@router.get("/{portfolio_id}/pdf")
def portfolio_pdf_export(portfolio_id: int, db: Session = Depends(get_db)) -> Response:
    """Exporta el informe consolidado de la cartera y sus posiciones a formato PDF."""
    try:
        content, filename = export_portfolio_pdf_report(db, portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary", response_model=PortfolioSummaryOut)
def portfolio_summary(db: Session = Depends(get_db)) -> dict:
    # Cache Redis de 10 min por tenant (categoria portfolio_valuation): se
    # invalida por eventos ORM al escribir posiciones/transacciones/caja/FX y
    # de forma explicita tras PATCH /prices y POST /refresh-market.
    from app.services.cached_portfolio_valuation import risk_dashboard

    risk = risk_dashboard(db)
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
        "valuation_hold": risk.get("valuation_hold", []),
        "provenance": risk.get("provenance"),
    }


@router.get("/intelligence", response_model=PortfolioIntelligenceOut, response_model_exclude_unset=True)
def portfolio_intelligence(
    years: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    return PortfolioIntelligenceService().build(db, years=years)


@router.get("/data-quality", response_model=PortfolioDataQualityOut, response_model_exclude_unset=True)
def portfolio_data_quality(db: Session = Depends(get_db)) -> dict:
    from app.services.portfolio_quality_service import portfolio_quality
    return portfolio_quality(db)


def _snapshot_payload(snapshot: PortfolioDailySnapshot) -> dict:
    return {
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


@router.get("/snapshots", response_model=PaginatedResponse[PortfolioSnapshotOut])
def portfolio_snapshots(
    start: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
    db: Session = Depends(get_db),
) -> dict:
    # Contrato dual aditivo como en /positions (ver list_fx_rates).
    service = PortfolioSnapshotService()
    total = service.count_history(db, start=start)
    if limit is not None:
        exact_offset = offset or 0
        items = [
            _snapshot_payload(snapshot)
            for snapshot in service.history(db, start=start, page_size=limit, offset=exact_offset)
        ]
        # page_info de la ventana real (has_next/has_prev del offset exacto,
        # no de la division entera), como en /positions.
        page_info = PageInfo(
            page=exact_offset // limit + 1,
            page_size=limit,
            total_items=total,
            total_pages=(total + limit - 1) // limit if limit > 0 else 0,
            has_next=exact_offset + len(items) < total,
            has_prev=exact_offset > 0,
        )
        return PaginatedResponse(items=items, page_info=page_info).model_dump()
    if offset:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El parámetro offset solo tiene efecto junto a limit.",
        )
    items = [
        _snapshot_payload(snapshot)
        for snapshot in service.history(db, start=start, page=page, page_size=page_size)
    ]
    return PaginatedResponse.create(items=items, total=total, page=page, page_size=page_size).model_dump()


@router.post("/snapshots/capture", response_model=PortfolioSnapshotCaptureOut)
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


def _pnl_effects(position: Position, *, held: bool, has_cost: bool) -> dict:
    """G/P latente en divisa base partida en efecto precio y efecto divisa."""
    if held or not has_cost or position.average_cost <= 0:
        return {"pnl_price_effect_base": None, "pnl_fx_effect_base": None}
    price_effect, fx_effect = split_unrealized_pnl(
        unrealized_native=position.unrealized_pnl,
        unrealized_base=position.unrealized_pnl_base,
        fx_rate_now=position.fx_rate,
    )
    return {"pnl_price_effect_base": price_effect, "pnl_fx_effect_base": fx_effect}


_QUOTE_MISSING_PNL_KEYS = (
    "unrealized_pnl",
    "unrealized_pnl_native",
    "unrealized_pnl_base",
    "pnl_price_effect_base",
    "pnl_fx_effect_base",
)


def _trade_price_fallbacks(db: Session, positions: list[Position]) -> set[int]:
    """Posiciones del ledger cuyo «precio de mercado» es el de su última operación.

    Sin cotización guardada, rebuild_position valora con el precio de la última
    compra/venta: con una sola compra la plusvalía sale exactamente 0, un dato
    que parece real y no lo es (auditoría A3). Señal sin columna nueva: fuente
    ledger, precio igual al de la última operación y ninguna cotización
    (MarketPrice) desde esa fecha. Un precio manual idéntico al de compra cae
    aquí también; rotularlo «sin cotización real» es inocuo.
    """
    candidates = {
        position.company_id: position
        for position in positions
        if position.source == "postgres_ledger" and not position.valuation_hold_reason
    }
    if not candidates:
        return set()
    last_trade: dict[int, Transaction] = {}
    for transaction in db.scalars(
        select(Transaction)
        .where(
            *tenant_filters(db, Transaction),
            Transaction.company_id.in_(candidates),
            Transaction.action.in_(["buy", "sell"]),
        )
        .order_by(Transaction.trade_date, Transaction.created_at, Transaction.id)
    ):
        last_trade[transaction.company_id] = transaction
    fallbacks: set[int] = set()
    for company_id, transaction in last_trade.items():
        position = candidates[company_id]
        if position.market_price != transaction.price:
            continue
        quoted = db.scalar(
            select(MarketPrice.id)
            .where(MarketPrice.company_id == company_id, MarketPrice.date >= transaction.trade_date)
            .limit(1)
        )
        if quoted is None:
            fallbacks.add(company_id)
    return fallbacks


def _fx_source(db: Session, base_currency: str) -> dict:
    """Etiqueta de la fuente FX: de donde salen los tipos y de que fecha."""
    row = db.execute(
        select(FXRate.source, FXRate.rate_date)
        .where(*tenant_filters(db, FXRate))
        .order_by(desc(FXRate.rate_date), desc(FXRate.id))
        .limit(1)
    ).first()
    return {
        "source": row.source if row else None,
        "latest_rate_date": row.rate_date.isoformat() if row else None,
        "base_currency": base_currency,
    }


@router.get("/configuration", response_model=PortfolioConfigurationOut)
def portfolio_configuration(db: Session = Depends(get_db)) -> dict:
    portfolio = PortfolioFXService().portfolio(db)
    base_currency = portfolio.base_currency if portfolio else "EUR"
    return {
        "id": portfolio.id if portfolio else None,
        "name": portfolio.name if portfolio else "Main",
        "base_currency": base_currency,
        "is_default": portfolio.is_default if portfolio else True,
        # IRPF y Modelo 720 se declaran en euros al tipo BCE, sea cual sea la
        # divisa base de la cartera.
        "tax_currency": TAX_CURRENCY,
        "fx_source": _fx_source(db, base_currency),
    }


@router.put("/configuration", response_model=PortfolioConfigurationUpdateOut)
def update_portfolio_configuration(
    payload: PortfolioConfigurationInput,
    db: Session = Depends(get_db),
) -> dict:
    service = PortfolioFXService()
    ledger = PortfolioLedgerService()
    try:
        portfolio = service.set_base_currency(db, payload.base_currency)
        company_ids = list(
            db.scalars(
                select(Position.company_id).where(*tenant_filters(db, Position))
            ).all()
        )
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


@router.get("/fx-rates", response_model=PaginatedResponse[FXRateOut])
def list_fx_rates(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
    db: Session = Depends(get_db),
) -> dict:
    # Contrato dual aditivo como en /positions: limit/offset (paginateAll del
    # indice de /research) tiene precedencia; antes se descartaba en silencio.
    use_window = limit is not None
    if use_window:
        page_size = limit
        offset = offset or 0
    elif offset:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El parámetro offset solo tiene efecto junto a limit.",
        )
    else:
        offset = (page - 1) * page_size
    total = db.scalar(
        select(func.count()).select_from(FXRate).where(*tenant_filters(db, FXRate))
    ) or 0
    items = [
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
            .limit(page_size)
            .offset(offset)
        ).all()
    ]
    if use_window:
        # page_info de la ventana real: con offset>0 la pagina derivada
        # mentia (siempre page=1) y has_next salia de la division entera.
        page_info = PageInfo(
            page=offset // limit + 1,
            page_size=limit,
            total_items=total,
            total_pages=(total + limit - 1) // limit if limit > 0 else 0,
            has_next=offset + len(items) < total,
            has_prev=offset > 0,
        )
        return PaginatedResponse(items=items, page_info=page_info).model_dump()
    return PaginatedResponse.create(items=items, total=total, page=page, page_size=page_size).model_dump()


@router.post("/fx-rates", status_code=201, response_model=FXRateOut)
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
        company_ids = list(
            db.scalars(
                select(Position.company_id).where(*tenant_filters(db, Position))
            ).all()
        )
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


@router.post("/dividends/sync", response_model=PortfolioDividendSyncOut, response_model_exclude_unset=True)
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


@router.get("/dividends", response_model=PortfolioDividendYieldsOut)
def portfolio_dividends(db: Session = Depends(get_db)) -> dict:
    """Trailing-12-month declared dividend yield per position and portfolio.

    Coverage is explicit: positions without ingested dividend records show
    null yields instead of zeros.
    """
    return DividendIngestionService().portfolio_yields(db)


@router.get("/dividends/projection", response_model=PortfolioDividendProjectionOut, response_model_exclude_unset=True)
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


@router.get("/tearsheet", response_model=PortfolioTearsheetOut, response_model_exclude_unset=True)
def portfolio_tearsheet(db: Session = Depends(get_db)) -> dict:
    """Tearsheet del portfolio: Sharpe, Sortino, drawdown, win rate y exposición.

    Lee la serie de retornos de los snapshots persistidos (ver
    ``TearsheetService``); sin portfolio o sin historial suficiente las
    métricas llegan a None en lugar de fallar.
    """
    return TearsheetService().build(db)


@router.get("/positions", response_model=PaginatedResponse[PortfolioPositionItemOut], response_model_exclude_unset=True)
def positions(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
    db: Session = Depends(get_db),
) -> dict:
    # Contrato dual (aditivo): page/page_size es el estilo documentado y
    # limit/offset el que usa el indice de /research via paginateAll
    # (?limit=2000&offset=N). Antes solo existian page/page_size y FastAPI
    # descartaba limit/offset en silencio: cualquier tenant con mas de 20
    # posiciones recibia solo la primera pagina rotulada como completa.
    # limit/offset tiene precedencia cuando se pasa `limit`.
    if limit is not None:
        page_size = limit
        offset_val = offset or 0
        page = offset_val // limit + 1
    elif offset:
        # offset sin limit no significa nada en el contrato page/page_size:
        # mejor un 422 explicito que ignorarlo en silencio (y un entero
        # enorme no llega nunca a la BD; tests/test_huge_integer_params.py).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El parámetro offset solo tiene efecto junto a limit.",
        )
    else:
        offset_val = (page - 1) * page_size
    total = db.scalar(
        select(func.count())
        .select_from(Position)
        .join(Company, Position.company_id == Company.id)
        .where(*tenant_filters(db, Position))
    ) or 0
    rows = db.execute(
        select(Position, Company)
        .join(Company, Position.company_id == Company.id)
        .order_by(Company.ticker)
        .limit(page_size)
        .offset(offset_val)
    ).all()
    fiscal = _fiscal_info_batch(db, _holding_as_of(db, rows))
    analysis_states = tracked_statuses(db, [company.ticker for _, company in rows])
    from app.services.ibkr_cost_reconciliation import mask_cost_under_review, reconcile_ibkr_costs

    cost_checks = reconcile_ibkr_costs(db, [position for position, _ in rows])
    trade_price_fallbacks = _trade_price_fallbacks(db, [position for position, _ in rows])
    payloads = []
    for position, company in rows:
        fiscal_info = fiscal.get(company.id) or _fiscal_info(db, company.id, local_today())
        # nosemgrep: gerarai-money-none-to-zero -- comparacion booleana: None no es coste conocido, igual que 0
        has_cost = position.average_cost > 0 and (position.cost_basis_base or 0) > 0
        held = bool(position.valuation_hold_reason)
        payloads.append(
            {
                "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "analysis": analysis_states.get(company.ticker),
            "quantity": float(position.quantity),
            "average_cost": float(position.average_cost),
            # Valoracion en suspenso: null con motivo, nunca un 0 presentado como cotizacion.
            "market_price": None if held else float(position.market_price),
            "market_value": None if held else float(position.market_value),
            "valuation_hold": (
                {
                    "reason": position.valuation_hold_reason,
                    "effective_date": position.valuation_hold_effective_date.isoformat()
                    if position.valuation_hold_effective_date
                    else None,
                    "since": position.valuation_hold_since.isoformat()
                    if position.valuation_hold_since
                    else None,
                }
                if held
                else None
            ),
            "unrealized_pnl": float(position.unrealized_pnl) if position.average_cost > 0 and not held else None,
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
                None
                if held
                else float(position.market_value_native)
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
            "unrealized_pnl_native": float(position.unrealized_pnl) if position.average_cost > 0 and not held else None,
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
            **_pnl_effects(position, held=held, has_cost=has_cost),
            "source": position.source,
            "first_buy_date": fiscal_info["first_buy_date"],
            "holding_days": fiscal_info["holding_days"],
            "fiscal_bucket": fiscal_info["fiscal_bucket"],
            # A3: el precio es el de la última operación, no una cotización. El
            # valor se conserva (es la mejor estimación), pero la plusvalía es
            # desconocida: null, nunca un 0 que parece medido.
            "quote_missing": company.id in trade_price_fallbacks,
            }
        )
        if company.id in trade_price_fallbacks:
            payloads[-1].update(dict.fromkeys(_QUOTE_MISSING_PNL_KEYS))
    items = [mask_cost_under_review(payload, cost_checks.get(position.id))
            for payload, (position, _) in zip(payloads, rows, strict=True)]
    if limit is not None:
        # Con limit/offset la ventana no tiene por que alinearse con paginas
        # enteras: has_next/has_prev se derivan de la ventana real, no de la
        # division entera (offset 19 con limit 10 y total 25 -> 6 items y
        # has_next False; la pagina derivada daria True).
        page_info = PageInfo(
            page=offset_val // limit + 1,
            page_size=limit,
            total_items=total,
            total_pages=(total + limit - 1) // limit if limit > 0 else 0,
            has_next=offset_val + len(items) < total,
            has_prev=offset_val > 0,
        )
        return PaginatedResponse(items=items, page_info=page_info).model_dump()
    return PaginatedResponse.create(items=items, total=total, page=page, page_size=page_size).model_dump()


def _trade_filters(ticker: str | None, action: str | None) -> list:
    """Filtros de Movimientos: ticker exacto (sin distinguir mayúsculas) y tipo."""
    conditions = [Transaction.action.in_([action] if action else ["buy", "sell"])]
    if ticker and ticker.strip():
        conditions.append(func.upper(Company.ticker) == ticker.strip().upper())
    return conditions


def _list_trades(db: Session, limit: int, offset: int, ticker: str | None = None, action: str | None = None) -> list[dict]:
    rows = db.scalars(
        select(Transaction)
        .join(Company, Transaction.company_id == Company.id)
        .where(*_trade_filters(ticker, action), *tenant_filters(db, Transaction))
        .options(selectinload(Transaction.company))
        .order_by(desc(Transaction.trade_date), desc(Transaction.created_at), desc(Transaction.id))
        .limit(limit)
        .offset(offset)
    ).all()
    return [_transaction_payload(transaction, transaction.company) for transaction in rows]


@router.get("/transactions", response_model=PaginatedResponse[PortfolioTransactionOut])
def transactions(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
    ticker: Annotated[str | None, Query(max_length=32)] = None,
    action: Annotated[Literal["buy", "sell"] | None, Query()] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
    db: Session = Depends(get_db),
) -> dict:
    if offset:
        # /transactions usa page/page_size (el listado limit/offset vive en
        # /transactions/page): offset suelto se rechaza en vez de ignorarlo.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El parámetro offset no aplica aquí; usa /transactions/page o page/page_size.",
        )
    offset = (page - 1) * page_size
    total = db.scalar(
        select(func.count()).select_from(Transaction)
        .join(Company, Transaction.company_id == Company.id)
        .where(*_trade_filters(ticker, action), *tenant_filters(db, Transaction))
    ) or 0
    items = _list_trades(db, page_size, offset, ticker, action)
    return PaginatedResponse.create(items=items, total=total, page=page, page_size=page_size).model_dump()


@router.get("/transactions/page", response_model=PortfolioTransactionPageOut)
def transactions_page(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    ticker: Annotated[str | None, Query(max_length=32)] = None,
    action: Annotated[Literal["buy", "sell"] | None, Query()] = None,
    db: Session = Depends(get_db),
) -> dict:
    total = db.scalar(
        select(func.count()).select_from(Transaction)
        .join(Company, Transaction.company_id == Company.id)
        .where(*_trade_filters(ticker, action), *tenant_filters(db, Transaction))
    ) or 0
    return {
        "items": _list_trades(db, limit, offset, ticker, action),
        "total": total,
    }


@router.post("/add", status_code=201, response_model=PortfolioTransactionCreateOut)
def add_portfolio_transaction(
    payload: PortfolioTransactionInput, db: Session = Depends(get_db)
) -> dict:
    """Añade una transacción/posición a la cartera (alias para contratos de API)."""
    return create_transaction(payload, db)


@router.post("/transactions", status_code=201, response_model=PortfolioTransactionCreateOut)
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
        if payload.action in {"buy", "sell"}:
            from app.services.journal_trade_link import auto_link_journal_trades_best_effort

            auto_link_journal_trades_best_effort(db, {company.id})
        if payload.action == "buy":
            try:
                enqueue_tracked_analysis(db, company.ticker)
            except Exception:
                db.rollback()  # Never roll back the already committed purchase record.
            try:
                from app.services.market_close_sync import enqueue_price_backfills

                # Una compra puede estrenar la compania en market_prices, que
                # solo acumula hacia adelante: sin backfill no tiene pasado.
                enqueue_price_backfills(
                    db,
                    [company.id],
                    tenant_id=(
                        db.info["tenant_id"]
                        if type(db.info.get("tenant_id")) is int
                        else None
                    ),
                    user_id=str(db.info["user_id"]) if db.info.get("user_id") else None,
                )
            except Exception:  # noqa: BLE001 - la cola nunca rompe la compra
                db.rollback()
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



class PortfolioTransactionBatchInput(BaseModel):
    transactions: list[PortfolioTransactionInput] = Field(min_length=1, max_length=1000)


@router.post("/transactions/batch", status_code=201, response_model=PortfolioTransactionBatchOut)
def create_transaction_batch(
    payload: PortfolioTransactionBatchInput, db: Session = Depends(get_db)
) -> dict:
    """Bulk transaction creation with atomic commit.
    
    All transactions are validated before any are inserted. If any transaction
    fails validation or causes a ledger error (oversell, mixed currency), the
    entire batch is rolled back.
    
    Returns the count of created transactions and their IDs.
    """
    service = PortfolioLedgerService()
    
    # Step 1: Validate all transactions upfront
    for i, tx_input in enumerate(payload.transactions):
        try:
            _reject_noncanonical_cash_row(tx_input)
        except HTTPException as exc:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Transaction {i}: {exc.detail}"
            ) from exc
    
    # Step 2: Insert all transactions without rebuilding positions (for performance)
    created_transactions: list[tuple[Transaction, Company]] = []
    company_ids_for_rebuild: set[int] = set()
    company_ids_for_analysis: set[int] = set()
    company_ids_for_backfill: set[int] = set()
    
    try:
        portfolio = service.fx.ensure_portfolio(db)
        
        for i, tx_input in enumerate(payload.transactions):
            try:
                # Validate and create company
                company = service.ensure_company(db, tx_input.ticker)
                normalized_action = tx_input.action.lower()
                
                # Validation checks (from PortfolioLedgerService.create_transaction)
                if normalized_action in {"buy", "sell"}:
                    snapshot_position = db.scalar(
                        select(Position).where(
                            Position.company_id == company.id,
                            *tenant_filters(db, Position),
                            Position.source == "screenshot_confirmed",
                        )
                    )
                    if snapshot_position is not None:
                        raise ValueError(
                            "Esta posición procede de una captura sin historial. "
                            "Importa primero el fichero del bróker para conciliar antes de añadir compras o ventas"
                        )
                
                # Oversell validation for sells
                if normalized_action == "sell":
                    held = service._held_quantity(db, company.id)
                    if tx_input.quantity > held:
                        raise PortfolioOversellError(
                            f"Cannot sell {tx_input.quantity} {tx_input.ticker.upper()}: only {held} shares are "
                            "available on the ledger."
                        )
                
                # Create transaction without rebuilding position
                transaction = Transaction(
                    portfolio_id=portfolio.id,
                    company_id=company.id,
                    trade_date=tx_input.trade_date,
                    action=normalized_action,
                    quantity=tx_input.quantity,
                    price=tx_input.price,
                    fees=tx_input.fees,
                    currency=canonical_currency_code(tx_input.currency),
                    external_id=f"manual-{uuid4().hex}",
                    raw_payload={"notes": tx_input.notes} if tx_input.notes else {},
                )
                db.add(transaction)
                db.flush()
                
                created_transactions.append((transaction, company))
                company_ids_for_rebuild.add(company.id)
                
                # Track companies for post-processing
                if normalized_action in {"buy", "sell"}:
                    company_ids_for_analysis.add(company.id)
                if normalized_action == "buy":
                    company_ids_for_backfill.add(company.id)
                    
            except (PortfolioOversellError, PortfolioMixedCurrencyError, ValueError) as exc:
                db.rollback()
                if isinstance(exc, PortfolioOversellError):
                    status_code = 409
                elif isinstance(exc, PortfolioMixedCurrencyError):
                    status_code = 422
                else:
                    status_code = 400
                raise HTTPException(
                    status_code=status_code,
                    detail=f"Transaction {i} ({tx_input.ticker} {tx_input.action}): {str(exc)}"
                ) from exc
        
        # Step 3: Rebuild positions once per company (batch optimization)
        for company_id in company_ids_for_rebuild:
            service.rebuild_position(db, company_id)
        
        # Enqueue fundamentals seed for new companies
        from app.services.fundamentals_seed_service import enqueue_fundamentals_seed
        for transaction, company in created_transactions:
            try:
                enqueue_fundamentals_seed(db, company.ticker)
            except Exception:  # noqa: BLE001
                # Nunca bloquear el lote por un fallo de la cola de seeds,
                # pero dejar rastro: un fallo silencioso deja empresas sin fundamentales.
                logger.warning(
                    "No se pudo encolar fundamentals seed para %s; el lote continua",
                    company.ticker,
                    exc_info=True,
                )
        
        # Commit the batch
        db.commit()
        
        # Step 4: Refresh all created transactions
        for transaction, _ in created_transactions:
            db.refresh(transaction)
        
        # Step 5: Post-processing (journal links and analysis queue)
        if company_ids_for_analysis:
            try:
                from app.services.journal_trade_link import auto_link_journal_trades_best_effort
                auto_link_journal_trades_best_effort(db, company_ids_for_analysis)
            except Exception:
                db.rollback()
        
        if company_ids_for_backfill:
            try:
                from app.services.market_close_sync import enqueue_price_backfills
                tenant_id = db.info["tenant_id"] if type(db.info.get("tenant_id")) is int else None
                user_id = str(db.info["user_id"]) if db.info.get("user_id") else None
                
                # Batch all company IDs into a single call for better performance
                enqueue_price_backfills(
                    db,
                    list(company_ids_for_backfill),
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            except Exception:  # noqa: BLE001
                db.rollback()
        
        # Enqueue analysis for buy transactions
        for company_id in company_ids_for_backfill:
            try:
                company = db.get(Company, company_id)
                if company:
                    enqueue_tracked_analysis(db, company.ticker)
            except Exception:
                db.rollback()
        
        # Return summary and transaction details
        return {
            "created": len(created_transactions),
            "transaction_ids": [tx.id for tx, _ in created_transactions],
            "transactions": [
                _transaction_payload(transaction, company)
                for transaction, company in created_transactions
            ],
        }
        
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_detail(exc, 500)
        ) from exc


@router.put("/transactions/{transaction_id}", response_model=PortfolioTransactionOut)
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
    # Omitir `fees` conserva la comision registrada (el default 0 del modelo no es un dato).
    if "fees" in payload.model_fields_set:
        transaction.fees = payload.fees
    transaction.currency = canonical_currency_code(payload.currency)
    transaction.raw_payload = {"notes": payload.notes} if payload.notes else {}
    try:
        # La sesion va con autoflush=False: sin volcar el cambio, la consulta
        # de rebuild_position leeria de la BD el ticker y la fecha ANTIGUOS
        # (posicion fantasma del ticker viejo, venta anterior a su compra
        # aceptada) mientras las cantidades salen del objeto ya editado.
        db.flush()
        if original_company_id is not None:
            service.rebuild_position(
                db,
                original_company_id,
                drop_when_empty=company.id != original_company_id,
            )
        if company.id != original_company_id:
            service.rebuild_position(db, company.id)
        db.commit()
        db.refresh(transaction)
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


@router.delete("/transactions/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)) -> None:
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.action not in {"buy", "sell"}:
        raise HTTPException(status_code=404, detail="Transaction not found")
    company_id = transaction.company_id
    try:
        db.delete(transaction)
        db.flush()
        if company_id is not None:
            PortfolioLedgerService().rebuild_position(db, company_id, drop_when_empty=True)
        db.commit()
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


@router.patch("/prices", response_model=PortfolioPriceUpdateOut)
def update_price(payload: PortfolioPriceInput, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, payload.ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Holding not found")
    try:
        position = PortfolioLedgerService().update_market_price(
            db, company_id=company.id, price=payload.price, as_of=payload.as_of
        )
        db.commit()
        # Precio manual: limpia valoraciones y lectores de mercado cacheados.
        invalidate_portfolio_cache(db=db)
        invalidate_market_data_cache()
        return {"ticker": company.ticker, "market_price": float(position.market_price)}
    except ValuationHeldError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/refresh-market", response_model=PortfolioRefreshMarketOut, response_model_exclude_unset=True)
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


@router.get("/cash", response_model=list[CashBalanceOut])
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
        raise ui_error(403, "flex_import_disabled")
    if not (settings.ibkr_flex_account_id or "").strip():
        raise ui_error(503, "ibkr_account_not_configured")
    from app.models import IBKRConnection
    if db.scalar(select(IBKRConnection.id).where(IBKRConnection.tenant_id == db.info.get("tenant_id"))) is not None:
        raise HTTPException(status_code=409, detail="Usa el conector IBKR de Ajustes para esta cartera.")
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


@router.post("/import/ibkr/xml", response_model=PortfolioIbkrXmlImportOut)
def import_ibkr_xml(payload: IBKRXmlImportRequest, db: Session = Depends(get_db)) -> dict:
    settings = _require_ibkr_owner(db)
    try:
        return IBKRImportService().import_flex_xml(
            db, payload.xml, expected_account_id=settings.ibkr_flex_account_id, max_statement_age_days=5,
        )
    except IBKRImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/ibkr/csv", response_model=PortfolioIbkrCsvImportOut)
def import_ibkr_csv(payload: IBKRCsvImportRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return IBKRImportService().import_ibkr_csv(db, payload.csv)
    except IBKRImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CsvPreviewRequest(BaseModel):
    # Tope duro: el preview parsea el contenido entero en memoria.
    content: str = Field(max_length=MAX_IMPORT_BYTES)
    filename: str = "import.csv"
    column_mapping: dict[str, str] | None = None


@router.post("/import/preview", response_model=TransactionImportPreviewResponse)
def preview_transaction_import(
    payload: CsvPreviewRequest,
) -> TransactionImportPreviewResponse:
    """Valida un archivo CSV o texto tabular y devuelve informe previo con errores y mapeo detectado."""
    try:
        service = TransactionImportService()
        return service.preview_import(
            file_bytes=payload.content.encode("utf-8"),
            filename=payload.filename,
            custom_mapping=payload.column_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/commit", response_model=PortfolioImportCommitOut)
def commit_transaction_import(
    payload: TransactionImportCommitRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Inserta atómicamente el lote de transacciones validadas en la cartera."""
    try:
        service = TransactionImportService()
        return service.commit_import(db, payload.transactions, source_filename=payload.source_filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/file", response_model=TransactionImportPreviewResponse)
async def upload_transaction_import_file(
    file: UploadFile = File(...),
) -> TransactionImportPreviewResponse:
    """Sube un archivo CSV o Excel (.xlsx) y realiza la validación previa de transacciones."""
    # Lectura acotada en bloques (como knowledge/sources): un upload sin tope
    # agotaria la memoria del worker con un solo archivo grande.
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MAX_IMPORT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"El archivo supera el máximo de {MAX_IMPORT_BYTES // (1024 * 1024)} MB para importación",
            )
    content = bytes(content)
    try:
        service = TransactionImportService()
        return service.preview_import(
            file_bytes=content,
            filename=file.filename or "uploaded.csv",
        )
    except ValueError as exc:
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


@router.get("/forecast", response_model=PortfolioForecastOut)
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
        "assumptions": ["Sin posiciones: no hay previsión que calcular."],
    }
    if not rows:
        return empty

    valued: list[tuple[Position, Company, float]] = []
    fx_excluded: list[dict] = []
    for position, company in rows:
        if position.valuation_hold_reason:
            # Valoracion en suspension (split sin precio post-split verificado): el
            # market_price de la fila es un centinela 0, nunca un precio. Se declara
            # con su causa real, no como "conversion N/D".
            fx_excluded.append(
                {
                    "ticker": company.ticker,
                    "name": company.name,
                    "weight": None,
                    "currency": position.currency,
                    "reason_code": "valuation_hold",
                    "reason": f"Valoración pendiente: {position.valuation_hold_reason}.",
                }
            )
            continue
        if position.market_value_base is None:
            fx_excluded.append(
                {
                    "ticker": company.ticker,
                    "name": company.name,
                    "weight": None,
                    "currency": position.currency,
                    "reason_code": "no_base_value",
                    "reason": "Sin valor en moneda base (conversión N/D): no se suma a la cartera.",
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
        out["assumptions"] = ["Ninguna posición tiene valor en moneda base: agregados N/D."]
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
            excluded_out.append(
                {
                    **base_info,
                    "reason_code": "no_published_thesis",
                    "reason": f"Sin tesis publicada vigente{suffix}: excluida de la previsión.",
                }
            )
            continue
        intrinsic, basis_label = _intrinsic_for_comparison(thesis, position, company)
        if intrinsic is None:
            reason = {
                "adr_without_listed_values": "ADR sin valores por acción cotizada: comparación con el precio no verificada (N/D).",
                "currency_mismatch": "Moneda de la posición distinta de la moneda de cotización de la compañía: comparación sin conversión verificada (N/D).",
            }.get(basis_label, "Base de valoración no verificada (tesis sin value_per_share_basis del motor): comparación con el precio N/D, nunca asumida.")
            excluded_out.append({**base_info, "reason_code": "valuation_basis_unverified", "reason": reason})
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
            excluded_out.append(
                {**base_info, "reason_code": "no_computable_intrinsic", "reason": "Tesis sin valores intrinsecos computables."}
            )
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
        "El esperado del CAGR es la media de los CAGR por escenario ponderada por probabilidad (no es el CAGR del valor esperado: no coinciden). Solo se da con probabilidad total del 100 % y sin entradas inválidas descartadas; con menos, solo se muestra el parcial y la probabilidad usada."
        + (" Probabilidades inválidas (fuera de [0, 1] o no finitas) descartadas en alguna posición." if any_invalid_probs else ""),
        (
            f"Cobertura de cartera N/D: {len(fx_excluded)} posición(es) sin conversión a moneda base; "
            "pesos y agregados cubiertos usan SOLO el subset valorado, nunca la cartera completa."
            if fx_excluded
            else f"Cobertura con tesis publicada: {covered_weight * 100:.1f}% de la cartera; el resto se lista en las excluidas.".replace(".", ",", 1)
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
