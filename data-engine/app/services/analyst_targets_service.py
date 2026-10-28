"""Precios objetivo por analista (firma, fecha, objetivo) desde Yahoo Finance.

Fuente gratuita y no oficial: `yfinance.Ticker.upgrades_downgrades` devuelve por
firma y fecha el objetivo actual y el anterior. No es una API contratada, asi
que cada fila lleva fuente y fecha, la respuesta lleva la hora de obtencion y
un fallo o un simbolo sin cobertura da una lista vacia con `status`, nunca
datos inventados ni rellenados con otras fuentes.
"""

from __future__ import annotations

import asyncio
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel

SOURCE = "Yahoo Finance (no oficial), agregado de analistas"
SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}/analysis/"
# 1h: movimientos de analistas del día (p.ej. reiteraciones) deben llegar a
# ficha y listas el mismo día; Yahoo sigue marcando la latencia real de ingesta.
CACHE_TTL_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 12.0
MAX_AGE_DAYS = 365
MAX_ROWS = 25


class AnalystTargetRow(BaseModel):
    firm: str
    date: str
    rating: str | None = None
    action: str | None = None
    price_target: float
    prior_target: float | None = None
    # (objetivo / precio de referencia - 1) * 100, solo con precio de referencia.
    upside_percent: float | None = None
    source: str = SOURCE


class AnalystConsensus(BaseModel):
    low: float | None = None
    high: float | None = None
    mean: float | None = None
    median: float | None = None


class AnalystTargets(BaseModel):
    symbol: str
    status: Literal["available", "empty", "unavailable"] = "unavailable"
    source: str = SOURCE
    source_url: str | None = None
    fetched_at: int
    # Divisa declarada por Yahoo para el listado consultado; sin ella la UI
    # pinta el numero pelado y no calcula recorrido (nunca se mezclan divisas).
    currency: str | None = None
    reference_price: float | None = None
    reference_price_source: str | None = None
    consensus: AnalystConsensus | None = None
    rows: list[AnalystTargetRow] = []
    note: str | None = None


# Subunidades que Yahoo distingue solo por mayusculas/minusculas.
_SUBUNIT_CURRENCY = {"GBp": "GBX", "ZAc": "ZAC"}


def _positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_rows(
    records: list[dict[str, Any]],
    *,
    reference_price: float | None,
    today: date | None = None,
) -> list[AnalystTargetRow]:
    """Ultima fila con objetivo por firma, de los ultimos 12 meses, mas reciente primero.

    Filas sin objetivo positivo, sin firma o sin fecha legible se descartan:
    sin fecha o sin cifra no hay nada que mostrar. El objetivo anterior 0 de
    Yahoo significa "sin objetivo previo" y se devuelve como ausente.
    """
    cutoff_ordinal = (today or datetime.now(UTC).date()).toordinal() - MAX_AGE_DAYS
    latest: dict[str, AnalystTargetRow] = {}
    for record in records:
        firm = _clean(record.get("firm"))
        target = _positive(record.get("price_target"))
        raw_date = record.get("date")
        if firm is None or target is None or raw_date is None:
            continue
        try:
            when = raw_date.date() if hasattr(raw_date, "date") else date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if when.toordinal() < cutoff_ordinal:
            continue
        key = firm.casefold()
        current = latest.get(key)
        if current is not None and current.date >= when.isoformat():
            continue
        prior = _positive(record.get("prior_target"))
        latest[key] = AnalystTargetRow(
            firm=firm,
            date=when.isoformat(),
            rating=_clean(record.get("rating")),
            action=_clean(record.get("action")),
            price_target=target,
            prior_target=prior,
            upside_percent=(
                round((target / reference_price - 1) * 100, 1) if reference_price else None
            ),
        )
    rows = sorted(latest.values(), key=lambda row: (row.date, row.firm), reverse=True)
    return rows[:MAX_ROWS]


def _fetch_records(symbol: str) -> list[dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(symbol).upgrades_downgrades
    records: list[dict[str, Any]] = []
    if frame is not None and len(frame) > 0:
        for index, item in frame.iterrows():
            records.append(
                {
                    "date": index,
                    "firm": item.get("Firm"),
                    "rating": item.get("ToGrade"),
                    "action": item.get("priceTargetAction"),
                    "price_target": item.get("currentPriceTarget"),
                    "prior_target": item.get("priorPriceTarget"),
                }
            )
    return records


def _fetch_consensus(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    try:
        return dict(yf.Ticker(symbol).analyst_price_targets or {})
    except Exception:  # noqa: BLE001 - el consenso es accesorio
        return {}


def _fetch_currency(symbol: str) -> str | None:
    import yfinance as yf

    # nosemgrep: gerarai-broad-except-pass -- divisa declarativa de yfinance: sin ella queda None (comentario en linea)
    try:
        raw_currency = yf.Ticker(symbol).fast_info.get("currency")
        if raw_currency:
            raw = str(raw_currency).strip()
            # Yahoo cotiza Londres en peniques ("GBp") y Johannesburgo en centavos
            # ("ZAc"): los objetivos vienen en esa subunidad. Poner .upper() daba
            # "GBP" y los precios salian x100. Se distingue con un codigo propio.
            return _SUBUNIT_CURRENCY.get(raw) or raw.upper() or None
    except Exception:  # noqa: BLE001 - la divisa es declarativa; sin ella, None
        pass
    return None


def _fetch_sync(symbol: str) -> dict[str, Any]:
    # Las tres lecturas de Yahoo son independientes y cada una paga sus
    # propios round-trips (cookie/crumb + endpoint): en serie la celda
    # "Obj. analistas" de la watchlist tardaba ~8 s en asentar (medido en
    # prod con CGEO.L, 19 oct 2026). En paralelo el total es el maximo de
    # las tres, no la suma. Tickers separados: una sola instancia comparte
    # estado de sesion y no es segura entre hilos.
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = pool.submit(_fetch_records, symbol)
        consensus = pool.submit(_fetch_consensus, symbol)
        currency = pool.submit(_fetch_currency, symbol)
        return {
            "records": records.result(),
            "consensus": consensus.result(),
            "currency": currency.result(),
        }


class AnalystTargetsService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, AnalystTargets]] = {}

    async def get(self, symbol: str) -> AnalystTargets:
        key = symbol.strip().upper()
        now = time.time()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        fetched_at = int(now)
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(_fetch_sync, key), timeout=FETCH_TIMEOUT_SECONDS
            )
        except Exception:  # noqa: BLE001 - Yahoo puede fallar; nunca se cachea un fallo
            return AnalystTargets(
                symbol=key,
                fetched_at=fetched_at,
                note="No se pudo consultar Yahoo Finance ahora; reintenta en unos minutos.",
            )
        consensus_raw = data["consensus"]
        reference = _positive(consensus_raw.get("current"))
        rows = normalize_rows(data["records"], reference_price=reference)
        consensus = AnalystConsensus(
            low=_positive(consensus_raw.get("low")),
            high=_positive(consensus_raw.get("high")),
            mean=_positive(consensus_raw.get("mean")),
            median=_positive(consensus_raw.get("median")),
        )
        has_consensus = any(
            value is not None for value in (consensus.low, consensus.high, consensus.mean, consensus.median)
        )
        # Disponible tambien con SOLO consenso agregado (sin detalle por firma,
        # p.ej. PNG.V): el consenso es dato real y se etiqueta como agregado.
        if rows:
            note = None
        elif has_consensus:
            note = "Yahoo Finance publica solo el consenso agregado, sin detalle por firma."
        else:
            note = "Yahoo Finance no publica precios objetivo por analista para este valor."
        result = AnalystTargets(
            symbol=key,
            status="available" if rows or has_consensus else "empty",
            source_url=SOURCE_URL.format(symbol=key),
            fetched_at=fetched_at,
            currency=data.get("currency"),
            reference_price=reference,
            reference_price_source="Yahoo Finance, precio al obtener los datos" if reference else None,
            consensus=consensus if has_consensus else None,
            rows=rows,
            note=note,
        )
        self._cache[key] = (now, result)
        return result


analyst_targets_service = AnalystTargetsService()
