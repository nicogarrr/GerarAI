import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import CustomMetricDefinition, SavedScreen
from app.schemas.api import (
    ScreenerCustomMetricOut,
    ScreenerMetricCoverageOut,
    ScreenerRealOut,
    ScreenerSavedScreenOut,
)
from app.services.screener_service import (
    DUPLICATE_SCREEN_NAME,
    CustomMetricService,
    ScreenerService,
)

router = APIRouter()


class CustomMetricCreate(BaseModel):
    metric_key: str = Field(min_length=2, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    formula: str = Field(min_length=1, max_length=1000)
    unit: str = Field(default="decimal", min_length=1, max_length=40)
    description: str = Field(default="", max_length=5000)


class Criterion(BaseModel):
    left: str = Field(min_length=1, max_length=1000)
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    right: str = Field(min_length=1, max_length=1000)


class ScreenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=5000)
    criteria: list[Criterion] = Field(min_length=1, max_length=30)
    ranking_formula: str | None = Field(default=None, max_length=1000)
    ranking_direction: Literal["asc", "desc"] = "desc"
    alerts_enabled: bool = True


class AdHocScreen(BaseModel):
    criteria: list[Criterion] = Field(min_length=1, max_length=30)
    ranking_formula: str | None = Field(default=None, max_length=1000)
    ranking_direction: Literal["asc", "desc"] = "desc"


def _metric_payload(row: CustomMetricDefinition) -> dict[str, Any]:
    return {
        "id": row.id,
        "metric_key": row.metric_key,
        "name": row.name,
        "formula": row.formula,
        "unit": row.unit,
        "description": row.description,
        "version": row.version,
        "active": row.active,
        "metadata": row.metadata_,
        "created_at": row.created_at,
    }


def _screen_payload(row: SavedScreen) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "criteria": row.criteria,
        "ranking_formula": row.ranking_formula,
        "ranking_direction": row.ranking_direction,
        "alerts_enabled": row.alerts_enabled,
        "active": row.active,
        "last_run_at": row.last_run_at,
        "created_at": row.created_at,
    }


@router.get("/custom-metrics", response_model=list[ScreenerCustomMetricOut])
def list_custom_metrics(db: Session = Depends(get_db)) -> list[dict]:
    return [_metric_payload(row) for row in CustomMetricService.active(db)]


@router.post("/custom-metrics", status_code=201)
def create_custom_metric(
    payload: CustomMetricCreate, db: Session = Depends(get_db)
) -> dict:
    try:
        row = CustomMetricService().create(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _metric_payload(row)


@router.get("/screens", response_model=list[ScreenerSavedScreenOut])
def list_screens(db: Session = Depends(get_db)) -> list[dict]:
    return [
        _screen_payload(row)
        for row in db.scalars(select(SavedScreen).where(SavedScreen.active.is_(True)).order_by(SavedScreen.name)).all()
    ]


@router.post("/screens", status_code=201)
def create_screen(payload: ScreenCreate, db: Session = Depends(get_db)) -> dict:
    try:
        row = ScreenerService().create_screen(
            db,
            name=payload.name,
            description=payload.description,
            criteria=[item.model_dump() for item in payload.criteria],
            ranking_formula=payload.ranking_formula,
            ranking_direction=payload.ranking_direction,
            alerts_enabled=payload.alerts_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _screen_payload(row)


@router.put("/screens/{screen_id}")
def update_screen(screen_id: int, payload: ScreenCreate, db: Session = Depends(get_db)) -> dict:
    screen = db.get(SavedScreen, screen_id)
    if screen is None or not screen.active:
        raise HTTPException(status_code=404, detail="Saved screen not found")
    service = ScreenerService()
    try:
        criteria = [service._criterion(item.model_dump()) for item in payload.criteria]
        if payload.ranking_formula:
            from app.services.screener_service import SafeFormula
            SafeFormula(payload.ranking_formula)
        name = service.claim_screen_name(db, payload.name, exclude_id=screen.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    screen.name = name
    screen.description = payload.description.strip()
    screen.criteria = criteria
    screen.ranking_formula = payload.ranking_formula
    screen.ranking_direction = payload.ranking_direction
    screen.alerts_enabled = payload.alerts_enabled
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=DUPLICATE_SCREEN_NAME) from exc
    db.refresh(screen)
    return _screen_payload(screen)


@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int, db: Session = Depends(get_db)) -> dict:
    screen = db.get(SavedScreen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Saved screen not found")
    # Archive instead of destroying match history and alert references.
    screen.active = False
    screen.alerts_enabled = False
    db.commit()
    return {"id": screen.id, "status": "archived"}


@router.post("/screens/{screen_id}/run")
def run_saved_screen(screen_id: int, db: Session = Depends(get_db)) -> dict:
    screen = db.get(SavedScreen, screen_id)
    if screen is None or not screen.active:
        raise HTTPException(status_code=404, detail="Saved screen not found")
    return ScreenerService().run_saved(db, screen)


@router.get("/metric-coverage", response_model=ScreenerMetricCoverageOut)
def metric_coverage(db: Session = Depends(get_db)) -> dict:
    """Metric names with data for at least one company.

    The screener UI uses this to only suggest metrics that can actually
    match something; see ScreenerService.metric_coverage.
    """
    return {"metrics_with_data": ScreenerService().metric_coverage(db)}


@router.post("/run")
def run_ad_hoc_screen(payload: AdHocScreen, db: Session = Depends(get_db)) -> dict:
    try:
        return ScreenerService().run(
            db,
            criteria=[item.model_dump() for item in payload.criteria],
            ranking_formula=payload.ranking_formula,
            ranking_direction=payload.ranking_direction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ============================================================================
# REAL-TIME SCREENER  —  GET /api/screeners/real
# ----------------------------------------------------------------------------
# Fuente elegida por defecto: Finnhub (free tier) — /quote da el precio real
# del día (c, d, dp, pc, v) y /stock/profile2 el nombre, market cap y sector
# reales. Yahoo Finance chart API es el vendor alternativo (gratuito, sin key;
# solo quotes, sin profile): se elige con SCREENER_QUOTE_VENDOR=yahoo.
# La fuente de quotes/profile es intercambiable vía SCREEN_VENDORS
# (protocolo ScreenQuoteVendor); el default Finnhub preserva el
# comportamiento actual.
# Yahoo público fue descartado tras probarlo en vivo: el screener
# (/v1/finance/screener/predefined) devuelve HTML bloqueado y /v7/finance/quote
# responde "Unauthorized" (requiere crumb). /stock/screener de Finnhub responde
# 404 sin plan premium.
#
# DISEÑO (screener mínimo HONESTO): universo fijo de ~35 grandes caps líquidos
# (la tabla companies contiene entradas de prueba tipo MATBIG/TPEER1 y small
# caps, así que el universo curado es la fuente primaria; la BD solo se usa
# para enriquecer nombre/sector cuando coincide). Cada ticker se consulta con
# precios y market cap REALES de Finnhub; los filtros marketCapMoreThan/sector
# se aplican sobre esos datos reales. Nunca se inventan precios.
#
# Cache (como market.py): resultado agregado 60s; perfil (nombre/mktcap/sector)
# 6h para no golpear el límite gratuito de 60 llamadas/min (refresco sostenido
# = ~35 /quote por minuto).
# ============================================================================

# (symbol, nombre de respaldo, sector de respaldo)
_REAL_UNIVERSE: list[tuple[str, str, str]] = [
    ("AAPL", "Apple", "Information Technology"),
    ("MSFT", "Microsoft", "Information Technology"),
    ("GOOGL", "Alphabet", "Communication Services"),
    ("AMZN", "Amazon", "Consumer Discretionary"),
    ("NVDA", "NVIDIA", "Information Technology"),
    ("TSLA", "Tesla", "Consumer Discretionary"),
    ("META", "Meta Platforms", "Communication Services"),
    ("BRK.B", "Berkshire Hathaway", "Financials"),
    ("JPM", "JPMorgan Chase", "Financials"),
    ("V", "Visa", "Financials"),
    ("UNH", "UnitedHealth", "Health Care"),
    ("WMT", "Walmart", "Consumer Staples"),
    ("PG", "Procter & Gamble", "Consumer Staples"),
    ("MA", "Mastercard", "Financials"),
    ("HD", "Home Depot", "Consumer Discretionary"),
    ("DIS", "Disney", "Communication Services"),
    ("NFLX", "Netflix", "Communication Services"),
    ("ADBE", "Adobe", "Information Technology"),
    ("CRM", "Salesforce", "Information Technology"),
    ("CSCO", "Cisco", "Information Technology"),
    ("PFE", "Pfizer", "Health Care"),
    ("INTC", "Intel", "Information Technology"),
    ("KO", "Coca-Cola", "Consumer Staples"),
    ("PEP", "PepsiCo", "Consumer Staples"),
    ("MRK", "Merck", "Health Care"),
    ("ABT", "Abbott", "Health Care"),
    ("BAC", "Bank of America", "Financials"),
    ("AMD", "Advanced Micro Devices", "Information Technology"),
    ("ORCL", "Oracle", "Information Technology"),
    ("AVGO", "Broadcom", "Information Technology"),
    ("XOM", "Exxon Mobil", "Energy"),
    ("CVX", "Chevron", "Energy"),
    ("JNJ", "Johnson & Johnson", "Health Care"),
    ("COST", "Costco", "Consumer Staples"),
    ("LIN", "Linde", "Materials"),
]

_ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "GLD"}

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_PROFILE_TTL = 6 * 3600.0  # 6h: nombre/market cap/sector cambian lento
_QUOTE_TTL = 60.0  # precio real del día, refrescado cada minuto (como market.py)
# Sin datos, cada request programaba un refresh nuevo y la UI veía
# `refreshing=true` para siempre (carga indefinida). Tras un intento que
# termina vacío se espera este cooldown antes de volver a intentarlo.
_REAL_REFRESH_COOLDOWN_SECONDS = 30.0
# El universo tiene 35 símbolos: un burst de seis workers está por debajo del
# límite global de 60 llamadas/min y evita el antiguo sleep O(n) de 0,3 s.
# El presupuesto efectivo de 55 deja margen para otros consumidores del mismo
# proceso; el limiter global sólo espera cuando se supera ese presupuesto.
PROFILE_MAX_WORKERS = 6
QUOTE_MAX_WORKERS = 8
_FINNHUB_RATE_LOCK = threading.Lock()
_FINNHUB_WINDOW_SECONDS = 60.0
_FINNHUB_MAX_CALLS_PER_WINDOW = 55
_finnhub_call_times: list[float] = []
_REAL_REQUEST_TIMEOUT_SECONDS = 1.0
_RETRY_DELAY_SECONDS = 0.05
_COLD_START_WAIT_SECONDS = 0.05

# symbol -> {"at": monotonic, "data": {...}}
_real_profile_cache: dict[str, dict] = {}
_real_quote_cache: dict[str, dict] = {}
_profile_singleflight: dict[str, threading.Event] = {}
# Items crudos (todo el universo, sin filtrar) — los filtros se aplican por
# request sobre los datos cacheados, así cada combinación de filtros funciona
# sin golpear Finnhub de nuevo. POR TENANT: los items llevan ratios
# (PE/PB/ROE) calculados sobre financial_facts (TenantOwnedMixin); un bucket
# global dejaba al tenant B leer los ratios del A aunque la clave de la
# respuesta final sí incluyera tenant. "vendor" impide mezclar fuentes.
_real_items_cache: dict[int | None, dict] = {}


def _real_items_bucket(tenant_id: int | None) -> dict:
    """Bucket LKG del tenant; lo crea vacío si no existe."""
    return _real_items_cache.setdefault(
        tenant_id, {"at": 0.0, "items": [], "vendor": None}
    )
# Respuesta completa por parámetros: evita incluso el filtrado O(n) en cada
# petición repetida y hace que el last-known-good sea realmente instantáneo.
_real_response_cache: dict[tuple, dict] = {}
_REAL_RESPONSE_CACHE_MAX = 256
_real_cache_lock = threading.RLock()
_real_refresh_state_lock = threading.RLock()
# Futuro de refresco POR TENANT: los ratios se calculan con los hechos del
# tenant y un refresh tarda (Finnhub free, 60 llamadas/min compartidas). Con
# un unico futuro global, un tenant cuyo bucket estaba frio esperaba detras
# del refresh de OTRO tenant; el cold start no espera y su pantalla (tarjeta
# DCF de Inicio) salia vacia de forma permanente.
_real_refresh_futures: dict[int | None, object] = {}
_real_refresh_generations: dict[int | None, int] = {}
_real_refresh_last_attempt: dict[int | None, float] = {}
_real_refresh_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gerarai-screener-refresh"
)


def _cs(_str: str | None) -> str:
    return (_str or "").strip().lower()


# Los sectores canonicos son los nombres GICS que sirve la tabla companies y
# filtra la UI. Vendors y datos historicos usan alias (Technology,
# Financial Services, Healthcare, ...): sin normalizacion, filtrar por el
# nombre GICS devolvia 0 filas aunque los datos fueran reales (F223).
_SECTOR_ALIASES: dict[str, str] = {
    "technology": "Information Technology",
    "financial services": "Financials",
    "healthcare": "Health Care",
    "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "basic materials": "Materials",
}


def _gics_sector(value: str | None) -> str | None:
    """Normaliza un sector al nombre GICS servido; lo desconocido pasa tal cual."""
    if value is None:
        return None
    return _SECTOR_ALIASES.get(_cs(value), value)


def _load_universe_from_db() -> dict[str, tuple[str, str]]:
    """Enriquecimiento best-effort desde companies (nombre/sector reales)."""
    try:
        from sqlalchemy import text as _text

        from app.core.database import SessionLocal

        with SessionLocal() as db:
            rows = db.execute(
                _text("SELECT ticker, name, sector FROM companies")
            ).fetchall()
        return {str(r[0]).upper(): (str(r[1]), str(r[2])) for r in rows}
    except Exception:  # noqa: BLE001 — el screener funciona sin BD
        return {}


def _load_screener_ratios(
    live_prices: dict[str, dict] | None = None,
    tenant_id: int | None = None,
) -> dict[str, dict]:
    """Best effort: financial ratios must not break the quote endpoint.

    Los ratios salen de `financial_facts`, que pertenece al tenant. La sesión
    se abre aquí y por tanto nace sin `db.info["tenant_id"]`, con lo que los
    guards de aislamiento de app/core/database.py no inyectan scope y la
    consulta era cross-tenant: los PE/PB/ROE se derivaban de los hechos que
    hubiera ingerido cualquier otro tenant. Se fija el tenant antes de leer.
    """
    try:
        from app.core.database import SessionLocal
        from app.services.screener_fundamentals import load_screener_ratios

        with SessionLocal() as db:
            if tenant_id is not None:
                db.info["tenant_id"] = tenant_id
            return load_screener_ratios(
                db,
                {symbol for symbol, _, _ in _REAL_UNIVERSE},
                live_prices=live_prices,
            )
    except Exception:  # noqa: BLE001 — sin base de datos, datos ausentes
        return {}


class ScreenQuoteVendor(Protocol):
    """Fuente intercambiable de quotes/profile para el screener (Finnhub ↔ Yahoo).

    Cada vendor normaliza al mismo dict de quote
    (price/change/changePercent/volume/prevClose/asOf) y de profile
    (name/marketCap/sector/exchange). El default es Finnhub (comportamiento
    actual); Yahoo es la alternativa gratuita sin key.
    """

    name: str
    source_label: str
    #: False si el vendor no puede dar perfil real (p. ej. Yahoo: solo quotes).
    supports_profiles: bool

    def fetch_quote(self, client: httpx.Client, symbol: str) -> dict | None: ...
    def fetch_profile(self, client: httpx.Client, symbol: str) -> dict | None: ...


def _finnhub_get(
    client: httpx.Client, path: str, symbol: str, timeout: float
) -> dict | None:
    # Cada intento real (incluido el retry de 429) consume una llamada Finnhub.
    # Centralizar aquí evita que quote/profile caminos distintos sorteen el límite.
    _reserve_finnhub_call()
    try:
        resp = client.get(
            f"{_FINNHUB_BASE}{path}",
            params={"symbol": symbol},
            timeout=timeout,
        )
        if resp.status_code == 429:  # rate limit free tier: saltar, cache sigue valiendo
            return None
        if resp.status_code != 200:
            return None
        payload = resp.json()
        return payload if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


def _reserve_finnhub_call() -> float:
    """Reserva una llamada sin mantener lock mientras espera el rate limit."""
    now = time.monotonic()
    while True:
        with _FINNHUB_RATE_LOCK:
            cutoff = now - _FINNHUB_WINDOW_SECONDS
            while _finnhub_call_times and _finnhub_call_times[0] <= cutoff:
                _finnhub_call_times.pop(0)
            if len(_finnhub_call_times) < _FINNHUB_MAX_CALLS_PER_WINDOW:
                _finnhub_call_times.append(now)
                return now
            wait = _FINNHUB_WINDOW_SECONDS - (now - _finnhub_call_times[0])
        if wait > 0:
            time.sleep(wait)
        now = time.monotonic()


class FinnhubScreenVendor:
    """Vendor por defecto: Finnhub free tier (comportamiento actual)."""

    name = "finnhub"
    source_label = "finnhub_free"
    supports_profiles = True

    def fetch_quote(self, client: httpx.Client, symbol: str) -> dict | None:
        """Precio real del día vía Finnhub /quote (plan gratuito).

        Retry único en 429 (límite 60 llamadas/minuto): un fallo puntual no debe
        dejar el ticker fuera del screener.
        """
        raw = _finnhub_get(client, "/quote", symbol, timeout=_REAL_REQUEST_TIMEOUT_SECONDS)
        if raw is None:  # posible 429: reintentar una vez tras un delay agrupado
            time.sleep(_RETRY_DELAY_SECONDS)
            raw = _finnhub_get(
                client, "/quote", symbol, timeout=_REAL_REQUEST_TIMEOUT_SECONDS
            )
        if raw and raw.get("c") and raw["c"] > 0:
            # Nulos honestos: un campo ausente en Finnhub es None (sin dato),
            # nunca 0.0 - un cero inventado se mostraria como "+0.00%" real.
            return {
                "price": float(raw["c"]),
                "change": float(raw["d"]) if raw.get("d") is not None else None,
                "changePercent": float(raw["dp"]) if raw.get("dp") is not None else None,
                "volume": float(raw["v"]) if raw.get("v") is not None else None,
                "prevClose": float(raw["pc"]) if raw.get("pc") is not None else None,
                "asOf": raw.get("t"),
            }
        return None

    def fetch_profile(self, client: httpx.Client, symbol: str) -> dict | None:
        """Perfil real (nombre, market cap en USD, sector, exchange) vía profile2."""
        raw = _finnhub_get(
            client,
            "/stock/profile2",
            symbol,
            timeout=_REAL_REQUEST_TIMEOUT_SECONDS,
        )
        if raw and raw.get("ticker"):
            market_cap = raw.get("marketCapitalization")
            return {
                "name": raw.get("name") or symbol,
                "currency": raw.get("currency") or None,
                # None cuando Finnhub no lo reporta: 0.0 seria un dato inventado.
                "marketCap": float(market_cap) * 1_000_000.0 if market_cap else None,
                "sector": raw.get("finnhubIndustry") or None,
                "exchange": raw.get("exchange") or "US",
            }
        return None


_YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _candle_market_date(timestamp: Any, tz_name: Any) -> str | None:
    """Fecha ISO de una vela diaria en la zona del mercado; None si falta algo (nunca se inventa)."""
    if not isinstance(timestamp, (int, float)) or not isinstance(tz_name, str) or not tz_name:
        return None
    try:
        return datetime.fromtimestamp(timestamp, ZoneInfo(tz_name)).date().isoformat()
    except (KeyError, ValueError, OSError):
        return None


class YahooScreenVendor:
    """Vendor alternativo: Yahoo Finance chart API (gratuita, sin key).

    Normaliza al mismo formato que Finnhub. Sin profile real (el endpoint
    /v7/finance/quote de Yahoo requiere crumb y devuelve "Unauthorized"):
    fetch_profile devuelve None y el nombre/sector caen al universo/DB.
    """

    name = "yahoo"
    source_label = "yahoo_finance"
    supports_profiles = False

    def fetch_quote(self, client: httpx.Client, symbol: str) -> dict | None:
        try:
            resp = client.get(
                f"{_YAHOO_CHART_BASE}/{symbol}",
                params={"range": "5d", "interval": "1d"},
                headers=_YAHOO_HEADERS,
                timeout=15,
            )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            payload = resp.json()
            result = payload["chart"]["result"][0]
            raw_closes = result["indicators"]["quote"][0]["close"]
            valid_closes = [(i, value) for i, value in enumerate(raw_closes) if value is not None]
            closes = [value for _, value in valid_closes]
            if not closes or closes[-1] <= 0:
                return None
            volumes = [
                value
                for value in result["indicators"]["quote"][0].get("volume") or []
                if value is not None
            ]
            timestamps = result.get("timestamp") or []
            meta = result.get("meta") or {}
            last = closes[-1]
            previous = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")
            # Sin cierre previo real no hay cambio computable: None, nunca 0.0.
            change = (last - previous) if previous else None
            return {
                "price": float(last),
                "currency": meta.get("currency") or None,
                "change": float(change) if change is not None else None,
                "changePercent": (
                    float(change / previous * 100) if change is not None else None
                ),
                "volume": float(volumes[-1]) if volumes else None,
                "prevClose": float(previous) if previous else None,
                "asOf": timestamps[valid_closes[-1][0]] if valid_closes[-1][0] < len(timestamps) else None,
                # Dia de calendario de la vela diaria en la zona del mercado (el
                # epoch de una vela diaria es su apertura, no una hora de cotizacion).
                "asOfDate": _candle_market_date(
                    timestamps[valid_closes[-1][0]] if valid_closes[-1][0] < len(timestamps) else None,
                    meta.get("exchangeTimezoneName"),
                ),
            }
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def fetch_profile(self, client: httpx.Client, symbol: str) -> dict | None:
        return None



class OfflineScreenVendor:
    """Vendor determinista para E2E/CI: no toca la red y declara vacío.

    Existe para que el navegador no dependa de Finnhub/Yahoo en CI. No es un
    modo de producto: `resolve_screener_vendor` lo ignora en producción.
    """

    name = "offline"
    source_label = "offline"
    supports_profiles = True

    def fetch_quote(self, client: httpx.Client, symbol: str) -> dict | None:
        return None

    def fetch_profile(self, client: httpx.Client, symbol: str) -> dict | None:
        return None


SCREEN_VENDORS: dict[str, ScreenQuoteVendor] = {
    FinnhubScreenVendor.name: FinnhubScreenVendor(),
    YahooScreenVendor.name: YahooScreenVendor(),
    OfflineScreenVendor.name: OfflineScreenVendor(),
}
DEFAULT_SCREENER_VENDOR = "finnhub"


def resolve_profile_vendor(active: ScreenQuoteVendor) -> ScreenQuoteVendor:
    """Vendor para perfiles (nombre/market cap/sector/exchange).

    Si el vendor de quotes no puede dar perfil real (Yahoo), el perfil se
    pide a Finnhub: 35 llamadas cacheadas 6h, muy por debajo del free tier.
    Sin key de Finnhub configurada se conserva el comportamiento anterior
    (fallbacks del universo/DB y marketCap None → "sin datos" en UI).
    """
    if active.supports_profiles:
        return active
    finnhub = SCREEN_VENDORS.get("finnhub")
    if finnhub is not None and get_settings().finnhub_api_key:
        return finnhub
    return active


def resolve_screener_vendor(name: str | None) -> ScreenQuoteVendor:
    """Devuelve el vendor pedido o el default (Finnhub) si es desconocido/vacío.

    `offline` es un fixture determinista para E2E: nunca se acepta en
    producción, aunque venga en el entorno.
    """
    requested = (name or "").strip().lower()
    if requested == OfflineScreenVendor.name and getattr(
        get_settings(), "is_production", False
    ):
        requested = ""
    if not requested:
        return SCREEN_VENDORS[DEFAULT_SCREENER_VENDOR]
    return SCREEN_VENDORS.get(
        requested, SCREEN_VENDORS[DEFAULT_SCREENER_VENDOR]
    )


def _fetch_quote(
    client: httpx.Client, symbol: str, *, vendor: str | None = None
) -> dict | None:
    now = time.monotonic()
    active = resolve_screener_vendor(vendor)
    cache_key = f"{active.name}:{symbol}"
    cached = _real_quote_cache.get(cache_key)
    if cached and now - cached["at"] < _QUOTE_TTL:
        return cached["data"]
    data = active.fetch_quote(client, symbol)
    if data:
        _real_quote_cache[cache_key] = {"at": now, "data": data}
    return data


def _fetch_profile(
    client: httpx.Client, symbol: str, *, vendor: str | None = None
) -> dict | None:
    now = time.monotonic()
    active = resolve_screener_vendor(vendor)
    cache_key = f"{active.name}:{symbol}"
    cached = _real_profile_cache.get(cache_key)
    if cached and now - cached["at"] < _PROFILE_TTL:
        return cached["data"]
    with _real_cache_lock:
        waiter = _profile_singleflight.get(cache_key)
        leader = waiter is None
        if leader:
            waiter = threading.Event()
            _profile_singleflight[cache_key] = waiter
    if not leader:
        waiter.wait(timeout=_REAL_REQUEST_TIMEOUT_SECONDS)
        cached = _real_profile_cache.get(cache_key)
        return cached.get("data") if cached else None
    try:
        data = active.fetch_profile(client, symbol)
        if data:
            with _real_cache_lock:
                _real_profile_cache[cache_key] = {"at": time.monotonic(), "data": data}
        return data
    finally:
        with _real_cache_lock:
            _profile_singleflight.pop(cache_key, None)
        waiter.set()


def _real_response_key(
    vendor: str,
    market_cap: float | None,
    sector: str | None,
    limit: int,
    tenant_id: int | None = None,
) -> tuple[str, float | None, str | None, int, int | None]:
    # El tenant forma parte de la clave: los ratios (PE/PB/ROE) se calculan
    # sobre financial_facts, que es TenantOwnedMixin, asi que la respuesta
    # depende del tenant. Con una clave global, el tenant B recibia ratios
    # derivados de los hechos ingeridos por el tenant A.
    return (vendor, market_cap, _cs(_gics_sector(sector)), max(1, min(limit, 200)), tenant_id)


def _real_response_payload(
    items: list[dict],
    vendor: str,
    market_cap: float | None,
    sector: str | None,
    limit: int,
    *,
    as_of: float | None = None,
    refreshing: bool = False,
) -> dict:
    filtered = [
        item
        for item in items
        if (
            market_cap is None
            or (item.get("marketCap") or 0.0) >= market_cap
        )
        and (not sector or _cs(_gics_sector(item.get("sector"))) == _cs(_gics_sector(sector)))
    ]
    filtered.sort(key=lambda item: (item.get("marketCap") or 0.0), reverse=True)
    limited = [dict(item) for item in filtered[: max(1, min(limit, 200))]]
    return {
        "source": SCREEN_VENDORS[vendor].source_label,
        "as_of": as_of if as_of is not None else time.time(),
        "count": len(limited),
        "screener": limited,
        # Carga fría: sin items y con un refresh en vuelo la respuesta vacía no
        # es «filtro sin resultados»; el front lo distingue con este flag.
        "refreshing": bool(refreshing),
        # El universo entero está vacío (proveedor caído o sin datos): no es un
        # filtro sin coincidencias y el front no debe decir «Sin resultados».
        "unavailable": not items,
        # Tamaño del universo seguido: el subtítulo declara el alcance real en
        # vez de prometer «large caps» a secas con 4 filas de Salud o 2 de Energía.
        "universe_size": len(_REAL_UNIVERSE),
    }


def _real_items_are_fresh(vendor: str, now: float, tenant_id: int | None) -> bool:
    with _real_cache_lock:
        bucket = _real_items_cache.get(tenant_id) or {}
        cache_vendor = bucket.get("vendor")
        return bool(
            bucket.get("items")
            and (cache_vendor is None or cache_vendor == vendor)
            and now - float(bucket.get("at", 0.0)) < _QUOTE_TTL
        )


def _store_real_items(
    items: list[dict], vendor: str, tenant_id: int | None = None
) -> None:
    """Publica un refresco sin perder LKG cuando el proveedor devuelve parcial.

    Todo ocurre dentro del bucket del tenant: los items llevan ratios
    calculados con SUS financial_facts y jamás se mezclan con los de otro.
    """
    with _real_cache_lock:
        bucket = _real_items_bucket(tenant_id)
        previous = {
            item.get("symbol"): item
            for item in bucket.get("items", [])
            if item.get("symbol")
        }
        previous_vendor = bucket.get("vendor")
        fresh = {item.get("symbol"): item for item in items if item.get("symbol")}
        if previous_vendor in (None, vendor):
            merged = [
                fresh.get(symbol, previous.get(symbol))
                for symbol, _, _ in _REAL_UNIVERSE
                if fresh.get(symbol) is not None or previous.get(symbol) is not None
            ]
        else:
            merged = list(items)
        # at_wall alimenta el as_of de la respuesta: si el merge conserva
        # items del LKG anterior, el as_of refleja el dato mas viejo servido,
        # nunca una frescura que el proveedor no confirmo.
        at_wall = time.time()
        carried = set(previous) - set(fresh)
        if carried and bucket.get("at_wall"):
            at_wall = min(at_wall, float(bucket["at_wall"]))
        bucket.update(
            {"at": time.monotonic(), "at_wall": at_wall, "items": merged, "vendor": vendor}
        )
        # Las respuestas cacheadas DE ESTE TENANT se invalidan para recomputar
        # con el nuevo universo; el resto conserva su LKG intacto.
        for key in tuple(_real_response_cache):
            if key[0] == vendor and key[4] == tenant_id:
                _real_response_cache.pop(key, None)


def _refresh_real_items_background(
    vendor: str, generation: int, tenant_id: int | None = None
) -> None:
    try:
        items = _refetch_real_items(vendor=vendor, tenant_id=tenant_id)
        with _real_refresh_state_lock:
            stale_generation = generation != _real_refresh_generations.get(tenant_id, 0)
        if items and not stale_generation:
            _store_real_items(items, vendor, tenant_id)
    except Exception:  # noqa: BLE001 — SWR nunca convierte un fallo upstream en 500
        # El próximo request conserva el last-known-good y vuelve a programar.
        return


def _schedule_real_refresh(vendor: str, tenant_id: int | None = None):
    """Programa el refresh DE ESTE TENANT y devuelve su Future (cold start).

    Con un intento ya terminado y sin datos se respeta un cooldown: antes cada
    request creaba otro Future vacío y `refreshing` nunca volvía a false.
    """
    with _real_refresh_state_lock:
        current = _real_refresh_futures.get(tenant_id)
        if current is not None and not current.done():
            return current
        now = time.monotonic()
        last_attempt = _real_refresh_last_attempt.get(tenant_id)
        if (
            current is not None
            and last_attempt is not None
            and now - last_attempt < _REAL_REFRESH_COOLDOWN_SECONDS
        ):
            return current
        generation = _real_refresh_generations.get(tenant_id, 0) + 1
        _real_refresh_generations[tenant_id] = generation
        future = _real_refresh_executor.submit(
            _refresh_real_items_background, vendor, generation, tenant_id
        )
        _real_refresh_futures[tenant_id] = future
        _real_refresh_last_attempt[tenant_id] = now
        return future


def active_vendor_allows_cold_wait(vendor: str, settings) -> bool:
    """Sólo espera cold-start cuando no hay una llamada Finnhub real que hacer."""
    if vendor != "finnhub":
        return True
    return not bool(settings.finnhub_api_key)


@router.get("/real", response_model=ScreenerRealOut)
def real_time_screener(
    marketCapMoreThan: float | None = None,
    sector: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
) -> dict:
    """Screener real con cache por parámetros y stale-while-revalidate.

    Nunca espera un refresh de red cuando existe LKG: devuelve la respuesta al
    instante y actualiza en segundo plano. En cold start espera como máximo
    50 ms para un primer resultado útil; después devuelve LKG al instante y
    deja el trabajo largo en background.

    El `get_db` no es decorativo: los ratios salen de `financial_facts`, que es
    TenantOwnedMixin, así que la respuesta depende del tenant. Sin esta
    dependencia el handler no conocía su tenant, la clave de caché era global
    y un tenant recibía ratios derivados de los hechos ingeridos por otro.
    """
    settings = get_settings()
    tenant_id = db.info.get("tenant_id")
    vendor = resolve_screener_vendor(settings.screener_quote_vendor)
    key = _real_response_key(
        vendor.name, marketCapMoreThan, sector, limit, tenant_id
    )
    now = time.monotonic()
    refreshing = False
    with _real_cache_lock:
        cached = _real_response_cache.get(key)
        bucket = _real_items_cache.get(tenant_id) or {}
        cached_items = bucket.get("items", [])
        cached_vendor = bucket.get("vendor")
        items_at_wall = float(bucket.get("at_wall") or 0.0) or None
        has_lkg = bool(cached_items) and (
            cached_vendor is None or cached_vendor == vendor.name
        )
    if cached and now - float(cached.get("at", 0.0)) < _QUOTE_TTL:
        # El as_of guardado es el de la captura real de los datos; reescribirlo
        # con time.time() al servir LKG stale afirmaba una frescura falsa.
        # `refreshing` no se congela con la caché: refleja el refresh en vuelo
        # AHORA (una respuesta cacheada de la carga fría no diría la verdad).
        with _real_refresh_state_lock:
            inflight = _real_refresh_futures.get(tenant_id)
        payload = {
            **cached["payload"],
            "screener": [dict(item) for item in cached["payload"]["screener"]],
            "refreshing": bool(inflight is not None and not inflight.done()),
            "universe_size": len(_REAL_UNIVERSE),
        }
        if not _real_items_are_fresh(vendor.name, now, tenant_id):
            _schedule_real_refresh(vendor.name, tenant_id)
        return payload

    items = list(cached_items) if has_lkg else []
    if not _real_items_are_fresh(vendor.name, now, tenant_id):
        future = _schedule_real_refresh(vendor.name, tenant_id)
        refreshing = future is not None and not future.done()
        if not has_lkg and not items and (
            active_vendor_allows_cold_wait(vendor.name, settings)
        ):
            # Sin key/no Finnhub no hay una respuesta real que esperar: el mock
            # o el fallback local puede resolverse en este pequeño budget. Con
            # Finnhub configurado, una petición de red nunca bloquea el cold start.
            # nosemgrep: gerarai-broad-except-pass -- espera acotada del arranque en frio; el refresco sigue en segundo plano y la respuesta usa la cache
            try:
                future.result(timeout=_COLD_START_WAIT_SECONDS)
            except Exception:  # noqa: BLE001 — el background seguirá intentando
                pass
            with _real_cache_lock:
                bucket = _real_items_cache.get(tenant_id) or {}
                items = list(bucket.get("items", []))
                items_at_wall = float(bucket.get("at_wall") or 0.0) or items_at_wall

    payload = _real_response_payload(
        items, vendor.name, marketCapMoreThan, sector, limit, as_of=items_at_wall,
        refreshing=refreshing,
    )
    if items:
        with _real_cache_lock:
            if len(_real_response_cache) >= _REAL_RESPONSE_CACHE_MAX:
                oldest_key = min(
                    _real_response_cache,
                    key=lambda candidate: _real_response_cache[candidate]["at"],
                )
                _real_response_cache.pop(oldest_key, None)
            _real_response_cache[key] = {
                "at": time.monotonic(),
                "payload": payload,
            }
    return payload


def _safe_fetch_quote(client: httpx.Client, symbol: str, vendor: str) -> dict | None:
    try:
        return _fetch_quote(client, symbol, vendor=vendor)
    except Exception:  # noqa: BLE001 — un ticker fallido no tumba el universo
        return None


def _safe_fetch_profile(client: httpx.Client, symbol: str, vendor: str) -> dict | None:
    try:
        return _fetch_profile(client, symbol, vendor=vendor)
    except Exception:  # noqa: BLE001 — un perfil fallido conserva el fallback
        return None


def _refetch_real_items(
    *, vendor: str | None = None, tenant_id: int | None = None
) -> list[dict]:
    """Universo completo con precios/market cap reales (vendor configurable).

    Fase 1: /quote en paralelo (35 llamadas, con retry en 429).
    Fase 2: /stock/profile2 en un pool acotado (sin sleep O(n)); el burst queda
    dentro del límite gratuito de 60 llamadas/min para el universo de 35 tickers.

    `tenant_id` se propaga a la carga de ratios: sin él, el hilo en background
    abría su propia sesión sin scope de tenant.
    """
    db_universe = _load_universe_from_db()
    settings = get_settings()
    active = resolve_screener_vendor(
        vendor if vendor is not None else settings.screener_quote_vendor
    )
    headers = {"User-Agent": "GerarAI/0.1"}

    quotes: dict[str, dict] = {}
    with httpx.Client(headers=headers, timeout=15) as client:
        fn_key = settings.finnhub_api_key
        # El token solo se fija cuando el vendor de QUOTES es Finnhub: con
        # Yahoo activo, httpx fusionaria Client(params) en cada URL de quote
        # y la key de Finnhub se filtraria a Yahoo.
        client.params = {"token": fn_key} if fn_key and active.name == "finnhub" else {}
        with ThreadPoolExecutor(max_workers=QUOTE_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_safe_fetch_quote, client, symbol, active.name): symbol
                for symbol, _, _ in _REAL_UNIVERSE
            }
            for future, symbol in futures.items():
                quote = future.result()
                if quote:
                    quotes[symbol] = quote

    # Precio en vivo como fallback del ratio cuando no hay MarketPrice en BD
    # (la procedencia del ratio queda marcada con el vendor en vivo).
    live_prices = {
        symbol: {
            "price": quote["price"],
            "source": active.source_label,
            "as_of": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(quote["asOf"]))
                if quote.get("asOf")
                else None
            ),
        }
        for symbol, quote in quotes.items()
        if quote.get("price")
    }
    ratios = _load_screener_ratios(live_prices=live_prices, tenant_id=tenant_id)

    profiles: dict[str, dict] = {}
    profile_symbols = [symbol for symbol, _, _ in _REAL_UNIVERSE if symbol in quotes]
    with httpx.Client(headers=headers, timeout=15) as client:
        profile_vendor = resolve_profile_vendor(active)
        fn_key = settings.finnhub_api_key
        client.params = {"token": fn_key} if fn_key and profile_vendor.name == "finnhub" else {}
        now = time.monotonic()
        with _real_cache_lock:
            cached_profiles = {}
            for symbol in profile_symbols:
                cached = _real_profile_cache.get(f"{profile_vendor.name}:{symbol}")
                if cached and now - float(cached.get("at", 0.0)) < _PROFILE_TTL:
                    cached_profiles[symbol] = cached["data"]
        missing_profiles = [
            symbol for symbol in profile_symbols if symbol not in cached_profiles
        ]
        profiles.update(cached_profiles)
        if missing_profiles:
            with ThreadPoolExecutor(
                max_workers=min(PROFILE_MAX_WORKERS, len(missing_profiles))
            ) as pool:
                futures = {
                    pool.submit(
                        _safe_fetch_profile, client, symbol, profile_vendor.name
                    ): symbol
                    for symbol in missing_profiles
                }
                for future, symbol in futures.items():
                    profile = future.result()
                    if profile:
                        profiles[symbol] = profile

    items: list[dict] = []
    for symbol, name_fb, sector_fb in _REAL_UNIVERSE:
        quote = quotes.get(symbol)
        if not quote:
            continue
        profile = profiles.get(symbol)
        db_row = db_universe.get(symbol)
        name = (db_row[0] if db_row else None) or (
            profile["name"] if profile else name_fb
        )
        sector_value = _gics_sector(
            db_row[1]
            if db_row
            else (profile["sector"] if profile and profile["sector"] else sector_fb)
        )
        items.append(
            {
                "symbol": symbol,
                "name": name,
                "price": quote["price"],
                "priceAsOf": quote.get("asOf"),
                "priceTimestampKind": "daily_candle_open" if active.name == "yahoo" else "quote",
                "priceDate": quote.get("asOfDate"),
                "currency": quote.get("currency"),
                "change": quote["change"],
                "changePercent": quote["changePercent"],
                # None sin perfil real: la UI muestra N/D; un 0.0 inventado
                # falseaba ademas los filtros marketCapMoreThan y el orden.
                "marketCap": (profile or {}).get("marketCap"),
                "volume": quote["volume"],
                "prevClose": quote["prevClose"],
                "sector": sector_value,
                "exchange": profile["exchange"] if profile else "US",
                "type": "ETF" if symbol.upper() in _ETF_SYMBOLS else "Stock",
                **ratios.get(symbol, {"pe": None, "pb": None, "roe": None, "has_fundamentals": False}),
                "beta": None,
            }
        )
    return items
