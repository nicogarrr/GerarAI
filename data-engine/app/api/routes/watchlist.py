from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.tenancy import tenant_filters
from app.models import (
    Company,
    DcaAlertOverride,
    DcaSignalState,
    EarningsDate,
    FinancialFact,
    MarketPrice,
    WatchItem,
)
from app.services.connectors.earnings_calendar import fetch_earnings_range
from app.services.derived_market_cap_service import DERIVED_SOURCE
from app.services.earnings_dates_service import is_fresh
from app.services.fair_value_service import resolve_fair_values
from app.services.fundamentals_seed_service import enqueue_fundamentals_seed
from app.services.tracked_analysis import enqueue_tracked_analysis, tracked_statuses

router = APIRouter()


class WatchItemCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")
    company: str | None = Field(default=None, max_length=255)


def _payload(item: WatchItem) -> dict:
    return {
        "id": item.id,
        "symbol": item.symbol,
        "company": item.company,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _find_watch_item(db: Session, symbol: str) -> WatchItem | None:
    """Fila del tenant activo para ``symbol`` (ya normalizado en mayúsculas)."""
    return db.scalar(select(WatchItem).where(WatchItem.symbol == symbol))


@router.get("")
def list_watchlist(db: Session = Depends(get_db)) -> list[dict]:
    """Watch items of the active tenant, most recently added first.

    Tenant scoping is applied implicitly by the session (see database.py):
    rows are only visible when their tenant_id matches the signed identity.
    """
    # Desempate por id: altas en el mismo instante (importaciones, dos
    # pestañas) no deben bailar entre páginas de un refresco a otro.
    items = db.scalars(
        select(WatchItem).order_by(desc(WatchItem.created_at), desc(WatchItem.id))
    ).all()
    states = tracked_statuses(db, [item.symbol for item in items])
    return [{**_payload(item), "analysis": states.get(item.symbol)} for item in items]


@router.post("", status_code=201)
def upsert_watch_item(
    payload: WatchItemCreate, db: Session = Depends(get_db)
) -> dict:
    """Add a symbol to the watchlist, or update its label if it exists."""
    symbol = payload.symbol.strip().upper()
    item = _find_watch_item(db, symbol)
    created = item is None
    if item is None:
        item = WatchItem(symbol=symbol, company=payload.company)
        db.add(item)
    elif payload.company is not None:
        item.company = payload.company
    try:
        db.commit()
    except IntegrityError:
        # Doble clic o dos pestañas: otra petición dio de alta el mismo
        # símbolo entre la lectura y el commit. La restricción única
        # (tenant, símbolo) lo para; respondemos con la fila existente en
        # vez de un 500.
        db.rollback()
        item = _find_watch_item(db, symbol)
        if item is None:
            raise
        created = False
        if payload.company is not None and item.company != payload.company:
            item.company = payload.company
            db.commit()
    db.refresh(item)
    if created:
        try:
            enqueue_tracked_analysis(db, symbol)
        except Exception:
            db.rollback()  # Following succeeds even if the analysis outbox fails.
        # Los hechos son por tenant: siembra automatica para que la ficha no
        # salga vacia hasta pulsar «Refrescar SEC» (hallazgo del tester).
        enqueue_fundamentals_seed(db, symbol)
    return _payload(item)


@router.delete("/{symbol}", status_code=204)
def delete_watch_item(symbol: str, db: Session = Depends(get_db)) -> None:
    item = _find_watch_item(db, symbol.strip().upper())
    if item is None:
        raise HTTPException(status_code=404, detail="Ese ticker no está en tu watchlist")
    db.delete(item)
    db.commit()

@router.get("/monitor")
async def watchlist_monitor(
    tickers: str = Query(..., description="CSV de tickers, max 60"),
    db: Session = Depends(get_db),
) -> dict:
    """Datos densos por ticker para el monitor de watchlist.

    Solo datos propios o de fuentes publicas con trazabilidad: minimo de 52
    semanas desde ``market_prices`` (ingesta propia), proximo resultado desde
    el conector publico de NASDAQ (misma fuente que /api/calendar/earnings) y
    comparacion con el valor justo UNICO (``fair_value_service``: tesis
    publicada o motor, con su procedencia en ``fair_value_source``/``_label``).
    Cualquier pieza sin dato va a ``None``; nunca se inventa.
    """
    wanted = list(dict.fromkeys(t.strip().upper() for t in tickers.split(",") if t.strip()))[:60]
    today = date.today()
    cutoff = today - timedelta(days=365)

    companies = db.scalars(select(Company).where(Company.ticker.in_(wanted))).all()
    company_ids = [company.id for company in companies]
    valid_price = (MarketPrice.company_id.in_(company_ids),
                   MarketPrice.close.isnot(None), MarketPrice.close > 0)
    # Constant query count: do not fetch one year's session IDs per company.
    counts = dict(db.execute(
        select(MarketPrice.company_id, func.count(MarketPrice.id))
        .where(*valid_price, MarketPrice.date >= cutoff)
        .group_by(MarketPrice.company_id)
    ).all())

    def ranked_prices(order, *, recent=False):
        ranked = select(
            MarketPrice.id,
            func.row_number().over(partition_by=MarketPrice.company_id, order_by=order).label("rank"),
        ).where(*valid_price)
        if recent:
            ranked = ranked.where(MarketPrice.date >= cutoff)
        ranked = ranked.subquery()
        return {row.company_id: row for row in db.scalars(
            select(MarketPrice).join(ranked, MarketPrice.id == ranked.c.id)
            .where(ranked.c.rank == 1)
        ).all()}

    lows = ranked_prices(MarketPrice.close.asc(), recent=True)
    closes = ranked_prices(MarketPrice.date.desc())
    # Valor justo ÚNICO (tesis o motor, misma precedencia que inicio y screener).
    fair_values = resolve_fair_values(db, companies)
    items: dict[str, dict] = {}
    for company in companies:
        ticker = str(company.ticker).upper()
        low_row = lows.get(company.id)
        last_close = closes.get(company.id)
        reading = fair_values[company.id]
        fair_value = reading["value"]
        price = float(last_close.close) if last_close is not None else None
        side = None
        if fair_value is not None and price is not None and fair_value > 0:
            side = "infravalorada" if price < fair_value else "sobrevalorada"
        items[ticker] = {
            "low_52w": float(low_row.close) if low_row is not None else None,
            "low_52w_date": low_row.date.isoformat() if low_row is not None else None,
            "low_52w_sessions": counts.get(company.id, 0),
            "last_close": price,
            "last_close_date": last_close.date.isoformat() if last_close is not None else None,
            "fair_value": fair_value,
            "fair_value_thesis_version": reading["thesis_version"],
            "fair_value_source": reading["source"],
            "fair_value_label": reading["label"],
            "fair_value_as_of": reading["as_of"],
            "fair_value_publishable": reading["publishable"],
            "valuation_side": side,
            "currency": company.currency,
            "next_earnings_date": None,
            "next_earnings_source": None,
            "next_earnings_confirmed": None,
        }

    # Proximos resultados (NASDAQ publico, mismo conector que /api/calendar).
    earnings_status = "skipped"
    # Primero la tabla de fechas refrescada (Yahoo/NASDAQ/manual): cubre tambien
    # lineas no US y lleva la fuente y si esta confirmada.
    stored = db.execute(
        select(EarningsDate)
        .where(EarningsDate.ticker.in_(list(items) or [""]), EarningsDate.event_date >= today)
        .order_by(EarningsDate.event_date)
    ).scalars().all()
    for row in stored:
        target = items.get(row.ticker)
        if not is_fresh(row):
            continue  # fecha automatica sin renovar: no se muestra
        if target is not None and target["next_earnings_date"] is None:
            target["next_earnings_date"] = row.event_date.isoformat()
            target["next_earnings_source"] = row.source_label
            target["next_earnings_confirmed"] = row.confirmed
    us_wanted = [t for t, v in items.items() if v["next_earnings_date"] is None]
    if us_wanted:
        try:
            # El conector rechaza rangos de mas de 31 dias inclusive: hoy+31
            # son 32 y el ValueError se tragaba como "unavailable" siempre.
            result = await fetch_earnings_range(today, today + timedelta(days=30))
            earnings_status = str(result.get("status", "unavailable"))
            for event in result.get("events", []):
                symbol = str(event.get("symbol") or "").upper()
                day = str(event.get("date") or "")
                row = items.get(symbol)
                if row is not None and day and row["next_earnings_date"] is None:
                    row["next_earnings_date"] = day
                    row["next_earnings_source"] = "NASDAQ (api.nasdaq.com)"
        except Exception:
            earnings_status = "unavailable"

    return {"items": items, "earnings_status": earnings_status}


@router.get("/metrics/{symbol}")
def watchlist_metrics(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Market cap y PER de respaldo para emisoras sin cobertura del
    proveedor US (QA AENA/ASML): market_cap del proveedor o derivado
    (precio x acciones, servicio derived_market_cap) y PER = ultimo cierre
    / EPS diluido del ultimo ejercicio anual. Nulo honesto cuando no hay
    base: nunca se fabrica el numero.
    """
    from datetime import date, timedelta

    company = db.scalar(select(Company).where(Company.ticker == symbol.upper()))
    if company is None:
        return {"market_cap": None, "per": None, "currency": None, "sources": []}

    today = date.today()
    sources: list[str] = []

    def _cap_row() -> FinancialFact | None:
        return db.execute(
            select(FinancialFact)
            .where(FinancialFact.company_id == company.id,
                   FinancialFact.metric == "market_cap")
            .order_by(desc(FinancialFact.is_reported), desc(FinancialFact.period))
            .limit(1)
        ).scalar_one_or_none()

    cap_row = _cap_row()
    if cap_row is None or (
        # Un derivado es un respaldo calculado, no un dato: se REFRESCA en
        # cada lectura (revisión auditor 19-oct-2026: un derivado antiguo
        # erróneo - cap de AENA 10x bajo por split - se serviría
        # indefinidamente). Es idempotente y nunca pisa un cap de proveedor.
        not cap_row.is_reported
        and cap_row.source_type == DERIVED_SOURCE
    ):
        # Respaldo bajo demanda (QA Tester 6, 19-oct-2026: AENA/CGEO.L con
        # cap N/D en la watchlist porque el barrido de métricas aún no lo
        # había derivado): precio x acciones, idempotente. Sin base (sin
        # precio fresco o sin acciones) no escribe nada: None honesto.
        from app.services.derived_market_cap_service import (
            refresh_derived_market_cap,
        )
        refresh_derived_market_cap(db, company)
        # get_db cierra TODA request con rollback (database.py): sin commit
        # el derivado recalculado no se persistiría jamás y cada lectura
        # re-derivaría lo mismo. Si el commit falla, rollback y se sirve el
        # estado anterior (None o el derivado viejo): degradación honesta.
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        cap_row = _cap_row()
    market_cap = float(cap_row.value) if cap_row is not None else None
    if cap_row is not None:
        sources.append(
            f"Capitalización: {cap_row.source_type}"
            + ("" if cap_row.is_reported else " (derivada: precio x acciones)")
            + (" · acciones ajustadas por split"
               if not cap_row.is_reported and cap_row.is_adjusted else ""))

    price_row = db.execute(
        select(MarketPrice)
        .where(MarketPrice.company_id == company.id,
               MarketPrice.date >= today - timedelta(days=7),
               MarketPrice.close.isnot(None), MarketPrice.close > 0)
        .order_by(desc(MarketPrice.date)).limit(1)
    ).scalar_one_or_none()
    eps_row = db.execute(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id,
               FinancialFact.metric.in_(["eps_diluted", "eps_basic"]),
               FinancialFact.fiscal_quarter == "FY",
               FinancialFact.value > 0)
        .order_by(desc(FinancialFact.fiscal_year)).limit(1)
    ).scalar_one_or_none()
    per = None
    if price_row is not None and eps_row is not None:
        # Divisa del EPS vs divisa del listado: el cierre almacenado es el
        # del listado de la Company (market_close_sync pide yahoo_symbol), y
        # mezclar un EPS en EUR con un cierre en USD fabrica el ratio (caso
        # real: PER de ASML 56x por cruzar ADR USD con EPS ESEF EUR). Misma
        # regla que el screener (_unit_currency): sin coincidencia, N/D.
        from app.services.screener_fundamentals import _unit_currency
        from app.services.split_adjustment import (
            cumulative_split_factor_after,
            period_end_date,
            split_events_by_company,
        )

        eps_ccy = _unit_currency(eps_row.unit)
        list_ccy = (company.currency or "").upper()
        if eps_ccy and list_ccy and eps_ccy != list_ccy:
            sources.append(
                f"PER: N/D: EPS {eps_row.metric} FY{eps_row.fiscal_year} en "
                f"{eps_ccy} y cierre del listado en {list_ccy}: mezclar "
                "divisas fabrica el ratio")
            return {"market_cap": market_cap, "per": None,
                    "currency": company.currency, "sources": sources}

        # El cierre es de hoy: EPS en acciones actuales o el PER sale
        # inflado por el factor de cualquier split posterior al ejercicio.
        split_factor = cumulative_split_factor_after(
            split_events_by_company(db, [company.id]).get(company.id, []),
            period_end_date(eps_row.period),
        )
        # Cierre cotizado en otra divisa que las cuentas (SHEL.L en GBp con
        # EPS en USD): FX point-in-time a la divisa de la compania; sin tipo,
        # PER N/D (nunca peniques divididos por un EPS en dolares).
        from decimal import Decimal

        from app.services.price_units import close_in_company_currency

        close = close_in_company_currency(
            db, Decimal(str(price_row.close)), quote_currency=price_row.quote_currency,
            company=company, on=price_row.date,
        )
        if close is None:
            sources.append(
                f"PER: N/D: cierre en {price_row.quote_currency} sin tipo de cambio "
                f"a {company.currency} para {price_row.date.isoformat()}")
            return {"market_cap": market_cap, "per": None,
                    "currency": company.currency, "sources": sources}
        per = float(close) / (float(eps_row.value) / float(split_factor))
        source = (f"PER: cierre {price_row.date.isoformat()} / "
                  f"{eps_row.metric} FY{eps_row.fiscal_year} ({eps_row.source_type})")
        if split_factor != 1:
            source += (", EPS ajustado por split acumulado x"
                  f"{format(split_factor.normalize(), "f")}")
        sources.append(source)

    return {"market_cap": market_cap, "per": per,
            "currency": company.currency, "sources": sources}


# --- Senales DCA por niveles (watchlist + cartera) -------------------------



class DcaZoneOut(BaseModel):
    level: int
    key: str
    label: str
    zone: str
    color: str
    fg: str


class DcaSignalStateOut(BaseModel):
    level: int
    previous_level: int | None = None
    key: str
    label: str
    zone: str
    color: str
    fg: str
    status: str
    period: str
    signal_date: date
    close: float
    currency: str | None = None
    currency_label: str | None = None
    metrics: dict[str, float | str | int | None] = Field(default_factory=dict)
    level_prices: dict[str, float | None] = Field(default_factory=dict)
    params_version: str
    data_source: str
    evaluated_at: datetime
    last_alerted_level: int | None = None
    last_alerted_period: str | None = None
    # Dias desde el ultimo cierre usado. Si supera DCA_MAX_DATA_AGE_DAYS el
    # nivel guardado ya no es actual (la evaluacion lo omite por datos viejos).
    data_age_days: int | None = None
    stale: bool = False


class DcaHitRateCellOut(BaseModel):
    horizon_months: int
    months: int
    pct_higher: float | None = None
    avg_return: float | None = None


class DcaHitRateRowOut(BaseModel):
    key: str
    label: str
    levels: list[int]
    signal_months: int
    color: str | None = None
    cells: list[DcaHitRateCellOut]


class DcaHitRatesOut(BaseModel):
    symbol: str
    available: bool
    reason: str | None = None
    months_completed: int = 0
    first_period: str | None = None
    last_period: str | None = None
    horizons: list[int] = Field(default_factory=list)
    params_version: str | None = None
    evaluated_at: datetime | None = None
    rows: list[DcaHitRateRowOut] = Field(default_factory=list)
    disclaimer: str = "Histórico, hipotético. No es asesoramiento."


class DcaBacktestPlanOut(BaseModel):
    key: str
    label: str
    invested: float
    deployed: float
    cash_left: float
    shares: float
    avg_cost: float | None = None
    final_value: float
    multiple: float | None = None
    irr: float | None = None
    max_drawdown: float
    worst_unrealized: float
    buys: int
    irr_vs_plain: float | None = None
    value_vs_plain: float | None = None
    shares_per_money_vs_plain: float | None = None


class DcaBacktestLevelOut(BaseModel):
    level: int
    label: str
    color: str
    months: int


class DcaBacktestOut(BaseModel):
    symbol: str
    available: bool
    reason: str | None = None
    params_version: str | None = None
    currency: str | None = None
    currency_label: str | None = None
    data_source: str | None = None
    first_signal: str | None = None
    last_signal: str | None = None
    first_buy: date | None = None
    last_buy: date | None = None
    valued_at_period: str | None = None
    final_price: float | None = None
    months: int = 0
    base_amount: float = 100.0
    plans: list[DcaBacktestPlanOut] = Field(default_factory=list)
    levels: list[DcaBacktestLevelOut] = Field(default_factory=list)
    hit_rates: DcaHitRatesOut | None = None
    disclaimer: str = "Histórico, hipotético. No es asesoramiento."


class DcaSignalItemOut(BaseModel):
    symbol: str
    company_name: str | None = None
    sources: list[str]
    in_watchlist: bool
    in_portfolio: bool
    min_level_override: int | None = None
    effective_min_level: int
    alerts_on: bool
    state: DcaSignalStateOut | None = None
    # Por que no hay nivel: never_run | job_failed | skipped (con motivo).
    evaluation_status: str = "never_run"
    evaluation_reason: str | None = None


class DcaRunOut(BaseModel):
    status: str  # ok | error | running | interrupted
    trigger: str  # scheduler | manual
    started_at: datetime
    finished_at: datetime | None = None
    tracked: int
    evaluated: int
    skipped: int
    errors: int
    alerted: int
    error: str | None = None
    skipped_detail: list[dict] = Field(default_factory=list)
    errors_detail: list[dict] = Field(default_factory=list)


class DcaSignalsOut(BaseModel):
    alerts_enabled: bool
    # False = la evaluacion diaria (DCA_EVALUATION_ENABLED) esta apagada en el
    # servidor: ningun ticker tendra nivel salvo con «Evaluar ahora».
    evaluation_enabled: bool = True
    global_min_level: int
    directional_policy: bool = False
    up_min_level: int | None = None
    down_max_level: int | None = None
    trims_enabled: bool
    channels: list[str]
    email_configured: bool
    signal_months: int | None = None
    zones: list[DcaZoneOut]
    items: list[DcaSignalItemOut]
    # Ultima ejecucion de la evaluacion; null = nunca se ha ejecutado.
    last_run: DcaRunOut | None = None


class DcaMinLevelIn(BaseModel):
    # null = usar el global; 0 = avisos apagados para este ticker; 1-4 = minimo.
    min_level: int | None = Field(default=None, ge=0, le=4)


class DcaMinLevelOut(BaseModel):
    symbol: str
    min_level_override: int | None
    effective_min_level: int


class DcaEvaluateOut(BaseModel):
    tracked: int
    evaluated: int
    alerted: list[dict]
    skipped: list[dict]
    errors: list[dict]
    alerts_enabled: bool
    params_version: str
    requested: int = 0
    pending_remaining: int = 0
    cooldown_seconds: int = 300


def _dca_staleness(signal_date: date | None, today: date | None = None) -> tuple[int | None, bool]:
    """(dias desde el ultimo cierre, desactualizado) con el mismo limite que el job."""
    from zoneinfo import ZoneInfo

    from app.core.config import get_settings

    if signal_date is None:
        return None, False
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    age = max((today - signal_date).days, 0)
    return age, age > int(get_settings().dca_max_data_age_days)


def _dca_state_payload(state: DcaSignalState, *, today: date | None = None) -> dict:
    from app.services.dca_alert_copy import currency_label
    from app.services.dca_signal_engine import ZONES

    zone = ZONES.get(state.level, ZONES[1])
    data_age_days, stale = _dca_staleness(state.signal_date, today)
    return {
        "level": state.level,
        "previous_level": state.previous_level,
        "key": zone["key"],
        "label": zone["label"],
        "zone": zone["zone"],
        "color": zone["color"],
        "fg": zone["fg"],
        "status": state.status,
        "period": state.period,
        "signal_date": state.signal_date,
        "close": float(state.close),
        "currency": state.currency,
        "currency_label": currency_label(state.currency),
        "metrics": state.metrics or {},
        "level_prices": state.level_prices or {},
        "params_version": state.params_version,
        "data_source": state.data_source,
        "evaluated_at": state.evaluated_at,
        "last_alerted_level": state.last_alerted_level,
        "last_alerted_period": state.last_alerted_period,
        "data_age_days": data_age_days,
        "stale": stale,
    }


@router.get("/dca-signals", response_model=DcaSignalsOut)
def list_dca_signals(db: Session = Depends(get_db)) -> dict:
    """Nivel DCA actual de cada ticker de watchlist + cartera y su minimo de aviso."""
    from app.core.config import get_settings
    from app.services import dca_signal_service as dca
    from app.services.dca_signal_engine import DEFAULT_PARAMS, ZONES
    from app.services.email_delivery import smtp_configured

    settings = get_settings()
    tracked = dca.tracked_symbols(db)
    per_ticker = dca.overrides(db)
    from app.services.dca_alert_settings_service import effective_policy
    policy = effective_policy(db)
    states = {
        row.symbol.upper(): row
        for row in db.scalars(select(DcaSignalState).where(*tenant_filters(db, DcaSignalState)))
    }
    from app.services import dca_run_log

    run = dca_run_log.run_payload(dca_run_log.latest_run(db))
    items = []
    for symbol, item in tracked.items():
        override = per_ticker.get(symbol)
        effective = policy.up_min_level if policy else dca.effective_min_level(override, settings)
        state = states.get(symbol)
        items.append({
            "symbol": symbol,
            "company_name": item.company.name if item.company is not None else None,
            "sources": item.sources,
            "in_watchlist": "watchlist" in item.sources,
            "in_portfolio": "portfolio" in item.sources,
            "min_level_override": override,
            "effective_min_level": effective,
            "alerts_on": bool(settings.dca_alerts_enabled) and (effective > 0 or (policy is not None and policy.down_max_level > 0)),
            "state": _dca_state_payload(state) if state is not None else None,
            "evaluation_status": (ev := dca_run_log.item_evaluation(symbol, state is not None, run))["status"],
            "evaluation_reason": ev["reason"],
        })
    return {
        "alerts_enabled": bool(settings.dca_alerts_enabled),
        "evaluation_enabled": bool(settings.dca_evaluation_enabled),
        "global_min_level": policy.up_min_level if policy else int(settings.dca_alert_min_level),
        "directional_policy": policy is not None,
        "up_min_level": policy.up_min_level if policy else None,
        "down_max_level": policy.down_max_level if policy else None,
        "trims_enabled": bool(settings.dca_alert_trims),
        "channels": dca.alert_channels(settings),
        "email_configured": smtp_configured(settings),
        "signal_months": getattr(DEFAULT_PARAMS, "sma_months", None),
        "zones": [{"level": level, **zone} for level, zone in ZONES.items()],
        "items": items,
        "last_run": run,
    }


@router.put("/{symbol}/dca-alert-min-level", response_model=DcaMinLevelOut)
def set_dca_alert_min_level(symbol: str, payload: DcaMinLevelIn, db: Session = Depends(get_db)) -> dict:
    """Ajusta el nivel minimo de aviso DCA de un ticker (null = global, 0 = apagado)."""
    from app.core.config import get_settings
    from app.services import dca_signal_service as dca

    from app.services.dca_alert_settings_service import effective_policy
    policy = effective_policy(db)
    key = symbol.strip().upper()
    if key not in dca.tracked_symbols(db):
        raise HTTPException(status_code=404, detail="El ticker no está en tu watchlist ni en tu cartera")
    row = db.scalar(
        select(DcaAlertOverride).where(DcaAlertOverride.symbol == key, *tenant_filters(db, DcaAlertOverride))
    )
    if payload.min_level is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(DcaAlertOverride(tenant_id=db.info.get("tenant_id"), symbol=key, min_level=payload.min_level))
    else:
        row.min_level = payload.min_level
    db.commit()
    return {
        "symbol": key,
        "min_level_override": payload.min_level,
        "effective_min_level": (policy.up_min_level if policy else dca.effective_min_level(payload.min_level, get_settings())),
    }


class DcaAcceptedOut(BaseModel):
    run_id: int
    status: str = "running"
    requested: int
    pending_remaining: int
    cooldown_seconds: int = 300


class DcaManualStatusOut(BaseModel):
    run_id: int
    status: str
    summary: DcaEvaluateOut | None = None
    error: str | None = None


@router.post("/dca-signals/evaluate-async", status_code=202, response_model=DcaAcceptedOut)
def enqueue_manual_dca(db: Session = Depends(get_db)) -> dict:
    import redis

    from app.models import DcaEvaluationRun
    from app.services import dca_manual, dca_manual_job, dca_run_log
    from app.workers.dramatiq_app import evaluate_manual_dca
    tenant_id, user_id = db.info.get("tenant_id"), db.info.get("user_id")
    if tenant_id is None or not user_id:
        raise HTTPException(status_code=401, detail="Se requiere identidad de cuenta para ejecutar en segundo plano.")
    client = dca_manual_job.redis_client()
    token = None
    row = None
    sent = False
    enqueue_attempted = False
    try:
        try:
            token, wait = dca_manual.acquire_manual_gate(client, str(tenant_id))
        except redis.RedisError as exc:
            raise HTTPException(status_code=503, detail="No se puede asegurar una ejecución única ahora.") from exc
        if token is None:
            if wait == -1:
                raise HTTPException(status_code=409, detail="Ya hay una evaluación DCA en curso en tu cuenta.")
            raise HTTPException(status_code=429, detail=f"Espera {wait} s antes de otra tanda.", headers={"Retry-After": str(wait)})
        pending = dca_manual.pending_symbols(db)
        requested = pending[:dca_manual.MAX_SYMBOLS]
        remaining = max(0, len(pending) - len(requested))
        # Unlike best-effort historical logs, this receipt is REQUIRED before enqueue.
        row = DcaEvaluationRun(tenant_id=tenant_id, trigger="manual", status="queued",
            started_at=datetime.now(UTC), detail={"requested_symbols": requested, "pending_remaining": remaining})
        db.add(row)
        db.commit()
        # A transport error can occur after broker acceptance. Keep the lease
        # on ambiguous delivery so a possibly running worker never overlaps.
        enqueue_attempted = True
        evaluate_manual_dca.send(row.id, token, tenant_id, user_id)
        sent = True
        return {"run_id": row.id, "requested": len(requested), "pending_remaining": remaining}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        if row is not None:
            dca_run_log.finish_run(db, row, error="No se pudo confirmar el envío al worker.")
        raise HTTPException(status_code=503, detail="No se pudo confirmar la ejecución; revisa su estado antes de repetir.") from exc
    finally:
        try:
            if token is not None and not sent and not enqueue_attempted:
                dca_manual.release_manual_gate(client, str(tenant_id), token)
        finally:
            client.close()


@router.get("/dca-signals/manual-runs/{run_id}", response_model=DcaManualStatusOut)
def manual_dca_status(run_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models import DcaEvaluationRun
    from app.services.dca_run_log import run_payload
    row = db.scalar(select(DcaEvaluationRun).where(DcaEvaluationRun.id == run_id,
        DcaEvaluationRun.trigger == "manual", *tenant_filters(db, DcaEvaluationRun)))
    if row is None:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada en tu cuenta.")
    payload = run_payload(row) or {}
    return {"run_id": row.id, "status": "running" if row.status == "queued" and datetime.now(UTC) - (row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)) < timedelta(minutes=40) else ("interrupted" if row.status == "queued" else payload.get("status", "interrupted")),
        "summary": (row.detail or {}).get("summary"), "error": row.error}


@router.post("/dca-signals/evaluate", response_model=DcaEvaluateOut)
async def evaluate_dca_signals_now(db: Session = Depends(get_db)) -> dict:
    """Refresh at most ten missing/stale states, shared lease and 5min cooldown."""
    import redis
    from fastapi.concurrency import run_in_threadpool

    from app.core.config import get_settings
    from app.core.redis_retry import no_retry
    from app.services import dca_manual, dca_run_log
    from app.services.dca_signal_service import evaluate_watchlist

    tenant = str(db.info.get("tenant_id") or "legacy")

    def _evaluate() -> dict:
        client = redis.Redis.from_url(get_settings().redis_url,
            socket_connect_timeout=1, socket_timeout=2, retry=no_retry())
        token = None
        try:
            try:
                token, wait = dca_manual.acquire_manual_gate(client, tenant)
            except redis.RedisError as exc:
                raise HTTPException(status_code=503, detail="No se puede asegurar una ejecución única ahora; reintenta más tarde.") from exc
            if token is None:
                if wait == -1:
                    raise HTTPException(status_code=409, detail="Ya hay una evaluación DCA en curso en tu cuenta.")
                raise HTTPException(status_code=429,
                    detail=f"Espera {wait} s antes de ejecutar otra tanda.",
                    headers={"Retry-After": str(wait)})
            pending = dca_manual.pending_symbols(db)
            requested = pending[:dca_manual.MAX_SYMBOLS]
            run = dca_run_log.start_run(db, "manual")
            try:
                summary = evaluate_watchlist(db, symbols=set(requested))
                summary.update(requested=len(requested), pending_remaining=max(0, len(pending) - len(requested)),
                    cooldown_seconds=dca_manual.COOLDOWN_SECONDS)
                dca_run_log.finish_run(db, run, summary=summary)
                if run is not None:
                    run.detail = {**(run.detail or {}), "requested_symbols": requested}
                    db.commit()
                return summary
            except Exception as exc:
                db.rollback()
                dca_run_log.finish_run(db, run, error=f"{type(exc).__name__}: {exc}")
                raise
        finally:
            try:
                if token is not None:
                    dca_manual.release_manual_gate(client, tenant, token)
            finally:
                client.close()

    return await run_in_threadpool(_evaluate)


@router.get("/dca-signals/{symbol}/hit-rates", response_model=DcaHitRatesOut)
def dca_hit_rates(symbol: str, db: Session = Depends(get_db)) -> dict:
    """"¿Cuántas veces estaba más arriba?" por nivel (3/6/12/24/36 meses).

    Sale de la ultima evaluacion guardada (misma serie y parametros que el
    veredicto); sin evaluacion previa se declara no disponible, no se inventa.
    """
    from app.services.dca_signal_engine import ZONES

    key = symbol.strip().upper()
    state = db.scalar(
        select(DcaSignalState).where(DcaSignalState.symbol == key, *tenant_filters(db, DcaSignalState))
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Ticker sin señal DCA evaluada (añádelo a watchlist o cartera)")
    data = state.hit_rates or {}
    if not data.get("rows"):
        return {"symbol": key, "available": False, "reason": "Aún sin histórico calculado: se rellena en la próxima evaluación"}
    colors = {zone["key"]: zone["color"] for zone in ZONES.values()}
    rows = [{**row, "color": colors.get(row.get("key"), "#94A3B8")} for row in data["rows"]]
    return {
        "symbol": key,
        "available": True,
        "months_completed": data.get("months_completed", 0),
        "first_period": data.get("first_period"),
        "last_period": data.get("last_period"),
        "horizons": data.get("horizons", []),
        "params_version": data.get("params_version"),
        "evaluated_at": state.evaluated_at,
        "rows": rows,
    }


_PERIOD_RE = r"^\d{4}-(0[1-9]|1[0-2])$"


@router.get("/dca-signals/{symbol}/backtest", response_model=DcaBacktestOut)
def dca_backtest(
    symbol: str,
    start: str | None = Query(None, pattern=_PERIOD_RE, description="Primer mes con señal (YYYY-MM)"),
    end: str | None = Query(None, pattern=_PERIOD_RE, description="Último mes con señal (YYYY-MM)"),
    base: float = Query(100.0, gt=0, le=1_000_000, description="Aportación base mensual"),
    db: Session = Depends(get_db),
) -> dict:
    """Backtest DCA plano vs DCA por niveles (Fórmula Nico v1) para cualquier ticker.

    Sin look-ahead: veredicto con datos hasta el cierre de cada mes y compra al
    primer cierre del mes siguiente. Usa la misma serie que la señal diaria
    (Yahoo, cierre ajustado si existe y sin la barra del día en curso).
    """
    from app.services import dca_signal_service as svc
    from app.services.dca_alert_copy import currency_label
    from app.services.dca_backtest import backtest_dca
    from app.services.dca_signal_engine import ZONES

    key = symbol.strip().upper()
    if not key or len(key) > 24:
        raise HTTPException(status_code=422, detail="Ticker inválido")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="El inicio va después del final")
    company = db.scalar(select(Company).where(Company.ticker == key))
    yahoo = key
    if company is not None:
        from app.services.propicks_price_service import yahoo_symbol

        yahoo = yahoo_symbol(company) or key
    try:
        fetched = svc.fetch_yahoo_history(yahoo)
    except Exception as exc:  # proveedor caido o ticker desconocido: se dice, no se inventa
        raise HTTPException(status_code=502, detail=f"No se pudo descargar el histórico de {key}") from exc
    rows = svc.settled_rows(fetched.rows, datetime.now(UTC))
    bars, _factor = svc.build_bars(rows)
    if not bars:
        return {"symbol": key, "available": False, "reason": "Sin histórico de precios para este ticker"}
    result = backtest_dca(bars, start=start, end=end, base_amount=base, today=date.today())
    currency = fetched.currency or (company.currency if company is not None else None)
    out: dict = {
        "symbol": key,
        "currency": currency,
        "currency_label": currency_label(currency),
        "data_source": "yfinance",
        **result,
    }
    hits = result.get("hit_rates")
    if hits:
        colors = {zone["key"]: zone["color"] for zone in ZONES.values()}
        out["hit_rates"] = {
            "symbol": key,
            "available": bool(hits.get("rows")),
            **hits,
            "rows": [{**row, "color": colors.get(row.get("key"), "#94A3B8")} for row in hits.get("rows", [])],
        }
    return out


@router.get("/attention-thesis")
def home_attention_thesis(db: Session = Depends(get_db)) -> dict:
    """Unresolved thesis changes for this tenant's watchlist and open holdings."""
    from app.services.home_attention_service import pending_thesis_changes

    # One extra row lets the UI state that this bounded inbox is truncated.
    items = pending_thesis_changes(db, limit=100)
    return {"items": items[:99], "truncated": len(items) > 99}
