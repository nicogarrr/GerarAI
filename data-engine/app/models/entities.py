from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

# Alias para las columnas llamadas `date`. Dentro del cuerpo de una clase,
# `date: Mapped[date]` hace que el anotado se refiera a la propia columna
# mientras se evalua, y pyright lo rechaza con "Type of 'date' could not be
# determined because it refers to itself".
_DateT = date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.services.fact_anchor import FactAnchorSpec


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ModelAlias(Base, TimestampMixin):
    """Stable internal model name mapped to a real provider identifier."""

    __tablename__ = "model_aliases"
    __table_args__ = (
        UniqueConstraint(
            "internal_alias", "provider", name="uq_model_alias_provider"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    internal_alias: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    provider_model_id: Mapped[str] = mapped_column(String(240))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    context_window: Mapped[int] = mapped_column(Integer)
    input_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    output_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    supported_capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)


class TenantOwnedMixin:
    """Marks rows that must be isolated by the active Research OS tenant."""

    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="Research workspace")
    status: Mapped[str] = mapped_column(String(40), default="active")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Portfolio(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_portfolio_tenant_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="Main")
    base_currency: Mapped[str] = mapped_column(String(10), default="EUR")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    positions: Mapped[list["Position"]] = relationship(
        "Position", back_populates="portfolio", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="portfolio", cascade="all, delete-orphan"
    )
    daily_snapshots: Mapped[list["PortfolioDailySnapshot"]] = relationship(
        "PortfolioDailySnapshot", back_populates="portfolio", cascade="all, delete-orphan"
    )
    tax_reports: Mapped[list["TaxReport"]] = relationship(
        "TaxReport", back_populates="portfolio", cascade="all, delete-orphan"
    )
    investment_plans: Mapped[list["InvestmentPlan"]] = relationship(
        "InvestmentPlan", back_populates="portfolio", cascade="all, delete-orphan"
    )


class WatchItem(TenantOwnedMixin, Base, TimestampMixin):
    """A symbol the tenant is following (research watchlist)."""

    __tablename__ = "watch_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "symbol", name="uq_watch_item_tenant_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DcaSignalState(TenantOwnedMixin, Base, TimestampMixin):
    """Ultimo veredicto DCA por ticker seguido (watchlist y/o cartera).

    Una fila por (tenant, simbolo). ``level`` usa los codigos del motor
    (4..1 compra, -1/-2 recorte). ``last_alerted_*`` es la memoria del aviso:
    el mismo nivel en el mismo mes nunca vuelve a avisar.
    """

    __tablename__ = "dca_signal_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "symbol", name="uq_dca_signal_state_tenant_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    level: Mapped[int] = mapped_column(Integer)
    previous_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(7))
    signal_date: Mapped[_DateT] = mapped_column(Date)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    level_prices: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    # "¿Cuantas veces estaba mas arriba?" (dca_signal_engine.hit_rates) de la
    # ultima evaluacion; NULL = aun sin calcular.
    hit_rates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    params_version: Mapped[str] = mapped_column(String(40))
    last_alerted_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_alerted_period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data_source: Mapped[str] = mapped_column(String(40))


class DcaEvaluationRun(TenantOwnedMixin, Base, TimestampMixin):
    """Una ejecucion de la evaluacion DCA (job diario o boton manual).

    Existe para que la UI distinga "nunca se ha ejecutado" de "la ultima
    ejecucion fallo": sin esta fila ambos casos salian como "Sin evaluar".
    Solo guarda el resumen que ya devuelve ``evaluate_watchlist``; no cambia
    como se calcula ningun nivel.
    """

    __tablename__ = "dca_evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16))  # scheduler | manual
    status: Mapped[str] = mapped_column(String(16))  # running | ok | error
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tracked: Mapped[int] = mapped_column(Integer, default=0)
    evaluated: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    alerted_count: Mapped[int] = mapped_column(Integer, default=0)
    # Simbolos omitidos/fallidos con su motivo (acotado), sin datos de usuario.
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    params_version: Mapped[str | None] = mapped_column(String(40), nullable=True)


class DcaAlertOverride(TenantOwnedMixin, Base, TimestampMixin):
    """Nivel minimo de aviso DCA por ticker (watchlist o cartera).

    Sin fila = se usa el global (DCA_ALERT_MIN_LEVEL). ``min_level`` 1-4 =
    nivel de compra minimo que avisa; 0 = avisos apagados para ese ticker.
    Tabla propia (y no columna en watch_items) para cubrir tambien los
    tickers que solo estan en cartera.
    """

    __tablename__ = "dca_alert_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "symbol", name="uq_dca_alert_override_tenant_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    min_level: Mapped[int] = mapped_column(Integer)


class EarningsDate(Base, TimestampMixin):
    """Fecha de resultados de un ticker (dato de mercado, no del tenant).

    ``confirmed`` es tri-estado: True = el proveedor la da por confirmada,
    False = el proveedor la marca estimada, None = la fuente no lo dice.
    ``session`` solo guarda la franja que publica la fuente (pre/after market);
    nunca una hora inventada. Las filas ``source='manual'`` las escribe una
    persona con enlace a la fuente y el refresco automatico no las toca.
    """

    __tablename__ = "earnings_dates"
    __table_args__ = (
        UniqueConstraint("ticker", "event_date", "source", name="uq_earnings_date_ticker_day_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    session: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fiscal_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(40))
    source_label: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class CalendarFeedToken(TenantOwnedMixin, Base, TimestampMixin):
    """Token publico (solo su hash) de la suscripcion ICS del calendario de resultados.

    El token en claro se muestra una unica vez al crearlo; aqui solo vive el
    SHA-256. Revocar = ``revoked_at``. Una suscripcion activa por tenant: crear
    una nueva revoca la anterior.
    """

    __tablename__ = "calendar_feed_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="followed")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FXRate(TenantOwnedMixin, Base, TimestampMixin):
    """Historical conversion where quote amount × rate = base amount."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "base_currency",
            "quote_currency",
            "rate_date",
            name="uq_fx_rate_tenant_pair_date",
        ),
        Index("ix_fx_rates_base_quote_date", "base_currency", "quote_currency", "rate_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(10), index=True)
    quote_currency: Mapped[str] = mapped_column(String(10), index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    exchange: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    sector: Mapped[str] = mapped_column(String(120), default="Unknown")
    industry: Mapped[str] = mapped_column(String(160), default="Unknown")
    cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ir_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domicile_country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # ISIN del valor (12 caracteres), capturado del Flex XML de IBKR; lo
    # necesita el Modelo 720 y verifica el país emisor por prefijo.
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    company_type: Mapped[str] = mapped_column(String(80))
    valuation_model: Mapped[str] = mapped_column(String(120))
    special_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    special_risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    factor_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Ultimo intento de enriquecimiento Finnhub (haya o no cambiado nada):
    # /companies/ensure no reintenta dentro del enfriamiento (antes llamaba
    # a Finnhub en cada ensure de una ficha con industria no mapeada,
    # indefinidamente). El barrido manual lo ignora y fuerza.
    enrichment_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    positions: Mapped[list["Position"]] = relationship(back_populates="company")
    thesis_versions: Mapped[list["ThesisVersion"]] = relationship(back_populates="company")
    claims: Mapped[list["Claim"]] = relationship(back_populates="company")
    memory_items: Mapped[list["MemoryItem"]] = relationship(back_populates="company")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", foreign_keys="[Transaction.company_id]")


class Position(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_portfolio_company", "portfolio_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True, index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    market_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    base_currency: Mapped[str] = mapped_column(String(10), default="EUR")
    market_value_native: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    market_value_base: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    cost_basis_native: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    cost_basis_base: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    unrealized_pnl_base: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    realized_pnl_base: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")
    as_of: Mapped[date] = mapped_column(Date, default=date.today)
    # Fecha del extracto del broker que fijo cantidad y coste. Distinta de as_of
    # (fecha de la cotizacion): un refresco de precios adelanta as_of sin tocar
    # el coste. NULL = filas anteriores a esta columna: la conciliacion usa as_of.
    statement_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Valoracion en suspenso (p. ej. tras un split aplicado sin precio post-split
    # verificado). NULL = sin suspension. Mientras haya motivo, market_price /
    # market_value / unrealized_* NO son una cotizacion: ningun refresco ni rebuild
    # los repone; solo release_valuation_hold con un precio verificado.
    valuation_hold_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    valuation_hold_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valuation_hold_since: Mapped[date | None] = mapped_column(Date, nullable=True)

    company: Mapped[Company] = relationship(back_populates="positions")
    portfolio: Mapped["Portfolio | None"] = relationship("Portfolio", back_populates="positions")


class CashBalance(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "cash_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(10), index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    settled_cash: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    source: Mapped[str] = mapped_column(String(80), default="manual")
    as_of: Mapped[date] = mapped_column(Date, default=date.today)


class Transaction(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_transaction_tenant_external"),
        Index("ix_transactions_portfolio_trade_date", "portfolio_id", "trade_date"),
        Index("ix_transactions_company_action", "company_id", "action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    # 4 decimales: IBKR cobra fracciones de céntimo (0,355 USD); con 2 se redondeaban.
    fees: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    company: Mapped["Company"] = relationship("Company", foreign_keys=[company_id], overlaps="transactions")
    portfolio: Mapped["Portfolio | None"] = relationship("Portfolio", back_populates="transactions")


class IbkrRawRow(TenantOwnedMixin, Base, TimestampMixin):
    """Fila cruda de un Flex de IBKR, con TODOS sus atributos, se use o no todavia.

    Un valor corregido es una fila nueva (hash distinto); nada se sobrescribe.
    """

    __tablename__ = "ibkr_raw_rows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "row_hash", name="uq_ibkr_raw_row_tenant_hash"),
        Index("ix_ibkr_raw_rows_section", "section"),
        Index("ix_ibkr_raw_rows_snapshot", "tenant_id", "report_date", "symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    section: Mapped[str] = mapped_column(String(80))
    path: Mapped[str] = mapped_column(String(200))
    row_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Copias indexadas de payload (symbol, reportDate/asOfDate) para leer solo
    # el extracto del dia de cada posicion; el payload sigue intacto.
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)


def ibkr_raw_row_keys(payload: dict | None) -> tuple[str | None, date | None]:
    """(symbol, fecha de informe) de una fila cruda, con el mismo parseo que la
    conciliacion de costes; lo que no se puede leer queda en None."""
    payload = payload or {}
    symbol = payload.get("symbol")
    symbol = symbol if isinstance(symbol, str) and 0 < len(symbol) <= 64 else None
    day = str(payload.get("reportDate") or payload.get("asOfDate") or "").split(";", 1)[0]
    try:
        report_date = datetime.strptime(day.replace("-", ""), "%Y%m%d").date()
    except ValueError:
        report_date = None
    return symbol, report_date


@event.listens_for(IbkrRawRow, "before_insert")
def _fill_ibkr_raw_row_keys(_mapper, _connection, row: IbkrRawRow) -> None:
    symbol, report_date = ibkr_raw_row_keys(row.payload)
    if row.symbol is None:
        row.symbol = symbol
    if row.report_date is None:
        row.report_date = report_date


class FxConversion(TenantOwnedMixin, Base, TimestampMixin):
    """Cambio de divisa real (Flex Trades con assetCategory CASH, p. ej. EUR.USD).

    No es una compra de valores: no entra en el FIFO de acciones. Alimenta el
    libro de divisas (``currency_ledger``). Importes siempre positivos.
    """

    __tablename__ = "fx_conversions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_fx_conversion_tenant_external"),
        Index("ix_fx_conversions_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date)
    disposed_currency: Mapped[str] = mapped_column(String(10))
    disposed_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    acquired_currency: Mapped[str] = mapped_column(String(10))
    acquired_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortfolioDailySnapshot(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "portfolio_daily_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "portfolio_id",
            "snapshot_date",
            name="uq_portfolio_daily_snapshot_tenant_date",
        ),
        Index("ix_portfolio_snapshots_portfolio_date", "portfolio_id", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    base_currency: Mapped[str] = mapped_column(String(10))
    positions_value_base: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    cash_value_base: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    total_value_base: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    net_external_flow_base: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal("0")
    )
    daily_return: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    cumulative_twr: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10), nullable=True
    )
    pricing_coverage: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0")
    )
    source: Mapped[str] = mapped_column(String(80), default="market_refresh")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="daily_snapshots")


class PositionDailySnapshot(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "position_daily_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_snapshot_id",
            "company_id",
            name="uq_position_daily_snapshot_company",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_daily_snapshots.id", ondelete="CASCADE"), index=True
    )
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    market_price_native: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(String(10))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    market_value_native: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    market_value_base: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="market_refresh")


class CashDailySnapshot(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "cash_daily_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_snapshot_id",
            "currency",
            name="uq_cash_daily_snapshot_currency",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_daily_snapshots.id", ondelete="CASCADE"), index=True
    )
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(10), index=True)
    balance_native: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    balance_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="market_refresh")


class InsiderFiling(TenantOwnedMixin, Base, TimestampMixin):
    """Persisted SEC Form 4/4-A filing envelope (provenance, never overwritten).

    One row per accession number. Amendments (4/A) get their own immutable
    row; they never mutate the filing they amend.
    """

    __tablename__ = "insider_filings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "accession_number", name="uq_insider_filings_tenant_accession"),
        Index("ix_insider_filings_issuer", "issuer_cik"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    accession_number: Mapped[str] = mapped_column(String(40))
    form: Mapped[str] = mapped_column(String(10))
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    amends_accession: Mapped[str | None] = mapped_column(String(40), nullable=True)
    issuer_cik: Mapped[str] = mapped_column(String(20))
    issuer_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    filing_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_of_report: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    index_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="parsed")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    transactions: Mapped[list["InsiderTransaction"]] = relationship(back_populates="filing")


class InsiderTransaction(TenantOwnedMixin, Base, TimestampMixin):
    """One persisted Form 4 transaction row, keyed by a stable fingerprint.

    The fingerprint (accession + row ordinal + raw fields) makes re-ingestion
    idempotent: the same SEC row is never stored twice, and an amendment adds
    new rows instead of mutating the original ones.
    """

    __tablename__ = "insider_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fingerprint", name="uq_insider_transactions_tenant_fingerprint"),
        Index("ix_insider_transactions_filing", "filing_id"),
        Index("ix_insider_transactions_ticker_date", "issuer_ticker", "tx_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    filing_id: Mapped[int] = mapped_column(ForeignKey("insider_filings.id", ondelete="CASCADE"))
    accession_number: Mapped[str] = mapped_column(String(40))
    form: Mapped[str] = mapped_column(String(10))
    issuer_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    insider: Mapped[str | None] = mapped_column(String(500), nullable=True)
    insider_cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str | None] = mapped_column(String(300), nullable=True)
    officer_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    multi_reporter: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution: Mapped[str | None] = mapped_column(String(30), nullable=True)
    code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    acquired_disposed: Mapped[str | None] = mapped_column(String(5), nullable=True)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_derivative: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_10b5_1: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    data_quality: Mapped[dict] = mapped_column(JSON, default=dict)

    filing: Mapped["InsiderFiling"] = relationship(back_populates="transactions")


class Schedule13DGFiling(TenantOwnedMixin, Base, TimestampMixin):
    """Persisted SC 13D/13G filing (titular >5%), fuente primaria de propiedad.

    One immutable row per accession number (tenant-scoped), igual que
    ``InsiderFiling``: las enmiendas (…/A) crean su propia fila y nunca
    sobrescriben el filing que corrigen. Los campos que el parser no pudo
    leer quedan NULL: la UI muestra N/D, nunca una cifra inventada.
    """

    __tablename__ = "schedule_13dg_filings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "accession_number", name="uq_schedule13dg_tenant_accession"
        ),
        Index("ix_schedule13dg_issuer", "issuer_cik"),
        Index("ix_schedule13dg_ticker", "issuer_ticker"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    accession_number: Mapped[str] = mapped_column(String(40))
    form: Mapped[str] = mapped_column(String(30))
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    issuer_cik: Mapped[str] = mapped_column(String(20))
    issuer_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    filer_cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    holder_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    aggregate_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    percent_of_class: Mapped[float | None] = mapped_column(Float, nullable=True)
    sole_voting_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    shared_voting_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    sole_dispositive_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    shared_dispositive_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    holders: Mapped[list] = mapped_column(JSON, default=list)
    securities_class_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    snapshot_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    filing_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    signature_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    index_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="parsed")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Document(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(400))
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Retencion: fecha en que se borro el original y los chunks y la fila
    # quedo como tombstone auditable. NULL = documento vivo. Se indexa para
    # que la purga no vuelva a examinar tombstones en cada corrida.
    retention_tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_doc_idx", "document_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class PrimarySourceRecord(TenantOwnedMixin, Base, TimestampMixin):
    """Tenant-bound news-to-official-document link, versioned by URL and bytes."""

    __tablename__ = "primary_source_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "news_event_id", "final_url", "checksum",
                         name="uq_primary_source_event_url_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    news_event_id: Mapped[int] = mapped_column(ForeignKey("news_events.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    requested_url: Mapped[str] = mapped_column(String(2000))
    final_url: Mapped[str] = mapped_column(String(2000))
    checksum: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference_kind: Mapped[str] = mapped_column(String(80))


class AlertAnalysis(TenantOwnedMixin, Base, TimestampMixin):
    """Immutable result versions per alert; status moves pending to a final state."""

    __tablename__ = "alert_analyses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "alert_id", "version", name="uq_alert_analysis_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("research_alerts.id", ondelete="CASCADE"), index=True)
    news_event_id: Mapped[int] = mapped_column(ForeignKey("news_events.id"), index=True)
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class ITUNotice(TenantOwnedMixin, Base, TimestampMixin):
    """Unassigned official registry candidate, never a company mapping by name."""

    __tablename__ = "itu_notices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "submission_id", name="uq_itu_notice_submission"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(40))
    notice_id: Mapped[str] = mapped_column(String(40))
    satellite_name: Mapped[str] = mapped_column(String(500))
    br_registry_date: Mapped[str] = mapped_column(String(20))
    submission_type: Mapped[str] = mapped_column(String(120))
    act_code: Mapped[str] = mapped_column(String(10))
    detail_url: Mapped[str] = mapped_column(String(1000))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class FinancialFact(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "financial_facts"
    __table_args__ = (
        Index("ix_financial_facts_company_metric_year", "company_id", "metric", "fiscal_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    metric: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    unit: Mapped[str] = mapped_column(String(40), default="USD")
    period: Mapped[str] = mapped_column(String(40))
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(80), default="seed")
    is_reported: Mapped[bool] = mapped_column(Boolean, default=True)
    is_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.80"))
    # Filing SEC (accn) del que salio el hecho reportado: la ingesta lo conoce
    # al anclar cada fila a su filing y lo persiste para que la procedencia
    # OFICIAL sea auditable por accession. NULL en derivadas y no-SEC.
    accession_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Fecha en que se PUBLICO el filing del que sale la cifra guardada (campo
    # `filed` de SEC companyfacts). Es el eje "cuando lo supo el mercado": una
    # cifra del FY2019 reexpresada en un 10-K de 2021 no era conocible en 2020.
    # La ingesta guarda la ultima cifra (reexpresada) con SU fecha de filing;
    # la primera version publicada no se conserva. NULL en no-SEC, en filas
    # anteriores a la migracion 0082 y en derivadas sin entradas fechadas.
    filed: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Procedencia del dato: el documento (filing SEC/ESEF, pagina del proveedor)
    # del que salio la cifra. La carga eager se pide SOLO en el endpoint de
    # facts (selectinload alli); el resto de consultas masivas (screener,
    # valuation) no arrastra el join.
    source: Mapped["Document | None"] = relationship(foreign_keys=[source_id])

    @property
    def source_url(self) -> str | None:
        from app.core.source_urls import linkable_source_url

        return linkable_source_url(self.source.source_url) if self.source is not None else None

    @property
    def source_title(self) -> str | None:
        return self.source.title if self.source is not None else None

    @property
    def source_published_at(self) -> datetime | None:
        return self.source.published_at if self.source is not None else None


class CompanyKPI(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "company_kpis"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "metric_key", name="uq_company_kpi_metric"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    metric_key: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    canonical_unit: Mapped[str] = mapped_column(String(40), default="unknown")
    period_type: Mapped[str] = mapped_column(String(40), default="annual_or_quarterly")
    driver_type: Mapped[str] = mapped_column(String(60), default="kpi")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    registry_version: Mapped[str] = mapped_column(String(80), default="framework-v1")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class KPIExtractionCandidate(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "kpi_extraction_candidates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_chunk_id",
            "metric_key",
            "period",
            "raw_value",
            name="uq_kpi_candidate_observation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    company_kpi_id: Mapped[int] = mapped_column(ForeignKey("company_kpis.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    document_chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id"), index=True)
    metric_key: Mapped[str] = mapped_column(String(120), index=True)
    raw_label: Mapped[str] = mapped_column(String(240))
    raw_value: Mapped[str] = mapped_column(String(160))
    raw_unit: Mapped[str] = mapped_column(String(80), default="unknown")
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    canonical_unit: Mapped[str] = mapped_column(String(40), default="unknown")
    period: Mapped[str] = mapped_column(String(40), index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    fiscal_quarter: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    reconciliation_status: Mapped[str] = mapped_column(String(60), default="pending")
    status: Mapped[str] = mapped_column(String(40), default="pending_approval", index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.50"))
    extraction_model: Mapped[str] = mapped_column(String(160), default="unknown")
    prompt_version: Mapped[str] = mapped_column(String(120), default="kpi-extraction-v1")
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canonical_fact_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class CalculatedMetric(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "calculated_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "company_id",
            "metric",
            "period",
            "definition_version",
            name="uq_calculated_metric_definition_period",
        ),
        Index("ix_calculated_metrics_company_metric", "company_id", "metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    metric: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit: Mapped[str] = mapped_column(String(40), default="decimal")
    period: Mapped[str] = mapped_column(String(40), index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="ok")
    definition_version: Mapped[str] = mapped_column(String(80), default="v1")
    formula: Mapped[str] = mapped_column(Text)
    numerator: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    denominator: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    source_fact_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    calculation_trace: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.70"))


class FinancialStatement(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "financial_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    statement_type: Mapped[str] = mapped_column(String(40))
    period: Mapped[str] = mapped_column(String(40))
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    facts: Mapped[dict] = mapped_column(JSON, default=dict)


class MarketObservation(Base, TimestampMixin):
    """Public observation with immutable source/date/vintage."""

    __tablename__ = "market_observations"
    __table_args__ = (
        UniqueConstraint(
            "metric_key",
            "geography",
            "observation_date",
            "source",
            "vintage",
            name="uq_market_observation_vintage",
        ),
        Index("ix_market_observations_metric_date", "metric_key", "observation_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(120))
    geography: Mapped[str] = mapped_column(String(80))
    observation_date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(String(1000))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vintage: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))


class MarketRegimeSnapshot(Base, TimestampMixin):
    __tablename__ = "market_regime_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "model_version", "input_hash", name="uq_market_regime_inputs"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    model_version: Mapped[str] = mapped_column(String(120))
    input_hash: Mapped[str] = mapped_column(String(64))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    probabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    coverage: Mapped[str] = mapped_column(String(40))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortfolioMoveDigest(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "portfolio_move_digests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "digest_date", "version", "input_hash", name="uq_portfolio_move_digest_version"),
        Index("ix_portfolio_move_digests_tenant_date", "tenant_id", "digest_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    digest_date: Mapped[date] = mapped_column(Date, index=True)
    version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(String(64))
    items: Mapped[list[dict]] = mapped_column(JSON, default=list)
    coverage: Mapped[str] = mapped_column(String(40))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketPrice(Base, TimestampMixin):
    __tablename__ = "market_prices"
    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_market_price_company_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    date: Mapped[_DateT] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    # NULL = la fuente dio un spot, no una serie ajustada por splits/dividendos.
    # Copiar close afirmaria un ajuste nunca realizado y un 0 fabricado hundia
    # a cero los retornos compuestos; los consumidores tratan falsy como
    # "sin dato ajustado" y lo saltan.
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    # NULL = la fuente no da el volumen (spot sin dato); un 0 fabricado
    # coronaba al ticker como el menos activo con un dato inexistente.
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Exact unit supplied by the provider: GBP != GBp/GBX. NULL is legacy
    # or an upstream response without a verifiable quote unit, never guessed.
    quote_currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="seed")


_FROM_SPEC_TOKEN = object()


class FactAnchor(TenantOwnedMixin, Base, TimestampMixin):
    """Dato extraido anclado a la frase exacta del filing (provenance a nivel dato).

    Persistencia verificada: la UNICA via de creacion es `from_spec`, que
    re-verifica el spec contra el body original justo antes de persistir; el
    constructor directo esta bloqueado. Append-only: eventos ORM bloquean
    UPDATE/DELETE por fila y DML masivo del ORM (update()/delete() en lote);
    si el dato se re-extrae, se inserta otra fila y la anterior queda como
    historico. Limites declarados: (1) SQL crudo Core sobre la conexion,
    fuera de la sesion ORM, no pasa por esas guardias; (2) INFERIDO exige
    derivacion no vacia, pero no prueba el calculo (trazabilidad, no
    validacion del metodo); (3) codigo hostil ejecutandose dentro del proceso
    puede manipular atributos privados o guards - estas defensas cubren la
    API normal, no un adversario con ejecucion arbitraria.
    """

    __tablename__ = "fact_anchors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "accession_number",
            "filename",
            "field",
            "quote_offset",
            "body_sha256",
            name="uq_fact_anchors_tenant_point",
        ),
        Index("ix_fact_anchors_company", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    accession_number: Mapped[str] = mapped_column(String(40), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    body_sha256: Mapped[str] = mapped_column(String(64))
    field: Mapped[str] = mapped_column(String(80))
    value_text: Mapped[str] = mapped_column(String(2000))
    label: Mapped[str] = mapped_column(String(10))
    quote: Mapped[str] = mapped_column(Text)
    quote_offset: Mapped[int] = mapped_column(Integer)
    item: Mapped[str | None] = mapped_column(String(40), nullable=True)
    extractor: Mapped[str] = mapped_column(String(120))
    derivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True
    )

    def __init__(self, *_args: object, _token: object = None, **kwargs: object) -> None:
        # Cerrado a cal y canto: la unica construccion valida pasa por
        # from_spec, que es quien verifica. SQLAlchemy no llama a __init__
        # al cargar filas, asi que la lectura no se ve afectada.
        from app.services.fact_anchor import FactAnchorError

        if _token is not _FROM_SPEC_TOKEN:
            raise FactAnchorError(
                "FactAnchor solo se crea con FactAnchor.from_spec(spec, body=...): "
                "el constructor directo no esta verificado"
            )
        super().__init__(**kwargs)

    @classmethod
    def from_spec(
        cls,
        spec: "FactAnchorSpec",
        *,
        body: str,
        tenant_id: int | None,
        company_id: int | None = None,
    ) -> "FactAnchor":
        """Unica via verificada de persistir un ancla.

        Re-verifica el spec contra el body ORIGINAL en el momento de
        persistir: un spec manipulado (dataclasses.replace o construido a
        mano) que no ancla el valor en el filing no llega a la base de datos.
        """
        from app.services.fact_anchor import FactAnchorError, verify_anchor

        if not verify_anchor(body, spec):
            raise FactAnchorError(
                "el spec no verifica contra el body del filing: no se persiste"
            )
        anchor = cls(
            _token=_FROM_SPEC_TOKEN,
            tenant_id=tenant_id,
            company_id=company_id,
            accession_number=spec.accession,
            filename=spec.filename,
            body_sha256=spec.body_sha256,
            field=spec.field,
            value_text=spec.value_text,
            label=spec.label,
            quote=spec.quote,
            quote_offset=spec.quote_offset,
            item=spec.item,
            extractor=spec.extractor,
            derivation=spec.derivation,
        )
        # El body verificado queda retenido en memoria (transitorio, nunca se
        # persiste): before_insert re-verifica la fila ACTUAL contra el con
        # verify_anchor. Una huella recalculable de la propia fila no vale:
        # la misma instancia podria rehacerla tras mutarla.
        anchor._verified_body = body
        return anchor


@event.listens_for(FactAnchor, "before_update", propagate=True)
def _fact_anchor_no_update(mapper, connection, target):  # noqa: ANN001, ANN202
    from app.services.fact_anchor import FactAnchorError

    raise FactAnchorError("fact_anchors es append-only: UPDATE prohibido")


@event.listens_for(FactAnchor, "before_delete", propagate=True)
def _fact_anchor_no_delete(mapper, connection, target):  # noqa: ANN001, ANN202
    from app.services.fact_anchor import FactAnchorError

    raise FactAnchorError("fact_anchors es append-only: DELETE prohibido")


@event.listens_for(FactAnchor, "before_insert", propagate=True)
def _fact_anchor_revalidate_on_insert(mapper, connection, target):  # noqa: ANN001, ANN202
    """Al persistir se RE-VERIFICA la fila actual contra el body retenido
    desde from_spec (verify_anchor completo, no un checksum): mutar
    value/quote/hash/label/item entre construccion y flush no persiste.

    Limite honesto: esto defiende la API normal de la aplicacion. Python
    hostil con ejecucion arbitraria dentro del proceso puede tocar atributos
    privados o desactivar guards; contra eso no se promete defensa.
    """
    from app.services.fact_anchor import (
        FactAnchorError,
        FactAnchorSpec,
        verify_anchor,
    )

    body = getattr(target, "_verified_body", None)
    if body is None:
        raise FactAnchorError(
            "fact_anchors: fila sin body verificado; reconstruye con from_spec"
        )
    current = FactAnchorSpec(
        accession=target.accession_number,
        filename=target.filename,
        body_sha256=target.body_sha256,
        field=target.field,
        value_text=target.value_text,
        label=target.label,
        quote=target.quote,
        quote_offset=target.quote_offset,
        item=target.item,
        extractor=target.extractor,
        derivation=target.derivation,
    )
    if not verify_anchor(body, current):
        raise FactAnchorError(
            "fact_anchors: la fila fue modificada tras la verificacion; "
            "reconstruye con from_spec"
        )


@event.listens_for(Session, "do_orm_execute")
def _fact_anchor_no_bulk_dml(orm_execute_state):  # noqa: ANN001, ANN202
    """El DML masivo del ORM (update()/delete() en lote) salta los eventos por
    fila; aqui se bloquea para fact_anchors. Limite declarado: SQL Core crudo
    fuera de la sesion ORM."""
    from sqlalchemy import Delete, Update

    statement = orm_execute_state.statement
    if not isinstance(statement, (Update, Delete)):
        return
    table = getattr(statement, "table", None)
    if table is not None and getattr(table, "name", None) == FactAnchor.__table__.name:
        from app.services.fact_anchor import FactAnchorError

        raise FactAnchorError(
            "fact_anchors es append-only: DML masivo del ORM prohibido"
        )


class NewsEvent(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "news_events"
    __table_args__ = (
        Index("ix_news_events_company_date", "company_id", "date"),
        UniqueConstraint("sec_filing_identity", name="uq_news_sec_filing_identity"),
    )

    sec_filing_identity: Mapped[str | None] = mapped_column(String(100), nullable=True)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    title: Mapped[str] = mapped_column(String(400))
    source: Mapped[str] = mapped_column(String(120), default="manual")
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    event_type: Mapped[str] = mapped_column(String(80), default="unknown")
    materiality_score: Mapped[int] = mapped_column(Integer, default=0)
    impact_direction: Mapped[str] = mapped_column(String(40), default="neutral")
    affected_thesis: Mapped[bool] = mapped_column(Boolean, default=False)
    affected_assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_update: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ExternalClaim(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "external_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    claim: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(80))
    metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.80"))
    used_in_model: Mapped[bool] = mapped_column(Boolean, default=False)


class Transcript(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    period: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    transcript_text: Mapped[str] = mapped_column(Text, default="")


class CallClaim(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "call_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    speaker: Mapped[str] = mapped_column(String(160))
    speaker_role: Mapped[str] = mapped_column(String(120))
    claim: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(80))
    metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.80"))
    follow_up_required: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="open")
    later_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    linked_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )


class Catalyst(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "catalysts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    catalyst_type: Mapped[str] = mapped_column(String(80))
    materiality_score: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(40), default="open")
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )


class ValuationModel(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "valuation_models"
    __table_args__ = (
        Index("ix_valuation_models_company_version", "company_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    model_type: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    calculation_trace: Mapped[dict] = mapped_column(JSON, default=dict)


class ValuationAssumption(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "valuation_assumptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    valuation_model_id: Mapped[int] = mapped_column(
        ForeignKey("valuation_models.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(40), default="decimal")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scenario: Mapped[str] = mapped_column(String(40), default="base")
    source_type: Mapped[str] = mapped_column(String(80), default="user")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assumption_type: Mapped[str] = mapped_column(String(80), default="model")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.70"))
    is_user_override: Mapped[bool] = mapped_column(Boolean, default=False)


class ValuationOutput(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "valuation_outputs"

    id: Mapped[int] = mapped_column(primary_key=True)
    valuation_model_id: Mapped[int] = mapped_column(
        ForeignKey("valuation_models.id", ondelete="CASCADE"), index=True
    )
    scenario: Mapped[str] = mapped_column(String(40), default="base")
    equity_value: Mapped[Decimal] = mapped_column(Numeric(24, 2), default=0)
    value_per_share: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)
    margin_of_safety: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ThesisVersion(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "thesis_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "version", name="uq_thesis_tenant_company_version"
        ),
        Index("ix_thesis_versions_company_version", "company_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    thesis_markdown: Mapped[str] = mapped_column(Text)
    executive_summary: Mapped[str] = mapped_column(Text)
    rating: Mapped[str] = mapped_column(String(40), default="watch")
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    bear_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    base_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    bull_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    margin_of_safety: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    data_confidence_score: Mapped[int] = mapped_column(Integer, default=0)
    source_coverage_score: Mapped[int] = mapped_column(Integer, default=0)
    red_team_score: Mapped[int] = mapped_column(Integer, default=0)
    valuation_risk_score: Mapped[int] = mapped_column(Integer, default=0)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Tesis profesional: hipotesis explicita, catalizadores con fecha,
    # criterios de invalidacion y probabilidades por escenario.
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalysts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    invalidation_criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Criterios de invalidacion ESTRUCTURADOS y opcionales: lista de
    # {metric, operator, threshold, description}. A diferencia del texto libre
    # de arriba, se evaluan: el evaluador de alertas los comprueba en cada
    # pasada (app/services/thesis_invalidation_rules.py). None = sin criterios.
    invalidation_rules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scenario_probabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Analisis narrativo (capa LLM opcional): secciones compuestas por
    # seleccion de plantillas con slots deterministicos. Null en versiones
    # anteriores a la capa o cuando la capa no produjo seleccion valida.
    narrative_sections: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Base por acción de los escenarios al generar la tesis (F394): ADR ratio y
    # valores ya convertidos. None = tesis anterior, sin evidencia de base.
    valuation_basis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    company: Mapped[Company] = relationship(back_populates="thesis_versions")


class ThesisDiff(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "thesis_diffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    from_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    change_summary: Mapped[str] = mapped_column(Text)
    affected_assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    rating_changed: Mapped[bool] = mapped_column(Boolean, default=False)


class ThesisSection(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "thesis_sections"
    __table_args__ = (
        UniqueConstraint("thesis_version_id", "section_key", name="uq_thesis_section_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_version_id: Mapped[int] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    section_key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.70"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Claim(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_company_status", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    thesis_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(80), default="thesis")
    status: Mapped[str] = mapped_column(String(40), default="unverified")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.50"))
    materiality_score: Mapped[int] = mapped_column(Integer, default=5)
    source_quality: Mapped[str] = mapped_column(String(40), default="unknown")
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    company: Mapped[Company | None] = relationship(back_populates="claims")
    evidence: Mapped[list["ClaimEvidence"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimEvidence(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "claim_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default="supports")
    summary: Mapped[str] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.70"))
    source_tier: Mapped[str] = mapped_column(String(40), default="secondary")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    claim: Mapped[Claim] = relationship(back_populates="evidence")


class ThesisChange(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "thesis_changes"
    __table_args__ = (
        Index("ix_thesis_changes_company_created", "company_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    from_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    change_type: Mapped[str] = mapped_column(String(80), default="update")
    impact_direction: Mapped[str] = mapped_column(String(40), default="neutral")
    materiality_score: Mapped[int] = mapped_column(Integer, default=5)
    summary: Mapped[str] = mapped_column(Text)
    affected_claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    affected_metrics: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)


class ResearchSession(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "research_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open")
    summary: Mapped[str] = mapped_column(Text, default="")
    source_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    memory_item_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class MemoryItem(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    research_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(80), default="portfolio")
    memory_type: Mapped[str] = mapped_column(String(80), default="note")
    importance: Mapped[int] = mapped_column(Integer, default=5)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active")
    source_type: Mapped[str] = mapped_column(String(80), default="user")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    company: Mapped[Company | None] = relationship(back_populates="memory_items")


class SourceAudit(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "source_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True
    )
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_coverage_score: Mapped[int] = mapped_column(Integer, default=0)
    unsupported_claims: Mapped[list[str]] = mapped_column(JSON, default=list)
    weak_claims: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_conflicts: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_fixes: Mapped[list[str]] = mapped_column(JSON, default=list)


class RiskEvent(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "risk_events"
    __table_args__ = (
        Index("ix_risk_events_company_status", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    severity: Mapped[str] = mapped_column(String(40), default="info")
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open")


class DailyBrief(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "daily_briefs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "brief_date", name="uq_daily_brief_tenant_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_date: Mapped[date] = mapped_column(Date)
    markdown: Mapped[str] = mapped_column(Text)
    alerts: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=0)


class ChatSession(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), default="Research chat")
    scope: Mapped[str] = mapped_column(String(80), default="portfolio")
    messages: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class ModelRun(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow: Mapped[str] = mapped_column(String(120), index=True)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str] = mapped_column(String(160))
    prompt_version: Mapped[str] = mapped_column(String(120), default="unknown")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ChatTelemetryEvent(TenantOwnedMixin, Base, TimestampMixin):
    """Telemetría propia de /api/chat (€0, sin Langfuse): pregunta, ruta
    (LLM/determinista), latencia y error, por tenant."""

    __tablename__ = "chat_telemetry_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(500))
    route: Mapped[str] = mapped_column(String(60), index=True)
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class BudgetUsage(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "budget_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    model: Mapped[str] = mapped_column(String(160))
    workflow: Mapped[str] = mapped_column(String(120))
    cost_eur: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)


class EvidenceSuggestion(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "evidence_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    suggested_claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    suggestion_type: Mapped[str] = mapped_column(String(80), default="create_claim")
    statement: Mapped[str] = mapped_column(Text)
    relation: Mapped[str] = mapped_column(String(40), default="uncertain")
    rationale: Mapped[str] = mapped_column(Text, default="")
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.50"))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(120), default="evidence-suggestion-v1")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ResearchReview(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "research_reviews"
    __table_args__ = (
        Index("ix_research_reviews_company_status", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    review_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(40), default="medium")
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    thesis_change_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_changes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    news_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("news_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_to: Mapped[str | None] = mapped_column(String(160), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ThesisNode(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "thesis_nodes"
    __table_args__ = (
        UniqueConstraint(
            "thesis_version_id", "node_key", name="uq_thesis_node_version_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    thesis_version_id: Mapped[int] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="CASCADE"), index=True
    )
    node_key: Mapped[str] = mapped_column(String(160))
    node_type: Mapped[str] = mapped_column(String(80), default="assumption")
    label: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="active")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.50"))
    materiality_score: Mapped[int] = mapped_column(Integer, default=5)
    claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    invalidation_conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ThesisEdge(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "thesis_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_node_id", "to_node_id", "edge_type", name="uq_thesis_edge"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_node_id: Mapped[int] = mapped_column(ForeignKey("thesis_nodes.id", ondelete="CASCADE"), index=True)
    to_node_id: Mapped[int] = mapped_column(ForeignKey("thesis_nodes.id", ondelete="CASCADE"), index=True)
    edge_type: Mapped[str] = mapped_column(String(80), default="depends_on")
    strength: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ResearchAlert(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "research_alerts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fingerprint", name="uq_research_alert_fingerprint"),
        Index("ix_research_alerts_company_status", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    review_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_reviews.id", ondelete="SET NULL"), nullable=True, index=True
    )
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    alert_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(160))
    channels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["in_app"])
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Hora del ultimo disparo: la fila se reutiliza por fingerprint en
    # disparos repetidos y created_at queda en el primero.
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class TelegramLinkChallenge(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "telegram_link_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    candidate_chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class TelegramChatBinding(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "telegram_chat_bindings"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_telegram_binding_owner"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160))
    chat_id: Mapped[str] = mapped_column(String(32), unique=True)


class AlertSubscription(TenantOwnedMixin, Base, TimestampMixin):
    """One Telegram destination per authenticated personal workspace/type."""

    __tablename__ = "alert_subscriptions"
    __table_args__ = (UniqueConstraint("tenant_id", "event_type", name="uq_alert_subscription_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_id: Mapped[str] = mapped_column(String(32))
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushSubscription(TenantOwnedMixin, Base, TimestampMixin):
    """Dispositivo con Web Push (PWA) de un usuario. El endpoint es una
    capacidad: quien lo conoce puede enviar al dispositivo, por eso no se
    exporta ni se registra."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("tenant_id", "endpoint_hash", name="uq_push_subscription_endpoint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160))
    endpoint: Mapped[str] = mapped_column(Text)
    endpoint_hash: Mapped[str] = mapped_column(String(64))
    p256dh: Mapped[str] = mapped_column(String(200))
    auth_secret: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PushPreference(TenantOwnedMixin, Base, TimestampMixin):
    """Opt-in de Web Push por usuario y tipo de evento (como Telegram)."""

    __tablename__ = "push_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "event_type", name="uq_push_preference_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertDelivery(TenantOwnedMixin, Base, TimestampMixin):
    """Outbox de entrega por canal con claim atomico.

    Una fila por (alerta, canal). El claim es un unico UPDATE ... WHERE
    status elegible RETURNING: dos workers no pueden reclamar la misma
    fila a la vez. Un commit fallido tras el envio deja la fila en
    'sending' y un retry inmediato NO la reclama (no hay reenvio); solo
    un claim expirado (> STALE_CLAIM_SECONDS) vuelve a ser elegible.
    Resultados ambiguos ('unknown': timeout/5xx, el proveedor pudo
    entregar) tampoco se reclaman de inmediato; los inequivocos
    ('failed': conexion no establecida o rechazo 4xx) si.
    """

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        UniqueConstraint("alert_id", "channel", name="uq_alert_delivery_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("research_alerts.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class AlertRule(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "name", name="uq_alert_rule_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    rule_type: Mapped[str] = mapped_column(String(80), index=True)
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(40), default="medium")
    channels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["in_app"])
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    last_value: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class TypeSafeStatus(Base):
    """Singleton global para el estado de facturación de JEV."""

    __tablename__ = "typesafe_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_billing_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorState(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "connector_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connector", "company_id", "feed_url", name="uq_connector_state"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connector: Mapped[str] = mapped_column(String(80), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    feed_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class EarningsRun(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "earnings_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_quarter: Mapped[str] = mapped_column(String(10), default="FY")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    document_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    extracted_metrics: Mapped[list[dict]] = mapped_column(JSON, default=list)
    guidance_changes: Mapped[list[dict]] = mapped_column(JSON, default=list)
    comparisons: Mapped[dict] = mapped_column(JSON, default=dict)
    management_tone: Mapped[dict] = mapped_column(JSON, default=dict)
    promise_tracking: Mapped[list[dict]] = mapped_column(JSON, default=list)
    risk_updates: Mapped[list[dict]] = mapped_column(JSON, default=list)
    catalyst_updates: Mapped[list[dict]] = mapped_column(JSON, default=list)
    claim_changes: Mapped[list[dict]] = mapped_column(JSON, default=list)
    thesis_change_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_changes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class MoatAssessment(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "moat_assessments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "moat_type", name="uq_tenant_company_moat_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    moat_type: Mapped[str] = mapped_column(String(80))
    strength: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String(40), default="uncertain")
    persistence: Mapped[str] = mapped_column(String(80), default="unknown")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0"))
    status: Mapped[str] = mapped_column(String(40), default="insufficient_evidence")
    supporting_claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    contradicting_claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    assessment_trace: Mapped[dict] = mapped_column(JSON, default=dict)


class PeerRelationship(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "peer_relationships"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "company_id",
            "peer_company_id",
            name="uq_tenant_company_peer_relationship",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    peer_company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(80), default="automatic")
    rationale: Mapped[list[str]] = mapped_column(JSON, default=list)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    selection_trace: Mapped[dict] = mapped_column(JSON, default=dict)


class RedTeamRun(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "red_team_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    thesis_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="completed")
    score: Mapped[int] = mapped_column(Integer, default=0)
    strongest_bear_case: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list[dict]] = mapped_column(JSON, default=list)
    broken_assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    falsification_tests: Mapped[list[str]] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(120), default="red-team-v1")
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class FundamentalModelVersion(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "fundamental_model_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "version", name="uq_fundamental_model_tenant_version"
        ),
        UniqueConstraint(
            "tenant_id", "company_id", "input_fingerprint", name="uq_fundamental_model_fingerprint"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(160))
    algorithm_version: Mapped[str] = mapped_column(String(160))
    framework_key: Mapped[str] = mapped_column(String(80), index=True)
    horizon_years: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), index=True)
    publishable: Mapped[bool] = mapped_column(Boolean, default=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    forecast_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    market_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    valuation_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    code_commit_sha: Mapped[str] = mapped_column(String(80), default="unknown")
    scenario_probabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    model_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class FundamentalValuationSnapshot(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "fundamental_valuation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "market_snapshot_fingerprint",
            name="uq_fundamental_valuation_market_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("fundamental_model_versions.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    market_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    valuation_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class FundamentalDriver(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "fundamental_drivers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "model_version_id", "driver_key", name="uq_fundamental_driver_version_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("fundamental_model_versions.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    driver_key: Mapped[str] = mapped_column(String(160), index=True)
    driver_type: Mapped[str] = mapped_column(String(40))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit: Mapped[str] = mapped_column(String(40), default="unknown")
    currency: Mapped[str] = mapped_column(String(10), default="N/A")
    time_basis: Mapped[str] = mapped_column(String(40), default="point_in_time")
    geography: Mapped[str] = mapped_column(String(120), default="global")
    segment: Mapped[str] = mapped_column(String(160), default="consolidated")
    period: Mapped[str] = mapped_column(String(40), default="unknown")
    source: Mapped[str] = mapped_column(String(240), default="financial_fact")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    source_fact_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class FundamentalAssumption(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "fundamental_assumptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "scenario",
            "assumption_key",
            name="uq_fundamental_assumption_version_scenario_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("fundamental_model_versions.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    assumption_key: Mapped[str] = mapped_column(String(160), index=True)
    scenario: Mapped[str] = mapped_column(String(40), default="base")
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit: Mapped[str] = mapped_column(String(40), default="decimal")
    source_type: Mapped[str] = mapped_column(String(80))
    basis: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    source_fact_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class FundamentalForecast(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "fundamental_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "scenario",
            "fiscal_year",
            "metric",
            name="uq_fundamental_forecast_point",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("fundamental_model_versions.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    scenario: Mapped[str] = mapped_column(String(40), index=True)
    probability: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[str] = mapped_column(String(160), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(40), default="USD")
    source_fact_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class DecisionJournalEntry(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "decision_journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    thesis_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("fundamental_model_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_date: Mapped[date] = mapped_column(Date, default=date.today)
    decision: Mapped[str] = mapped_column(String(40), index=True)
    rationale: Mapped[str] = mapped_column(Text)
    what_must_be_true: Mapped[list[str]] = mapped_column(JSON, default=list)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    # Operacion real (compra/venta importada de IBKR o manual) que ejecuto esta
    # decision. Opcional: una decision de "vigilar" no tiene operacion. Si se
    # borra la operacion, la entrada del diario se conserva (SET NULL).
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )


class ExpectationReview(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "expectation_reviews"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "forecast_id", name="uq_expectation_review_forecast"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("fundamental_model_versions.id", ondelete="CASCADE"), index=True
    )
    forecast_id: Mapped[int] = mapped_column(ForeignKey("fundamental_forecasts.id"), index=True)
    actual_fact_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actual_metric_id: Mapped[int | None] = mapped_column(
        ForeignKey("calculated_metrics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actual_source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    semantics: Mapped[str] = mapped_column(String(40), default="higher_is_better")
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[str] = mapped_column(String(160), index=True)
    expected_value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    variance: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    variance_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class KnowledgeCollection(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "knowledge_collections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "slug", name="uq_knowledge_collection_tenant_slug"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    slug: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    collection_type: Mapped[str] = mapped_column(String(80), default="custom")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class KnowledgeDocument(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_collections.id"), nullable=True, index=True
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, unique=True
    )
    title: Mapped[str] = mapped_column(String(400))
    author: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="en")
    status: Mapped[str] = mapped_column(String(40), default="ready", index=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Empresa a la que se refiere el documento (opcional, normalizado strip +
    # upper). Lo usa la ficha /research/[ticker] para listar sus lecturas.
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class KnowledgeChunk(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_document_id",
            "chunk_index",
            name="uq_knowledge_chunk_document_index",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class InvestmentPrinciple(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "investment_principles"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id"), index=True
    )
    knowledge_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id"), nullable=True, index=True
    )
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_collections.id"), nullable=True, index=True
    )
    principle: Mapped[str] = mapped_column(Text)
    principle_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    semantic_duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("investment_principles.id"), nullable=True, index=True
    )
    canonical_principle_id: Mapped[int | None] = mapped_column(
        ForeignKey("investment_principles.id"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("investment_principles.id"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(120), index=True)
    application_conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    exceptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    applies_to_company_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    exact_fragment: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str | None] = mapped_column(String(240), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(40), default="proposed", index=True)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ProcessingJob(TenantOwnedMixin, Base, TimestampMixin):
    """Durable status and progress for asynchronous Research OS work."""

    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InvestmentCaseStudy(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "investment_case_studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id"), nullable=True, index=True
    )
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_collections.id"), nullable=True, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(Text, default="")
    lessons: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class DecisionLesson(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "decision_lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("decision_journal_entries.id"), nullable=True, index=True
    )
    expectation_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("expectation_reviews.id"), nullable=True, unique=True, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )
    taxonomy: Mapped[str] = mapped_column(String(120), index=True)
    expectation: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    deviation: Mapped[str] = mapped_column(Text, default="")
    cause: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    lesson: Mapped[str] = mapped_column(Text)
    future_application: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class FactRevision(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "fact_revisions"
    __table_args__ = (
        UniqueConstraint(
            "financial_fact_id",
            "canonical_version",
            name="uq_fact_revision_canonical_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_fact_id: Mapped[int] = mapped_column(
        ForeignKey("financial_facts.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("kpi_extraction_candidates.id"), nullable=True, index=True
    )
    previous_value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    new_value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canonical_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)


class DriverAssumptionVersion(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "driver_assumption_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("fundamental_drivers.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    scenario: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(240))
    user_override: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    rationale: Mapped[str] = mapped_column(Text, default="")
    previous_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_assumption_versions.id"), nullable=True, index=True
    )


class CustomMetricDefinition(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "custom_metric_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "metric_key", "version", name="uq_custom_metric_key_version"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(240))
    formula: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(40), default="decimal")
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class SavedScreen(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "saved_screens"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_saved_screen_tenant_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    criteria: Mapped[list[dict]] = mapped_column(JSON, default=list)
    ranking_formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    ranking_direction: Mapped[str] = mapped_column(String(10), default="desc")
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class SavedScreenMatch(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "saved_screen_matches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "saved_screen_id", "company_id", name="uq_screen_match_company"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    saved_screen_id: Mapped[int] = mapped_column(
        ForeignKey("saved_screens.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    first_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class KnowledgeGraphNode(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "knowledge_graph_nodes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "node_key", name="uq_knowledge_graph_node_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(String(240), index=True)
    node_type: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1"))
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class KnowledgeGraphEdge(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "from_node_id",
            "to_node_id",
            "edge_type",
            name="uq_knowledge_graph_edge",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_graph_nodes.id"), index=True
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_graph_nodes.id"), index=True
    )
    edge_type: Mapped[str] = mapped_column(String(120), index=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1"))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1"))
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    provenance: Mapped[str] = mapped_column(String(160), default="deterministic_sync")
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class ManagementPromise(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "management_promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    call_claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("call_claims.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    promise: Mapped[str] = mapped_column(Text)
    promise_date: Mapped[date] = mapped_column(Date, index=True)
    expected_period: Mapped[str] = mapped_column(String(80), index=True)
    metric: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    operator: Mapped[str | None] = mapped_column(String(10), nullable=True)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_fact_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    management_explanation: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

class TaxReport(TenantOwnedMixin, Base, TimestampMixin):
    """Persisted fiscal-year tax snapshot (IRPF-style) for the private portfolio."""

    __tablename__ = "tax_reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fiscal_year", name="uq_tax_report_tenant_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True, index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    base_currency: Mapped[str] = mapped_column(String(10), default="EUR")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    dividends: Mapped[list[dict]] = mapped_column(JSON, default=list)
    realized: Mapped[list[dict]] = mapped_column(JSON, default=list)
    misc: Mapped[list[dict]] = mapped_column(JSON, default=list)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    portfolio: Mapped["Portfolio | None"] = relationship("Portfolio", back_populates="tax_reports")


class InvestmentPlan(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "investment_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True, index=True
    )
    monthly_contribution: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    # Divisa de la aportacion mensual. NULL = «divisa no registrada» (planes
    # legacy): NUNCA se reinterpreta como divisa base — los totales quedan en
    # estado desconocido explicito hasta que el usuario fija una divisa.
    monthly_contribution_currency: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date)
    horizon_years: Mapped[int] = mapped_column(Integer, default=30)
    target_allocations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)

    portfolio: Mapped["Portfolio | None"] = relationship("Portfolio", back_populates="investment_plans")


class PlanContribution(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "plan_contributions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "plan_id", "external_id", name="uq_plan_contribution_tenant_external"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("investment_plans.id", ondelete="CASCADE"), index=True)
    date: Mapped[_DateT] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(10), default="EUR")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")


class CorporateAction(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    action_type: Mapped[str] = mapped_column(
        String(40), default="split", index=True
    )  # split | reverse_split | merger | spin_off | ticker_change
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    ratio: Mapped[Decimal] = mapped_column(
        Numeric(24, 10), default=1
    )  # shares after / shares before
    description: Mapped[str] = mapped_column(String(500), default="")
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(40), default="manual")
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DividendRecord(TenantOwnedMixin, Base, TimestampMixin):
    """Declared dividend ingested from a labeled data provider.

    Deduped per (company, ex_date, amount). Powers real dividend-yield
    analytics; dividend cash application to the ledger stays manual.
    """

    __tablename__ = "dividend_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "ex_date", "amount", name="uq_dividend_record_tenant"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    ex_date: Mapped[date] = mapped_column(Date, index=True)
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    source: Mapped[str] = mapped_column(String(40), default="fmp")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FundManager(TenantOwnedMixin, Base, TimestampMixin):
    """Reviewed institutional manager tracked via SEC Form 13F (free, official).

    Only managers in the reviewed code table are ingested: exact CIK mapped
    to the official EDGAR name, never guessed.
    """

    __tablename__ = "fund_managers"
    __table_args__ = (UniqueConstraint("tenant_id", "cik", name="uq_fund_manager_tenant_cik"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(200))
    last_report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage: Mapped[str] = mapped_column(String(20), default="ok")
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ManagerHolding(TenantOwnedMixin, Base, TimestampMixin):
    """One 13F information-table row, stored as filed (CUSIP + issuer name).

    Tickers are never inferred. Amendments (13F-HR/A) are separate immutable
    accessions; prior filings are never rewritten. 13F is quarterly with up
    to a 45-day lag and long-only - consumers must show these limits.
    """

    __tablename__ = "manager_holdings"
    __table_args__ = (
        UniqueConstraint(
            "manager_id",
            "accession_number",
            "cusip",
            "title_of_class",
            "put_call",
            name="uq_manager_holding",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("fund_managers.id"), index=True)
    accession_number: Mapped[str] = mapped_column(String(25), index=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    name_of_issuer: Mapped[str] = mapped_column(String(200), default="")
    title_of_class: Mapped[str] = mapped_column(String(150), default="")
    cusip: Mapped[str] = mapped_column(String(9))
    value_usd_thousands: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), nullable=True
    )
    # Escala usada al guardar el valor (heuristica por filing, ver form13f.infer_value_scale):
    # "dollars_raw", "thousands_x1000" o NULL (fila anterior a este campo / periodo legacy).
    value_scale: Mapped[str | None] = mapped_column(String(24), nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    share_type: Mapped[str] = mapped_column(String(10), default="SH")
    put_call: Mapped[str] = mapped_column(String(10), default="")
    investment_discretion: Mapped[str] = mapped_column(String(10), default="")
    voting_sole: Mapped[Decimal | None] = mapped_column(Numeric(24, 0), nullable=True)
    voting_shared: Mapped[Decimal | None] = mapped_column(Numeric(24, 0), nullable=True)
    voting_none: Mapped[Decimal | None] = mapped_column(Numeric(24, 0), nullable=True)
    filing_url: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(40), default="sec_edgar_13f")
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkflowRun(TenantOwnedMixin, Base, TimestampMixin):
    """Uniform execution envelope for every workflow run.

    One row per run attempt, whatever the underlying runtime (deterministic
    runner, MAF graph, or direct service call). Records the state machine
    (queued/running/succeeded/failed), the idempotency key, and the final
    result or classified error. Steps live in workflow_step_runs.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workflow_name", "idempotency_key",
            name="uq_workflow_runs_idempotency",
        ),
        Index("ix_workflow_runs_name_status", "workflow_name", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(120))
    execution_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["WorkflowStepRun"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="WorkflowStepRun.position",
    )


class WorkflowStepRun(TenantOwnedMixin, Base, TimestampMixin):
    """One executed step inside a workflow run."""

    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "position", "attempt", name="uq_workflow_step_runs_position_attempt"
        ),
        Index("ix_workflow_step_runs_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    step_name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="running")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["WorkflowRun"] = relationship(back_populates="steps")


class ProPickRun(TenantOwnedMixin, Base, TimestampMixin):
    """One execution of the ProPicks deterministic funnel (big-data stage).

    Persists the full parameter set so every candidate row is reproducible
    and runs can be diffed (in/out) for the rebalance digest.
    """

    __tablename__ = "propick_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed", index=True)
    funnel_version: Mapped[str] = mapped_column(String(80))
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    top_n: Mapped[int] = mapped_column(Integer, default=20)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidates: Mapped[list["ProPickCandidate"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ProPickCandidate(TenantOwnedMixin, Base, TimestampMixin):
    """Per-company funnel outcome for one run (pass and fail rows both kept:
    the failed gates are product information, not noise)."""

    __tablename__ = "propick_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "company_id", name="uq_propick_candidates_run_company"),
        Index("ix_propick_candidates_run_score", "run_id", "score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("propick_runs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    passed: Mapped[bool] = mapped_column(default=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    failed_gates: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped["ProPickRun"] = relationship(back_populates="candidates")


class InferredInput(TenantOwnedMixin, Base, TimestampMixin):
    """Input INFERIDO: estimacion con base explicita y URLs web.

    Nunca es un fact ni un dato oficial. El motor solo lo usa si trae base y al
    menos una URL https; lo validan el servicio y el motor.

    Estimacion privada del tenant creador. Una empresa sigue siendo global,
    pero sus inferencias no se comparten. Filas legacy sin autor se conservan
    para recuperacion auditada y no son visibles en sesiones normales.
    """

    __tablename__ = "inferred_inputs"
    __table_args__ = (
        Index("ix_inferred_inputs_company_key", "company_id", "input_key"),
        Index("ix_inferred_inputs_tenant_company_key", "tenant_id", "company_id", "input_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    input_key: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(40), default="decimal")
    base: Mapped[str] = mapped_column(Text)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(20), default="llm")


class InstrumentReference(Base, TimestampMixin):
    """Referencia normalizada de instrumentos (ticker/FIGI/ISIN/sector).

    Seed idempotente desde FinanceDatabase (CSV comunitario, MIT) con
    normalizacion opcional via OpenFIGI. El resolver la consulta primero;
    si no hay fila, el fallback de sufijos funciona exacto igual que hoy.

    Honestidad: si FinanceDatabase no trae un campo, la columna es NULL
    (fuente sin dato), nunca "Unknown" ni cadena vacia. NULL significa
    "la fuente no lo declara"; los consumidores deben tratarlo como
    desconocido con motivo explicito, no inventar un sector.

    Unicidad: UNIQUE(ticker_normalized). FIGI/ISIN/composite llevan indices
    NO unicos a proposito: un FIGI agrupa varios venues (FIGIs distintos
    por bolsa comparten compositeFIGI) y un renombre por corporate action
    conserva el FIGI (fila vieja + fila nueva con el mismo FIGI). Un
    UNIQUE(figi) rechazaria justo el historial de renombres que esta tabla
    existe para soportar; la identidad estable se resuelve por igualdad de
    FIGI, no por unicidad.
    """

    __tablename__ = "instrument_references"
    __table_args__ = (
        UniqueConstraint("ticker_normalized", name="uq_instrument_ref_ticker"),
        Index("ix_instrument_ref_ticker", "ticker_normalized"),
        Index("ix_instrument_ref_figi", "figi"),
        Index("ix_instrument_ref_composite_figi", "composite_figi"),
        Index("ix_instrument_ref_isin", "isin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker_normalized: Mapped[str] = mapped_column(String(40))
    figi: Mapped[str | None] = mapped_column(String(12), nullable=True)
    composite_figi: Mapped[str | None] = mapped_column(String(12), nullable=True)
    shareclass_figi: Mapped[str | None] = mapped_column(String(12), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    cusip: Mapped[str | None] = mapped_column(String(9), nullable=True)
    sedol: Mapped[str | None] = mapped_column(String(7), nullable=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mic: Mapped[str | None] = mapped_column(String(4), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    as_of: Mapped[_DateT] = mapped_column(Date, default=date.today)
    source: Mapped[str] = mapped_column(String(80), default="financedatabase")


class InvestorPosition(TenantOwnedMixin, Base, TimestampMixin):
    """Posicion de un inversor publico con fuente y fecha (no 13F: 13D, Form 3/4...).

    Cada dato lleva etiqueta OFICIAL / INFERIDO / SIN DATOS y su fecha. Los
    campos sin fuente quedan en NULL (= SIN DATOS); nunca se rellenan.
    """

    __tablename__ = "investor_positions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "investor_slug", "issuer_cik", "security_title", "as_of",
            name="uq_investor_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investor_slug: Mapped[str] = mapped_column(String(60), index=True)
    issuer_name: Mapped[str] = mapped_column(String(200))
    issuer_cik: Mapped[str] = mapped_column(String(10), default="")
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    security_title: Mapped[str] = mapped_column(String(150), default="")
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    value_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    label: Mapped[str] = mapped_column(String(12), default="OFICIAL")
    value_label: Mapped[str] = mapped_column(String(12), default="SIN_DATOS")
    as_of: Mapped[date] = mapped_column(Date)
    source_form: Mapped[str] = mapped_column(String(20), default="")
    accession_number: Mapped[str] = mapped_column(String(25), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class InvestorMovement(TenantOwnedMixin, Base, TimestampMixin):
    """Movimiento declarado (Form 4 / Form 3 / 13D) de un inversor publico."""

    __tablename__ = "investor_movements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "investor_slug", "accession_number", "line_no",
            name="uq_investor_movement",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investor_slug: Mapped[str] = mapped_column(String(60), index=True)
    accession_number: Mapped[str] = mapped_column(String(25))
    line_no: Mapped[int] = mapped_column(default=0)
    issuer_name: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    movement_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    action: Mapped[str] = mapped_column(String(20), default="otro")
    transaction_code: Mapped[str] = mapped_column(String(4), default="")
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    shares_after: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    label: Mapped[str] = mapped_column(String(12), default="OFICIAL")
    source_form: Mapped[str] = mapped_column(String(20), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class EtfHolding(Base):
    """Posicion de un ETF tematico segun el fichero oficial de holdings del
    emisor (global, no por tenant). Solo tickers de renta variable con peso y
    fecha de corte (as_of) publicados por el emisor; nada inferido."""

    __tablename__ = "etf_holdings"
    __table_args__ = (UniqueConstraint("etf", "ticker", name="uq_etf_holding"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    etf: Mapped[str] = mapped_column(String(12), index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    as_of: Mapped[_DateT] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(Text)


class TenantLLMSettings(TenantOwnedMixin, Base, TimestampMixin):
    """Proveedor/modelo/clave LLM propios de un tenant.

    ``tenant_id`` es unico: una fila por tenant, borrada en cascada con el
    tenant. La clave NUNCA se guarda en claro: solo el sobre cifrado y los
    ultimos cuatro caracteres para poder mostrarla en ajustes.

    Hereda ``TenantOwnedMixin``: la sesion filtra las SELECT de entidad por
    tenant, asigna el tenant a las filas nuevas y rechaza reasignarlo. La
    columna ``tenant_id`` se redeclara aqui (NOT NULL + ON DELETE CASCADE),
    por lo que el esquema de la migracion 0081 no cambia.
    """

    __tablename__ = "tenant_llm_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_llm_settings_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), default="opencode-go")
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model: Mapped[str] = mapped_column(String(200), default="deepseek-v4.1-flash")
    fallback_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(20), nullable=True)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PrivacyAuditEvent(Base):
    """Auditoria de operaciones de privacidad que debe sobrevivir al borrado.

    No es tenant-owned a proposito: el evento de ``account.delete`` tiene que
    seguir existiendo despues de eliminar la fila de ``tenants``. Solo guarda
    identificadores externos (nunca email, documentos ni contenido) y un
    detalle agregado sin datos personales.
    """

    __tablename__ = "privacy_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    tenant_external_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
