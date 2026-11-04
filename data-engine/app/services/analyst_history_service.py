"""Historial de analistas por ticker: cómo acertaron sus precios objetivo.

Fuente gratuita y no oficial (Yahoo Finance vía yfinance): el histórico de
cambios de recomendación y precio objetivo por firma (``upgrades_downgrades``)
y los cierres diarios. Para cada objetivo con el horizonte ya cumplido (6 y 12
meses) se compara con el cierre real en esa fecha, usando SOLO cierres hasta
la fecha del horizonte (sin mirar el futuro).

Puntuación por firma y ticker:
- error absoluto ``|ln(objetivo / precio al horizonte)|`` y acierto de
  dirección (si el objetivo apuntaba hacia donde fue el precio);
- error RELATIVO: su error menos la mediana del error de las otras firmas que
  publicaron en la misma ventana (±45 días). Así una acción que se multiplicó
  por 20 no castiga igual a todas: se mide quién lo hizo mejor que sus pares;
- encogimiento bayesiano hacia la media del ticker (5 pseudo-muestras) y peso
  a lo reciente; con menos de 5 muestras vencidas la firma no entra en el
  ranking y lleva la marca de muestra pequeña.

El consenso que se devuelve es la media SIMPLE de los objetivos vigentes: el
backtest de investigación (21 acciones de software, nov 2026) mostró que
ponderar por acierto pasado no mejora a la media simple, así que no se ofrece
un «consenso inteligente» como si fuera mejor.

Sin cobertura (p. ej. la mayoría de listados no estadounidenses) el estado es
``empty`` con su motivo; un fallo de Yahoo es ``unavailable`` y nunca se cachea.
"""

from __future__ import annotations

import asyncio
import math
import time
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel

from app.services.analyst_targets_service import (
    _clean,
    _fetch_currency_and_type,
    _fetch_first_trade_date,
    _positive,
    non_equity_label,
)

SOURCE = "Yahoo Finance (no oficial): histórico de recomendaciones y cierres diarios"
SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}/analysis/"
# El histórico solo cambia cuando una firma publica; 6 h basta y evita
# descargar años de cierres en cada visita a la ficha.
CACHE_TTL_SECONDS = 6 * 3600
FETCH_TIMEOUT_SECONDS = 20.0

HORIZONS: dict[str, int] = {"6m": 182, "12m": 365}
HorizonKey = Literal["6m", "12m"]
MIN_SAMPLES = 5  # muestras vencidas mínimas para entrar en el ranking
SHRINK_PSEUDO_SAMPLES = 5.0  # pseudo-muestras hacia la media del ticker
RECENCY_HALF_LIFE_DAYS = 730
PEER_WINDOW_DAYS = 45  # ventana a cada lado para comparar con otras firmas
MIN_PEERS = 2
CONSENSUS_WINDOW_DAYS = 365  # objetivo vigente = último de cada firma en 12 meses
RATING_CHANGE_WINDOW_DAYS = 90
TOP_N = 5

# Mismas firmas con nombres distintos según la época en Yahoo (fusiones o
# cambios de marca). Es normalización de NOMBRE de firma, no de tickers.
FIRM_ALIASES: dict[str, str] = {
    "keybanc": "KeyBanc",
    "cowen & co.": "TD Cowen",
    "exane bnp paribas": "BNP Paribas",
    "roth mkm": "Roth Capital",
    "citizens capital markets": "Citizens",
    "redburn partners": "Redburn Atlantic",
    "suntrust robinson humphrey": "Truist Securities",
}


class FirmScore(BaseModel):
    firm: str
    samples: int
    median_abs_error_pct: float
    # >0: sus objetivos quedaron por encima del precio real (optimista).
    median_bias_pct: float
    direction_hit_rate: float
    # Error frente a sus pares (puntos de error logarítmico x100, encogido):
    # negativo = más preciso que las otras firmas del momento.
    relative_error: float | None = None
    # Muestras con pares en la misma ventana (las que cuentan para el ranking).
    peer_scored_samples: int = 0
    small_sample: bool = False
    last_date: str
    last_target: float


class HorizonSummary(BaseModel):
    horizon: HorizonKey
    months: int
    matured_targets: int
    median_abs_error_pct: float | None = None
    median_bias_pct: float | None = None
    direction_hit_rate: float | None = None
    ranked_firms: int = 0
    small_sample_firms: int = 0
    top: list[FirmScore] = []
    bottom: list[FirmScore] = []


class SimpleConsensus(BaseModel):
    method: Literal["simple_mean"] = "simple_mean"
    mean: float
    median: float
    firms: int
    reference_price: float | None = None
    upside_percent: float | None = None


class RatingChanges(BaseModel):
    window_days: int = RATING_CHANGE_WINDOW_DAYS
    upgrades: int = 0
    downgrades: int = 0


class AnalystHistory(BaseModel):
    symbol: str
    status: Literal["available", "empty", "unavailable"] = "unavailable"
    source: str = SOURCE
    source_url: str | None = None
    fetched_at: int
    currency: str | None = None
    # Último cierre usado: ningún horizonte posterior se da por vencido.
    as_of: str | None = None
    first_target_date: str | None = None
    targets_total: int = 0
    # Horizonte con menor error mediano en el backtest de ESTE ticker.
    best_horizon: HorizonKey | None = None
    horizons: list[HorizonSummary] = []
    consensus: SimpleConsensus | None = None
    rating_changes: RatingChanges | None = None
    min_samples: int = MIN_SAMPLES
    note: str | None = None
    note_code: Literal["fetch_failed", "not_equity", "no_history", "no_matured"] | None = None


# ---------------------------------------------------------------------------
# Normalización (pura)
# ---------------------------------------------------------------------------


def normalize_firm(raw: Any) -> str | None:
    name = _clean(raw)
    if name is None:
        return None
    return FIRM_ALIASES.get(name.lower(), name)


def _as_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.strip()).date()
        except ValueError:
            return None
    to_py = getattr(raw, "to_pydatetime", None)
    if callable(to_py):
        value = to_py()
        return value.date() if isinstance(value, datetime) else None
    return None


def split_factor_after(day: date, splits: list[tuple[date, float]]) -> float:
    """Producto de los splits con fecha posterior a ``day``.

    Yahoo da los objetivos tal y como se publicaron (sin ajustar), pero los
    cierres sí vienen ajustados por split: un objetivo de 1.275 $ de NVDA de
    mayo de 2024 equivale a 127,5 $ tras el split 10:1 de junio.
    """
    factor = 1.0
    for when, ratio in splits:
        if when > day and ratio > 0:
            factor *= ratio
    return factor


def normalize_targets(
    records: list[dict[str, Any]],
    splits: list[tuple[date, float]],
    first_trade: date | None = None,
) -> list[dict[str, Any]]:
    """Objetivos válidos, ajustados por split, uno por firma y día, en orden."""
    by_key: dict[tuple[str, date], dict[str, Any]] = {}
    for raw in sorted(records, key=lambda r: str(r.get("date"))):
        firm = normalize_firm(raw.get("firm"))
        day = _as_date(raw.get("date"))
        target = _positive(raw.get("price_target"))
        if firm is None or day is None or target is None:
            continue
        if first_trade is not None and day < first_trade:
            continue  # otro instrumento que usó el mismo ticker antes
        by_key[(firm, day)] = {
            "firm": firm,
            "date": day,
            "target": target / split_factor_after(day, splits),
        }
    return sorted(by_key.values(), key=lambda r: (r["date"], r["firm"]))


# ---------------------------------------------------------------------------
# Puntuación (pura, sin red)
# ---------------------------------------------------------------------------


class _Prices:
    def __init__(self, closes: list[tuple[date, float]]) -> None:
        clean = sorted((d, c) for d, c in closes if c is not None and c > 0)
        self.days = [d for d, _ in clean]
        self.closes = [c for _, c in clean]

    @property
    def last_day(self) -> date | None:
        return self.days[-1] if self.days else None

    def first_on_or_after(self, day: date) -> float | None:
        i = bisect_left(self.days, day)
        return self.closes[i] if i < len(self.days) else None

    def last_on_or_before(self, day: date) -> float | None:
        i = bisect_right(self.days, day) - 1
        return self.closes[i] if i >= 0 else None


def score_targets(
    targets: list[dict[str, Any]],
    closes: list[tuple[date, float]],
    today: date,
) -> dict[HorizonKey, list[dict[str, Any]]]:
    """Muestras vencidas por horizonte.

    Un objetivo publicado el día D vence a 6/12 meses cuando hay cierres hasta
    D+h (y D+h <= hoy). El precio al horizonte es el último cierre en o antes de
    D+h: ningún cierre posterior al horizonte entra en la cuenta.
    """
    prices = _Prices(closes)
    last = prices.last_day
    out: dict[HorizonKey, list[dict[str, Any]]] = {"6m": [], "12m": []}
    if last is None:
        return out
    horizon_end = min(last, today)
    for key, days in HORIZONS.items():
        rows: list[dict[str, Any]] = []
        for t in targets:
            end = t["date"] + timedelta(days=days)
            if end > horizon_end:
                continue
            p0 = prices.first_on_or_after(t["date"])
            ph = prices.last_on_or_before(end)
            if p0 is None or ph is None:
                continue
            logerr = math.log(t["target"] / ph)
            rows.append(
                {
                    **t,
                    "price_at_issue": p0,
                    "price_at_horizon": ph,
                    "logerr": logerr,
                    "abs": abs(logerr),
                    "err": t["target"] / ph - 1.0,
                    "dir_hit": ((t["target"] > p0) == (ph > p0) if t["target"] != p0 and ph != p0 else None),
                }
            )
        _add_relative(rows)
        out[key] = rows  # type: ignore[index]
    return out


def _add_relative(rows: list[dict[str, Any]]) -> None:
    """Error relativo: el propio menos la mediana de otras firmas en ±45 días."""
    days = [r["date"] for r in rows]  # ya ordenadas por fecha
    window = timedelta(days=PEER_WINDOW_DAYS)
    for row in rows:
        lo = bisect_left(days, row["date"] - window)
        hi = bisect_right(days, row["date"] + window)
        peers = [o["abs"] for o in rows[lo:hi] if o["firm"] != row["firm"]]
        row["rel"] = row["abs"] - median(peers) if len(peers) >= MIN_PEERS else None


def _weight(day: date, ref: date) -> float:
    return 0.5 ** ((ref - day).days / RECENCY_HALF_LIFE_DAYS)


def rank_firms(rows: list[dict[str, Any]]) -> list[FirmScore]:
    """Una puntuación por firma; las de muestra suficiente, de mejor a peor."""
    if not rows:
        return []
    ref = max(r["date"] for r in rows)
    rel_rows = [r for r in rows if r["rel"] is not None]
    # Media del ticker (ponderada por recencia) hacia la que se encoge.
    if rel_rows:
        weights = [_weight(r["date"], ref) for r in rel_rows]
        prior = sum(w * r["rel"] for w, r in zip(weights, rel_rows, strict=True)) / sum(weights)
    else:
        prior = 0.0
    firms: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        firms.setdefault(r["firm"], []).append(r)
    scores: list[FirmScore] = []
    for firm, items in firms.items():
        rel = [r for r in items if r["rel"] is not None]
        shrunk: float | None = None
        if rel:
            w = [_weight(r["date"], ref) for r in rel]
            shrunk = (
                sum(wi * r["rel"] for wi, r in zip(w, rel, strict=True)) + SHRINK_PSEUDO_SAMPLES * prior
            ) / (sum(w) + SHRINK_PSEUDO_SAMPLES)
        hits = [r["dir_hit"] for r in items if r["dir_hit"] is not None]
        latest = max(items, key=lambda r: r["date"])
        scores.append(
            FirmScore(
                firm=firm,
                samples=len(items),
                median_abs_error_pct=round(100 * median(abs(r["err"]) for r in items), 1),
                median_bias_pct=round(100 * median(r["err"] for r in items), 1),
                direction_hit_rate=round(sum(hits) / len(hits), 3) if hits else 0.0,
                relative_error=round(100 * shrunk, 2) if shrunk is not None else None,
                peer_scored_samples=len(rel),
                small_sample=len(rel) < MIN_SAMPLES,
                last_date=latest["date"].isoformat(),
                last_target=round(latest["target"], 2),
            )
        )
    return sorted(
        scores,
        key=lambda s: (
            s.small_sample,
            s.relative_error if s.relative_error is not None else math.inf,
            s.firm,
        ),
    )


def summarize_horizon(key: HorizonKey, rows: list[dict[str, Any]]) -> HorizonSummary:
    ranked = rank_firms(rows)
    ok = [s for s in ranked if not s.small_sample]
    # Con pocas firmas clasificadas, mitad arriba y mitad abajo: nunca la
    # misma firma en las dos listas.
    top = ok[: min(TOP_N, math.ceil(len(ok) / 2))]
    bottom = list(reversed(ok[len(top) :]))[:TOP_N]
    hits = [r["dir_hit"] for r in rows if r["dir_hit"] is not None]
    return HorizonSummary(
        horizon=key,
        months=6 if key == "6m" else 12,
        matured_targets=len(rows),
        median_abs_error_pct=round(100 * median(abs(r["err"]) for r in rows), 1) if rows else None,
        median_bias_pct=round(100 * median(r["err"] for r in rows), 1) if rows else None,
        direction_hit_rate=round(sum(hits) / len(hits), 3) if hits else None,
        ranked_firms=len(ok),
        small_sample_firms=len(ranked) - len(ok),
        top=top,
        bottom=bottom,
    )


def best_horizon(summaries: list[HorizonSummary]) -> HorizonKey | None:
    """El horizonte cuyo backtest da menor error mediano (con muestra mínima).

    A igualdad gana 12 meses, que es el plazo que declaran los objetivos.
    """
    usable = [s for s in summaries if s.matured_targets >= MIN_SAMPLES and s.median_abs_error_pct is not None]
    if not usable:
        return None
    best = min(usable, key=lambda s: (s.median_abs_error_pct, -s.months))
    return best.horizon


def simple_consensus(
    targets: list[dict[str, Any]], today: date, reference_price: float | None
) -> SimpleConsensus | None:
    """Media simple del último objetivo de cada firma de los últimos 12 meses."""
    since = today - timedelta(days=CONSENSUS_WINDOW_DAYS)
    latest: dict[str, float] = {}
    for t in targets:  # ordenados por fecha: el último pisa
        if since <= t["date"] <= today:
            latest[t["firm"]] = t["target"]
    if not latest:
        return None
    values = list(latest.values())
    mean = sum(values) / len(values)
    upside = round((mean / reference_price - 1.0) * 100, 1) if reference_price else None
    return SimpleConsensus(
        mean=round(mean, 2),
        median=round(median(values), 2),
        firms=len(values),
        reference_price=round(reference_price, 2) if reference_price else None,
        upside_percent=upside,
    )


def count_rating_changes(records: list[dict[str, Any]], today: date) -> RatingChanges:
    since = today - timedelta(days=RATING_CHANGE_WINDOW_DAYS)
    up = down = 0
    for r in records:
        day = _as_date(r.get("date"))
        if day is None or not since <= day <= today:
            continue
        action = (_clean(r.get("grade_action")) or "").lower()
        if action == "up":
            up += 1
        elif action == "down":
            down += 1
    return RatingChanges(upgrades=up, downgrades=down)


def build_history(
    symbol: str,
    records: list[dict[str, Any]],
    closes: list[tuple[date, float]],
    splits: list[tuple[date, float]],
    *,
    today: date,
    fetched_at: int,
    currency: str | None = None,
    first_trade: date | None = None,
) -> AnalystHistory:
    targets = normalize_targets(records, splits, first_trade)
    base = {
        "symbol": symbol,
        "source_url": SOURCE_URL.format(symbol=symbol),
        "fetched_at": fetched_at,
        "currency": currency,
    }
    if not targets:
        return AnalystHistory(
            **base,
            status="empty",
            note="Sin datos: no hay histórico de precios objetivo de analistas para este valor.",
            note_code="no_history",
        )
    prices = _Prices(closes)
    scored = score_targets(targets, closes, today)
    summaries = [summarize_horizon(k, scored[k]) for k in ("6m", "12m")]  # type: ignore[arg-type]
    reference = prices.last_on_or_before(today)
    result = AnalystHistory(
        **base,
        status="available",
        as_of=prices.last_day.isoformat() if prices.last_day else None,
        first_target_date=targets[0]["date"].isoformat(),
        targets_total=len(targets),
        best_horizon=best_horizon(summaries),
        horizons=summaries,
        consensus=simple_consensus(targets, today, reference),
        rating_changes=count_rating_changes(records, today),
    )
    if not any(s.matured_targets for s in summaries):
        result.note = "Aún no hay objetivos con 6 meses cumplidos para puntuar a las firmas."
        result.note_code = "no_matured"
    return result


# ---------------------------------------------------------------------------
# Red (Yahoo) y caché
# ---------------------------------------------------------------------------


def _fetch_history_records(symbol: str) -> list[dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(symbol).upgrades_downgrades
    records: list[dict[str, Any]] = []
    if frame is not None and len(frame) > 0:
        for index, item in frame.iterrows():
            records.append(
                {
                    "date": index,
                    "firm": item.get("Firm"),
                    "grade_action": item.get("Action"),
                    "price_target": item.get("currentPriceTarget"),
                }
            )
    return records


def _fetch_prices(symbol: str) -> dict[str, list[tuple[date, float]]]:
    import yfinance as yf

    frame: Any = yf.Ticker(symbol).history(period="max", auto_adjust=False, actions=True)
    closes: list[tuple[date, float]] = []
    splits: list[tuple[date, float]] = []
    if frame is not None and len(frame) > 0:
        for index, item in frame.iterrows():
            day = _as_date(index)
            if day is None:
                continue
            close = _positive(item.get("Close"))
            if close is not None:
                closes.append((day, close))
            ratio = _positive(item.get("Stock Splits"))
            if ratio is not None:
                splits.append((day, ratio))
    return {"closes": closes, "splits": splits}


def _fetch_sync(symbol: str) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = pool.submit(_fetch_history_records, symbol)
        prices = pool.submit(_fetch_prices, symbol)
        instrument = pool.submit(_fetch_currency_and_type, symbol)
        first_trade = pool.submit(_fetch_first_trade_date, symbol)
        declared = instrument.result()
        px = prices.result()
        return {
            "records": records.result(),
            "closes": px["closes"],
            "splits": px["splits"],
            "currency": declared["currency"],
            "quote_type": declared["quote_type"],
            "first_trade_date": first_trade.result(),
        }


class AnalystHistoryService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, AnalystHistory]] = {}

    async def get(self, symbol: str, *, today: date | None = None) -> AnalystHistory:
        key = symbol.strip().upper()
        now = time.time()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        fetched_at = int(now)
        try:
            data = await asyncio.wait_for(asyncio.to_thread(_fetch_sync, key), timeout=FETCH_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - Yahoo puede fallar; nunca se cachea un fallo
            return AnalystHistory(
                symbol=key,
                fetched_at=fetched_at,
                note="No se pudo consultar el histórico de analistas ahora; reintenta en unos minutos.",
                note_code="fetch_failed",
            )
        label = non_equity_label(data.get("quote_type"))
        if label is not None:
            result = AnalystHistory(
                symbol=key,
                status="empty",
                source_url=SOURCE_URL.format(symbol=key),
                fetched_at=fetched_at,
                currency=data.get("currency"),
                note=f"Sin datos: {key} está identificado como {label}, no como una acción.",
                note_code="not_equity",
            )
        else:
            result = await asyncio.to_thread(
                build_history,
                key,
                data.get("records") or [],
                data.get("closes") or [],
                data.get("splits") or [],
                today=today or date.today(),
                fetched_at=fetched_at,
                currency=data.get("currency"),
                first_trade=data.get("first_trade_date"),
            )
        self._cache[key] = (now, result)
        return result


analyst_history_service = AnalystHistoryService()
