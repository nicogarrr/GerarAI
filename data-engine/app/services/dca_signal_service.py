"""Senales DCA por niveles sobre watchlist + cartera, con avisos sin repeticion.

Para cada simbolo seguido por el tenant (watchlist y posiciones vivas, sin
duplicar) se descarga la historia diaria, se calcula el veredicto del mes con
el motor puro ``dca_signal_engine`` y se guarda en ``dca_signal_states``. Si el
nivel cambia y supera el minimo efectivo (ajuste por ticker o global) se emite
una alerta ``dca_level`` y se despacha por el outbox (in_app / email /
Telegram con suscripcion "dca_levels").

Reglas de aviso (deduplicacion):

* Avisa un CAMBIO real de nivel respecto al guardado, en las dos direcciones,
  con ``direction`` en el aviso: ``up`` (1X -> 2X, 3X -> 4X; hacia recorte:
  1X -> ligero -> fuerte) o ``down`` (3X -> 2X, 2X -> 1X, fuerte -> ligero,
  recorte -> 1X), que se redacta como aviso informativo («baja a 2X»).
  Con politica por tenant: subida si destino >= minimo, bajada si destino <= maximo.
  Sin tenant se conserva la regla legacy del nivel de partida.
* La primera evaluacion de un ticker (sin estado guardado, p. ej. recien
  anadido a la watchlist) solo guarda el nivel, sin aviso.
* Huella ``dca_level:{simbolo}:{mes}:{nivel}`` (subidas) y
  ``dca_level:{simbolo}:{mes}:{nivel}:baja`` (bajadas): cada nivel avisa como
  mucho una vez por mes y direccion aunque el mes en formacion oscile
  (3X -> 2X -> 3X -> 2X da dos avisos, no cuatro).
* Escalar (2X -> 3X -> 4X) avisa de nuevo; seguir en el mismo nivel al
  cambiar de mes no.
* Recortes solo con DCA_ALERT_TRIMS=true. Overrides por ticker se conservan,
  pero no afectan a los avisos si hay contexto de tenant (defaults 3X/1X).

Datos: Yahoo Finance (yfinance, historia completa) con la linea real del
listado (``yahoo_symbol``); si falla, los cierres de ``market_prices``. Se usa
el cierre ajustado cuando existe (una fila suelta sin ajuste no pasa la serie
entera a cierres brutos); el cierre mostrado y los precios de nivel se
expresan en precio real de cotizacion.
Sin historia suficiente el ticker se omite con motivo: nunca se inventa.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from time import monotonic as _monotonic
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import generation_language
from app.core.tenancy import tenant_filters
from app.models import (
    AlertDelivery,
    Company,
    DcaAlertOverride,
    DcaSignalState,
    MarketPrice,
    Position,
    ResearchAlert,
    WatchItem,
)
from app.services import dca_alert_copy
from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    ZONES,
    DailyBar,
    DcaParams,
    MonthlyVerdict,
    current_verdict,
    hit_rates,
    zone_visits,
)

logger = logging.getLogger(__name__)

ALERT_TYPE = "dca_level"
SEVERITY_BY_LEVEL = {4: "critical", 3: "high", 2: "medium"}
_ALLOWED_CHANNELS = ("in_app", "email", "push")
_NY = ZoneInfo("America/New_York")
# Un cierre del dia en curso solo esta asentado tras la sesion US (16:30 NY,
# misma regla que market_close_sync / propicks_price_service).
_SESSION_CLOSED_AFTER = time(16, 30)


@dataclass(frozen=True)
class PriceRow:
    day: date
    close: float
    adj_close: float | None = None


@dataclass(frozen=True)
class FetchedHistory:
    rows: list[PriceRow]
    currency: str | None = None


HistoryFetcher = Callable[[str], FetchedHistory]


@dataclass
class TrackedSymbol:
    symbol: str
    company: Company | None = None
    sources: list[str] = field(default_factory=list)


def fetch_yahoo_history(symbol: str, *, period: str = "max") -> FetchedHistory:
    """Historia diaria de Yahoo (sin auto-ajuste) y la divisa del listado.

    La divisa sale de ``history_metadata`` de la misma descarga (sin peticion
    extra): Yahoo da "GBp" para las lineas de Londres en peniques.
    """
    import math

    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, auto_adjust=False)
    rows: list[PriceRow] = []
    # Columnas en bloque, no ``iterrows`` (que crea una Series por fila: ~0,3 s
    # para los ~11.000 dias de un historico "max"). Mismo filtrado fila a fila.
    n = len(hist)
    closes = hist["Close"].tolist() if "Close" in hist else [None] * n
    adjs = hist["Adj Close"].tolist() if "Adj Close" in hist else [None] * n
    for idx, close_raw, adj_raw in zip(hist.index, closes, adjs, strict=True):
        try:
            close = float(close_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        try:
            adj = float(adj_raw) if adj_raw is not None else None
        except (TypeError, ValueError):
            adj = None
        if adj is not None and (not math.isfinite(adj) or adj <= 0):
            adj = None
        day = idx.date() if hasattr(idx, "date") else idx
        rows.append(PriceRow(day=day, close=close, adj_close=adj))
    currency = None
    try:
        currency = (getattr(ticker, "history_metadata", None) or {}).get("currency")
    except Exception:  # noqa: BLE001 - la divisa es informativa
        currency = None
    return FetchedHistory(rows=rows, currency=currency)


# Cache corta de proceso para la vista (backtest): cada apertura descargaba el
# historico "max" entero de Yahoo. Datos publicos, iguales para todos los
# usuarios. El job diario de senales no la usa (lee siempre fresco).
_HISTORY_TTL_S = 600.0
_HISTORY_MAX_ENTRIES = 64
_history_lock = threading.Lock()
_history_cache: dict[str, tuple[float, object, FetchedHistory]] = {}


def fetch_yahoo_history_cached(symbol: str) -> FetchedHistory:
    """``fetch_yahoo_history`` (historico "max") con cache de 10 min por simbolo.

    Un fallo no se cachea. La entrada guarda la funcion que la produjo para
    que un doble de test nunca reciba datos de otro.
    """
    key = symbol.strip().upper()
    fetcher = fetch_yahoo_history
    now = _monotonic()
    with _history_lock:
        hit = _history_cache.get(key)
        if hit is not None and hit[1] is fetcher and now - hit[0] < _HISTORY_TTL_S:
            return hit[2]
    fetched = fetcher(symbol)
    with _history_lock:
        if len(_history_cache) >= _HISTORY_MAX_ENTRIES:
            _history_cache.pop(min(_history_cache, key=lambda k: _history_cache[k][0]), None)
        _history_cache[key] = (_monotonic(), fetcher, fetched)
    return fetched


def tracked_symbols(db: Session) -> dict[str, TrackedSymbol]:
    """Simbolos seguidos por el tenant: watchlist + posiciones con cantidad > 0."""
    tracked: dict[str, TrackedSymbol] = {}
    for symbol in db.scalars(select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))):
        key = (symbol or "").strip().upper()
        if key:
            tracked.setdefault(key, TrackedSymbol(symbol=key)).sources.append("watchlist")
    held = db.execute(
        select(Company)
        .join(Position, Position.company_id == Company.id)
        .where(Position.quantity > 0, *tenant_filters(db, Position))
    ).scalars()
    for company in held:
        key = (company.ticker or "").strip().upper()
        if not key:
            continue
        item = tracked.setdefault(key, TrackedSymbol(symbol=key))
        item.company = company
        if "portfolio" not in item.sources:
            item.sources.append("portfolio")
    missing = [key for key, item in tracked.items() if item.company is None]
    if missing:
        for company in db.scalars(select(Company).where(Company.ticker.in_(missing))):
            tracked[company.ticker.upper()].company = company
    for item in tracked.values():
        item.sources = sorted(set(item.sources), key=["watchlist", "portfolio"].index)
    return dict(sorted(tracked.items()))


def overrides(db: Session) -> dict[str, int]:
    return {
        row.symbol.upper(): int(row.min_level)
        for row in db.scalars(select(DcaAlertOverride).where(*tenant_filters(db, DcaAlertOverride)))
    }


def effective_min_level(override: int | None, settings: Any | None = None) -> int:
    """Nivel minimo efectivo: ajuste del ticker o global. 0 = sin avisos."""
    if override is not None:
        return int(override)
    settings = settings or get_settings()
    return int(settings.dca_alert_min_level)


def alert_channels(settings: Any) -> list[str]:
    raw = str(getattr(settings, "dca_alert_channels", "in_app") or "in_app")
    channels = [c.strip() for c in raw.split(",") if c.strip() in _ALLOWED_CHANNELS]
    return list(dict.fromkeys(channels)) or ["in_app"]


def alert_direction(level: int, previous_level: int | None) -> str | None:
    """``up`` si la senal se intensifica, ``down`` si se relaja, None sin cambio.

    Compra: mas X es mas intensa. Recorte: fuerte es mas intenso que ligero.
    Pasar de compra a recorte es ``up``; volver de recorte a 1X es ``down`` y
    volver de recorte directamente a 2X+ es entrar en zona de compra (``up``).
    """
    if previous_level is None or level == previous_level:
        return None
    if level >= 1 and previous_level >= 1:
        return "up" if level > previous_level else "down"
    if level < 0 and previous_level < 0:
        return "up" if level < previous_level else "down"
    if level < 0:
        return "up"
    return "up" if level >= 2 else "down"


def should_alert(
    *,
    level: int,
    previous_level: int | None,
    min_level: int,
    trims_enabled: bool,
    up_min_level: int | None = None,
    down_max_level: int | None = None,
) -> bool:
    """Regla de aviso por cambio de nivel en ambas direcciones (sin mirar la huella del mes).

    Sin nivel previo (primera evaluacion) no se avisa: se siembra el estado.
    """
    direction = alert_direction(level, previous_level)
    if direction is None or previous_level is None:
        return False
    if up_min_level is not None and down_max_level is not None:
        # Explicit tenant policy: destination threshold, independently per direction.
        if level >= 1 and previous_level >= 1:
            if direction == "up":
                return up_min_level > 0 and level >= up_min_level
            return down_max_level > 0 and level <= down_max_level
        # Returning from trim to a buy zone still obeys the buy threshold.
        if previous_level < 0 and level >= 2:
            return (up_min_level > 0 and level >= up_min_level) or bool(trims_enabled)
        # Trims are a separate server-controlled opt-in, unchanged by this form.
        if level < 0 or previous_level < 0:
            return bool(trims_enabled)
        return False
    if min_level <= 0:
        return False
    if level >= 1 and previous_level >= 1:
        # Subida: el nivel nuevo llega al minimo. Bajada: el de partida llegaba.
        return (level if direction == "up" else previous_level) >= min_level
    if level >= 2:
        # De recorte a zona de compra 2X+.
        return level >= min_level or bool(trims_enabled)
    # Entrar, moverse o salir (a 1X) de recorte.
    return bool(trims_enabled)


def _yahoo_symbol_for(item: TrackedSymbol) -> str | None:
    from app.services.propicks_price_service import yahoo_symbol

    if item.company is not None:
        return yahoo_symbol(item.company)
    # Sin ficha: el simbolo tal y como lo escribio el usuario en la watchlist.
    return item.symbol


def _db_history(db: Session, company: Company | None) -> FetchedHistory:
    """Cierres guardados en UNA sola unidad, sin FX.

    ``market_prices`` puede mezclar unidades de un mismo listado (TSCO.L en
    GBp de un proveedor y en GBP de otro): leidos tal cual, 250 peniques
    seguidos de 2,52 libras parecen una caida del 99 % y el motor daria 4X.
    La unidad es la ``quote_currency`` de la fila mas reciente que la declara
    (si ninguna, la divisa de la empresa, como antes). Cada fila se pasa a esa
    unidad solo si es la misma moneda (GBp <-> GBP, exacto); una fila en otra
    moneda se descarta. Una fila heredada sin unidad se lee en la divisa de la
    empresa, como siempre.
    """
    if company is None:
        return FetchedHistory(rows=[])
    from app.valuation.currency import normalize_currency

    # Columnas, no entidades: son años de cierres por ticker y construir un
    # MarketPrice ORM por fila era casi todo el coste de la evaluacion DCA
    # (400 tickers x 5 años = ~520.000 objetos). MarketPrice no es de tenant.
    prices = [
        (day, close, adj_close, quote_currency)
        for day, close, adj_close, quote_currency in db.execute(
            select(
                MarketPrice.date,
                MarketPrice.close,
                MarketPrice.adj_close,
                MarketPrice.quote_currency,
            )
            .where(MarketPrice.company_id == company.id)
            .order_by(MarketPrice.date)
        )
        if close and float(close) > 0
    ]
    declared = [quote for _day, _close, _adj, quote in prices if quote]
    unit = declared[-1] if declared else company.currency
    unit_major, unit_divisor = normalize_currency(unit)
    # Escala por unidad de fila: hay una o dos unidades por ticker, no una por
    # cierre. None = otra moneda (o unidad desconocida frente a una declarada).
    scales: dict[str | None, float | None] = {}
    rows: list[PriceRow] = []
    for day, close, adj_close, quote in prices:
        if quote in scales:
            scale = scales[quote]
        else:
            major, divisor = normalize_currency(quote or company.currency)
            scale = unit_divisor / divisor if major == unit_major else None
            scales[quote] = scale
        if scale is None:
            continue  # otra moneda (o unidad desconocida frente a una declarada): nunca a la par
        rows.append(
            PriceRow(
                day=day,
                close=float(close) * scale,
                adj_close=float(adj_close) * scale if adj_close else None,
            )
        )
    return FetchedHistory(rows=rows, currency=unit)


def settled_rows(rows: Sequence[PriceRow], now: datetime) -> list[PriceRow]:
    """Descarta barras futuras y la del dia en curso con la sesion US abierta."""
    local = now.astimezone(_NY)
    today = local.date()
    closed = local.time() >= _SESSION_CLOSED_AFTER
    return [row for row in rows if row.day < today or (row.day == today and closed)]


def _fresh_rows(rows: Sequence[PriceRow], today: date, max_age_days: int) -> list[PriceRow]:
    """Vacio si el cierre mas reciente es mas viejo que el maximo permitido.

    La historia antigua sigue sirviendo para backtests; aqui solo se impide que
    emita una senal como si fuera actual.
    """
    if not rows:
        return []
    newest = max(row.day for row in rows)
    return list(rows) if (today - newest).days <= max_age_days else []


def build_bars(rows: Sequence[PriceRow]) -> tuple[list[DailyBar], float]:
    """Serie para el motor y factor serie->precio real del ultimo cierre.

    Con cierre ajustado se usa el ajustado. Una fila suelta sin ``adj_close``
    no pasa toda la serie a cierres brutos (un split se leeria como desplome):
    las filas sin ajuste dentro de la historia ajustada se omiten, y las
    posteriores al ultimo ajuste usan el ultimo factor conocido. Solo si
    ninguna fila trae ajuste se usan los cierres brutos.
    """
    ordered = sorted(rows, key=lambda r: r.day)
    if not ordered:
        return [], 1.0
    adjusted = [i for i, row in enumerate(ordered) if row.adj_close and row.close]
    if not adjusted:
        return [DailyBar(day=row.day, close=float(row.close)) for row in ordered], 1.0
    last_adj = adjusted[-1]
    # nosemgrep: gerarai-money-none-to-zero -- last_adj es por construccion el indice de la ultima fila con adj_close no nulo
    ratio = float(ordered[last_adj].adj_close or 0.0) / float(ordered[last_adj].close)
    bars: list[DailyBar] = []
    for i, row in enumerate(ordered):
        if row.adj_close and row.close:
            bars.append(DailyBar(day=row.day, close=float(row.adj_close)))
        elif i > last_adj:
            bars.append(DailyBar(day=row.day, close=float(row.close) * ratio))
    factor = 1.0 / ratio if ratio > 0 else 1.0
    return bars, factor


def _company_name(item: TrackedSymbol) -> str | None:
    return item.company.name if item.company is not None and item.company.name else None


def _dca_payload(
    item: TrackedSymbol,
    verdict: MonthlyVerdict,
    *,
    close: float,
    level_prices: dict[str, float | None],
    currency: str | None,
    previous_level: int | None,
    params: DcaParams,
) -> dict[str, Any]:
    zone = ZONES[verdict.level]
    direction = alert_direction(verdict.level, previous_level)
    previous_zone = ZONES.get(previous_level) if previous_level is not None else None
    return {
        "symbol": item.symbol,
        "company_name": _company_name(item),
        "level": verdict.level,
        "previous_level": previous_level,
        "previous_label": previous_zone["label"] if previous_zone else None,
        "direction": direction,
        "informational": direction == "down",
        "key": zone["key"],
        "label": zone["label"],
        "zone": zone["zone"],
        "color": zone["color"],
        "fg": zone["fg"],
        "status": verdict.status,
        "period": verdict.period,
        "signal_date": verdict.signal_date.isoformat(),
        "close": close,
        "currency": currency,
        "metrics": dict(verdict.metrics),
        "level_prices": level_prices,
        "touched_level": verdict.touched_level,
        "sources": list(item.sources),
        "sma_months": getattr(params, "sma_months", None),
        "high_lookback_months": getattr(params, "high_lookback_months", None),
        "params_version": params.version,
    }


def _scaled(value: float | None, factor: float) -> float | None:
    return round(value * factor, 6) if value is not None else None


def _emit_alert_row(db: Session, dca: dict[str, Any], *, company_id: int | None, settings: Any) -> tuple[str, ResearchAlert | int]:
    """Inserta la alerta SIN commit: va en la misma transaccion que el estado."""
    from app.services.review_alert_service import ReviewAlertService

    service = ReviewAlertService()
    parts = [ALERT_TYPE, dca["symbol"], dca["period"], str(dca["level"])]
    down = dca.get("direction") == "down"
    if down:
        # Huella propia: una bajada a 2X no queda tapada por la subida a 2X del mismo mes.
        parts.append("baja")
    fingerprint = service.fingerprint_for(db, parts)
    exists = db.scalar(
        select(ResearchAlert.id).where(ResearchAlert.fingerprint == fingerprint, *tenant_filters(db, ResearchAlert))
    )
    if exists is not None:
        return "duplicate", exists
    # Idioma guardado del usuario al disparar (Ajustes); sin preferencia o con
    # la generacion multidioma apagada, espanol como siempre.
    language = generation_language(db)
    metadata: dict[str, Any] = {"dca": dca}
    if language != "es":
        metadata["language"] = language
    alert = service.emit_alert(
        db,
        company_id=company_id,
        alert_type=ALERT_TYPE,
        severity="low" if down else SEVERITY_BY_LEVEL.get(int(dca["level"]), "low"),
        title=dca_alert_copy.title(dca, language),
        message=dca_alert_copy.message_text(dca, language),
        fingerprint_parts=parts,
        channels=alert_channels(settings),
        metadata=metadata,
    )
    # Intencion de entrega DURABLE: una fila 'pending' por canal externo en la
    # misma transaccion que la alerta. Si el despacho falla antes de crear las
    # filas (o el proceso muere), el reconciliador las reclama tras el TTL.
    for channel in alert.channels or []:
        if channel in ("in_app", "telegram"):
            continue
        already = db.scalar(
            select(AlertDelivery.id).where(AlertDelivery.alert_id == alert.id, AlertDelivery.channel == channel)
        )
        if already is None:
            db.add(AlertDelivery(tenant_id=alert.tenant_id, alert_id=alert.id, channel=channel))
    db.flush()
    return "alerted", alert


def _dispatch_alert(db: Session, alert: ResearchAlert) -> dict:
    """Entrega tras el commit; un fallo de canal no pierde la alerta."""
    from app.services.notification_service import NotificationService

    try:
        deliveries = NotificationService().dispatch(db, alert)
    except Exception:  # noqa: BLE001 - el aviso queda en la app aunque falle un canal
        logger.warning("dca dispatch failed alert_id=%s", alert.id, exc_info=True)
        db.rollback()
        deliveries = {"error": "dispatch_error"}
    return {
        "status": "alerted",
        "alert_id": alert.id,
        "deliveries": {k: v.get("status") if isinstance(v, dict) else v for k, v in deliveries.items()},
    }


def evaluate_watchlist(
    db: Session,
    *,
    fetcher: HistoryFetcher | None = None,
    today: date | None = None,
    now: datetime | None = None,
    params: DcaParams = DEFAULT_PARAMS,
    use_db_fallback: bool = True,
    symbols: set[str] | None = None,
) -> dict[str, Any]:
    """Evalua watchlist + cartera del tenant de la sesion. Devuelve un resumen."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    today = today or now.astimezone(_NY).date()
    fetch = fetcher or fetch_yahoo_history
    tracked = tracked_symbols(db)
    per_ticker = overrides(db)
    from app.services.dca_alert_settings_service import effective_policy
    policy = effective_policy(db)
    states = {
        row.symbol.upper(): row
        for row in db.scalars(select(DcaSignalState).where(*tenant_filters(db, DcaSignalState)))
    }
    summary: dict[str, Any] = {
        "tracked": len(tracked),
        "evaluated": 0,
        "alerted": [],
        "skipped": [],
        "errors": [],
        "alerts_enabled": bool(settings.dca_alerts_enabled),
        "params_version": params.version,
    }
    for symbol, item in tracked.items():
        if symbols is not None and symbol not in symbols:
            continue
        history = FetchedHistory(rows=[])
        source = None
        yahoo = _yahoo_symbol_for(item)
        if yahoo:
            try:
                history = fetch(yahoo)
                source = "yahoo"
            except Exception as exc:  # noqa: BLE001 - un ticker roto no frena el barrido
                summary["errors"].append({"symbol": symbol, "error": type(exc).__name__})
                history = FetchedHistory(rows=[])
        max_age = int(settings.dca_max_data_age_days)
        seen_days = [r.day for r in history.rows]
        rows = _fresh_rows(settled_rows(history.rows, now), today, max_age)
        if not rows and use_db_fallback:
            fallback = _db_history(db, item.company)
            rows = _fresh_rows(settled_rows(fallback.rows, now), today, max_age)
            history = fallback
            seen_days += [r.day for r in fallback.rows]
            source = "market_prices" if rows else source
        if not rows:
            newest = max((d for d in seen_days if d <= today), default=None)
            if newest is not None:
                # Historia vieja: no se trata como senal actual ni se avisa.
                summary["skipped"].append(
                    {"symbol": symbol, "reason": "datos_desactualizados", "last_price_date": newest.isoformat()}
                )
                continue
        bars, factor = build_bars(rows)
        verdict = current_verdict(bars, params=params, today=today) if bars else None
        if verdict is None:
            reason = "sin_datos" if not bars else "historia_insuficiente"
            if not yahoo and not bars:
                reason = "sin_simbolo_yahoo_seguro"
            summary["skipped"].append({"symbol": symbol, "reason": reason, "daily_bars": len(bars)})
            continue
        last_row = max(rows, key=lambda r: r.day)
        # La unidad real de las filas USADAS, no la divisa general de la ficha:
        # el respaldo de market_prices normaliza a la unidad declarada (p. ej.
        # peniques GBp); etiquetarlas con company.currency (GBP) mostraba el
        # cierre en peniques como libras (x100) en el estado, la UI y el correo.
        currency = history.currency or (item.company.currency if item.company is not None else None)
        level_prices = {key: _scaled(value, factor) for key, value in verdict.level_prices.items()}
        state = states.get(symbol)
        previous_level = state.level if state is not None else None
        if state is None:
            state = DcaSignalState(tenant_id=db.info.get("tenant_id"), symbol=symbol)
            db.add(state)
            states[symbol] = state
        elif state.level != verdict.level:
            state.previous_level = state.level
        state.company_id = item.company.id if item.company is not None else None
        state.level = verdict.level
        state.status = verdict.status
        state.period = verdict.period
        state.signal_date = verdict.signal_date
        state.close = Decimal(str(round(last_row.close, 6)))
        state.currency = currency
        state.metrics = dict(verdict.metrics)
        state.level_prices = level_prices
        state.sources = list(item.sources)
        # Tabla "¿cuantas veces estaba mas arriba?" con la misma serie y los
        # mismos parametros (solo meses confirmados, sin look-ahead).
        hr_payload = hit_rates(bars, params=params, today=today)
        # Mismo corte temporal que hit_rates: la duración de visitas sale de la
        # misma serie y parámetros; los estados viejos sin la clave se declaran
        # no disponibles hasta la próxima evaluación, nunca se rellenan.
        hr_payload["zone_visits"] = zone_visits(bars, params=params, today=today)
        state.hit_rates = hr_payload
        state.params_version = params.version
        state.evaluated_at = now
        state.data_source = source or "desconocido"
        db.flush()
        summary["evaluated"] += 1
        min_level = effective_min_level(per_ticker.get(symbol), settings)
        if not settings.dca_alerts_enabled or not should_alert(
            level=verdict.level,
            previous_level=previous_level,
            min_level=min_level,
            trims_enabled=bool(settings.dca_alert_trims),
            up_min_level=policy.up_min_level if policy else None,
            down_max_level=policy.down_max_level if policy else None,
        ):
            continue
        dca = _dca_payload(
            item,
            verdict,
            close=last_row.close,
            level_prices=level_prices,
            currency=currency,
            previous_level=previous_level,
            params=params,
        )
        # Estado y alerta en UNA transaccion: un fallo entre ambos deja el nivel
        # sin guardar y el reintento vuelve a emitir el aviso.
        try:
            status, emitted = _emit_alert_row(db, dca, company_id=state.company_id, settings=settings)
            state.last_alerted_level = verdict.level
            state.last_alerted_period = verdict.period
            db.commit()
        except Exception:
            db.rollback()
            raise
        if status == "alerted":
            outcome = _dispatch_alert(db, emitted)
            summary["alerted"].append({"symbol": symbol, "level": verdict.level, **outcome})
    # Los tickers que ya no se siguen dejan de mostrarse.
    for symbol, state in states.items():
        if symbol not in tracked:
            db.delete(state)
    db.commit()
    # Tras el commit final: el listado /watchlist/dca-signals cacheado por
    # tenant ya no refleja los estados recien escritos.
    from app.core.cache import invalidate_dca_cache

    invalidate_dca_cache(db=db)
    return summary
