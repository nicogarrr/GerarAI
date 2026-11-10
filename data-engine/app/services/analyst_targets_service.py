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
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

SOURCE = "Yahoo Finance (no oficial), agregado de analistas"
SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}/analysis/"
# 1h: movimientos de analistas del día (p.ej. reiteraciones) deben llegar a
# ficha y listas el mismo día; Yahoo sigue marcando la latencia real de ingesta.
CACHE_TTL_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 12.0
# Presupuesto de la pasada de prensa: corre en paralelo a Yahoo, así que no
# suma a la latencia salvo que Yahoo termine antes (caso típico: símbolo sin
# cobertura). La prensa es un complemento de mejor esfuerzo: al agotarse el
# presupuesto el panel devuelve solo Yahoo, nunca falla por la prensa.
PRESS_TIMEOUT_SECONDS = 9.0
# Segunda pasada de prensa (consultas por firma envejecida), tras Yahoo.
PRESS_FIRM_TIMEOUT_SECONDS = 6.0
# Presupuesto TOTAL de la petición con press=1 (Yahoo + ambas pasadas de
# prensa): el front corta a 14 s, así que la segunda pasada solo corre con el
# tiempo que quede; si no llega, se devuelve lo de Yahoo (o la primera
# pasada) sin ruido. Medido por el auditor: sin deadline, el peor caso eran
# ~18 s y el panel no llegaba a pintar.
TOTAL_BUDGET_SECONDS = 12.5
# Una fila de Yahoo más vieja que esto dispara la consulta por firma en prensa.
STALE_FIRM_DAYS = 7
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
    # Enlace al artículo cuando la fila viene de prensa (con press=1); las
    # filas de Yahoo no llevan enlace por fila, solo el panel (source_url).
    source_url: str | None = None


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
    # Codigos estables de los textos de arriba: el front los traduce con sus
    # diccionarios (es/en). `note` y `reference_price_source` siguen en
    # castellano por compatibilidad; con la app en ingles se pintaban tal cual.
    reference_price_source_code: Literal["market_at_fetch"] | None = None
    consensus: AnalystConsensus | None = None
    rows: list[AnalystTargetRow] = []
    note: str | None = None
    note_code: Literal["fetch_failed", "not_equity", "consensus_only", "no_targets", "with_press"] | None = None
    # Tipo de instrumento que declara Yahoo (ETF, MUTUALFUND...) cuando no es
    # una accion; acompana a note_code="not_equity" para traducir la nota.
    instrument_type: str | None = None


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
    listed_from: date | None = None,
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
        if when.toordinal() < cutoff_ordinal or (listed_from is not None and when < listed_from):
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

    from app.services.analyst_yahoo import fetch_upgrades_downgrades_records

    return [
        {
            "date": record["date"],
            "firm": record["firm"],
            "rating": record["to_grade"],
            "action": record["price_target_action"],
            "price_target": record["price_target"],
            "prior_target": record["prior_target"],
        }
        for record in fetch_upgrades_downgrades_records(yf.Ticker(symbol))
    ]


def _fetch_consensus(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    try:
        return dict(yf.Ticker(symbol).analyst_price_targets or {})
    except Exception:  # noqa: BLE001 - el consenso es accesorio
        return {}


# Tipos de instrumento que Yahoo declara en fast_info (misma lectura de
# metadatos que la divisa) y su nombre para la persona usuaria. Solo una
# accion (EQUITY) tiene precios objetivo de analistas con sentido: un ETF,
# fondo o indice no es una empresa cubierta por analistas, y aceptar el
# simbolo tal cual mostraba objetivos de OTRO instrumento con el mismo ticker
# El antiguo SPCX del ETF ahora es SPCK; SPCX corresponde a SpaceX desde
# 2026-06-12. No se bloquea un ticker por su identidad historica.
# https://nasdaqtrader.com/TraderNews.aspx?id=DTN2026-8
_NON_EQUITY_LABEL = {
    "ETF": "un ETF",
    "MUTUALFUND": "un fondo",
    "INDEX": "un índice",
    "CURRENCY": "una divisa",
    "CRYPTOCURRENCY": "una criptomoneda",
    "FUTURE": "un futuro",
    "OPTION": "una opción",
}


def non_equity_label(quote_type: str | None) -> str | None:
    """Nombre legible si el instrumento NO es una accion; None si lo es o no se sabe."""
    if not quote_type:
        return None
    normalized = quote_type.strip().upper()
    if normalized == "EQUITY":
        return None
    return _NON_EQUITY_LABEL.get(normalized, f"un instrumento de tipo {normalized}")


def _fetch_currency_and_type(symbol: str) -> dict[str, str | None]:
    import yfinance as yf

    # Divisa y tipo se leen por separado: si quoteType falla (yfinance cambia
    # sus claves a menudo), la divisa sigue valiendo y viceversa.
    currency: str | None = None
    quote_type: str | None = None
    # nosemgrep: gerarai-broad-except-pass -- sin metadatos de yfinance ambos quedan None
    try:
        fast_info = yf.Ticker(symbol).fast_info
    except Exception:  # noqa: BLE001 - ambos son declarativos; sin ellos, None
        return {"currency": None, "quote_type": None}
    # nosemgrep: gerarai-broad-except-pass -- divisa declarativa: sin ella queda None
    try:
        raw_currency = fast_info.get("currency")
        if raw_currency:
            raw = str(raw_currency).strip()
            # Yahoo cotiza Londres en peniques ("GBp") y Johannesburgo en centavos
            # ("ZAc"): los objetivos vienen en esa subunidad. Poner .upper() daba
            # "GBP" y los precios salian x100. Se distingue con un codigo propio.
            currency = _SUBUNIT_CURRENCY.get(raw) or raw.upper() or None
    except Exception:  # noqa: BLE001 - declarativa; sin ella, None
        currency = None
    # nosemgrep: gerarai-broad-except-pass -- tipo declarativo: sin el queda None
    try:
        raw_type = fast_info.get("quoteType")
        quote_type = str(raw_type).strip().upper() if raw_type else None
    except Exception:  # noqa: BLE001 - declarativo; sin el, None
        quote_type = None
    return {"currency": currency, "quote_type": quote_type}


def _first_trade_date(raw: Any) -> date | None:
    """Fecha de la primera sesión del listado tal y como la declara Yahoo.

    Según la versión de yfinance llega como ``datetime``/``Timestamp`` con zona,
    como segundos epoch o como texto ISO. Cualquier otra cosa es ``None``.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if hasattr(raw, "date") and callable(raw.date):
        try:
            value = raw.date()
        except Exception:  # noqa: BLE001 - tipo raro: sin fecha
            return None
        return value if isinstance(value, date) else None
    if isinstance(raw, (int, float)):
        if not math.isfinite(raw) or raw <= 0:
            return None
        try:
            return datetime.fromtimestamp(raw, tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _fetch_first_trade_date(symbol: str) -> date | None:
    """Primera sesión del listado actual (``firstTradeDate`` del chart de Yahoo).

    Un ticker puede haber sido de otro instrumento antes (SPCX fue un ETF hasta
    que SpaceX empezó a cotizar con ese símbolo el 2026-06-12, Nasdaq
    DTN2026-8). Las filas de analistas anteriores a la primera sesión del
    listado actual no pueden ser de esta empresa. Sin dato, ``None`` y no se
    filtra nada (comportamiento anterior).
    """
    import yfinance as yf

    try:
        metadata = yf.Ticker(symbol).get_history_metadata() or {}
    except Exception:  # noqa: BLE001 - metadato accesorio; sin él no se filtra
        return None
    if not isinstance(metadata, dict):
        return None
    return _first_trade_date(metadata.get("firstTradeDate"))


def _fetch_sync(symbol: str) -> dict[str, Any]:
    # Las tres lecturas de Yahoo son independientes y cada una paga sus
    # propios round-trips (cookie/crumb + endpoint): en serie la celda
    # "Obj. analistas" de la watchlist tardaba ~8 s en asentar (medido en
    # prod con CGEO.L, 19 oct 2026). En paralelo el total es el maximo de
    # las tres, no la suma. Tickers separados: una sola instancia comparte
    # estado de sesion y no es segura entre hilos.
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = pool.submit(_fetch_records, symbol)
        consensus = pool.submit(_fetch_consensus, symbol)
        instrument = pool.submit(_fetch_currency_and_type, symbol)
        first_trade = pool.submit(_fetch_first_trade_date, symbol)
        declared = instrument.result()
        return {
            "records": records.result(),
            "consensus": consensus.result(),
            "currency": declared["currency"],
            "quote_type": declared["quote_type"],
            "first_trade_date": first_trade.result(),
        }


def merge_press_rows(
    rows: list[AnalystTargetRow],
    press_targets: list[Any],
    *,
    reference_price: float | None,
    currency: str | None,
) -> list[AnalystTargetRow]:
    """Filas de Yahoo fusionadas con notas de prensa, última por firma.

    Una nota de prensa solo reemplaza la fila de Yahoo de su firma cuando es
    MÁS reciente (a igual fecha gana Yahoo, fuente estructurada). La divisa
    marcada en la frase debe resolver a la declarada por Yahoo para el
    listado: sin divisa declarada o con marca incompatible, la fila de prensa
    se descarta (nunca se mezclan divisas). El consenso agregado no se toca.
    """
    from app.services.analyst_targets_press import currency_matches

    merged = {row.firm.casefold(): row for row in rows}
    for target in press_targets:
        if not currency_matches(target.currency_mark, currency, target.currency_mentions):
            continue
        key = target.firm.casefold()
        current = merged.get(key)
        if current is not None and current.date >= target.date.isoformat():
            continue
        merged[key] = AnalystTargetRow(
            firm=target.firm,
            date=target.date.isoformat(),
            rating=target.rating,
            action=target.action,
            price_target=target.price_target,
            prior_target=target.prior_target,
            upside_percent=(
                round((target.price_target / reference_price - 1) * 100, 1) if reference_price else None
            ),
            source=target.outlet,
            source_url=target.url,
        )
    ordered = sorted(merged.values(), key=lambda row: (row.date, row.firm), reverse=True)
    return ordered[:MAX_ROWS]


class AnalystTargetsService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, AnalystTargets]] = {}

    async def get(self, symbol: str, *, press: bool = False,
                  deadline: float | None = None) -> AnalystTargets:
        key = symbol.strip().upper()
        # La variante con prensa se cachea aparte: la celda de listas (sin
        # press) y la ficha (con press) no comparten entrada.
        cache_key = f"{key}|press" if press else key
        now = time.time()
        hit = self._cache.get(cache_key)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        fetched_at = int(now)
        # Presupuesto de espera compartido con la ruta (fallback de listado
        # incluido): limita lo que el endpoint ESPERA; el to_thread de Yahoo
        # sigue trabajando en segundo plano tras el timeout. Con el
        # presupuesto agotado no hay fase de prensa ni espera mínima: solo
        # Yahoo al instante (timeout 0).
        deadline = deadline if deadline is not None else time.monotonic() + TOTAL_BUDGET_SECONDS
        press_targets: list[Any] = []
        if press and deadline - time.monotonic() > 0:
            from app.services.analyst_targets_press import fetch_press_targets

            remaining = deadline - time.monotonic()
            data, found = await asyncio.gather(
                asyncio.wait_for(
                    asyncio.to_thread(_fetch_sync, key),
                    timeout=min(FETCH_TIMEOUT_SECONDS, remaining),
                ),
                asyncio.wait_for(
                    fetch_press_targets(key, today=datetime.now(UTC).date()),
                    timeout=min(PRESS_TIMEOUT_SECONDS, remaining),
                ),
                return_exceptions=True,
            )
            if isinstance(found, list):
                press_targets = found
            # Prensa fallida o agotada: panel igual que antes, sin ruido.
        else:
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_sync, key),
                    timeout=min(FETCH_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic())),
                )
            except Exception:  # noqa: BLE001 - Yahoo puede fallar; nunca se cachea un fallo
                data = None
        if not isinstance(data, dict):
            return AnalystTargets(
                symbol=key,
                fetched_at=fetched_at,
                note="No se pudo consultar el consenso ahora; reintenta en unos minutos.",
                note_code="fetch_failed",
            )
        # Guard de identidad: si Yahoo dice que el ticker NO es una accion
        # (ETF, fondo, indice...), sus "objetivos de analistas" pertenecen a
        # otro instrumento con el mismo ticker. Mostrarlos en la ficha de la
        # empresa seria un dato inventado por confusion de identidad.
        label = non_equity_label(data.get("quote_type"))
        if label is not None:
            result = AnalystTargets(
                symbol=key,
                status="empty",
                source_url=SOURCE_URL.format(symbol=key),
                fetched_at=fetched_at,
                currency=data.get("currency"),
                note=(
                    f"El valor {key} está identificado como {label}, no como una "
                    "acción, así que no hay precios objetivo de analistas que "
                    "mostrar para una empresa con este ticker."
                ),
                note_code="not_equity",
                instrument_type=(data.get("quote_type") or "").strip().upper() or None,
            )
            self._cache[cache_key] = (now, result)
            return result
        consensus_raw = data["consensus"]
        reference = _positive(consensus_raw.get("current"))
        # Filas anteriores a la primera sesión del listado actual son de otro
        # instrumento que usó el mismo ticker (p. ej. el ETF que era SPCX antes
        # de SpaceX, Nasdaq DTN2026-8): fuera, para todos los tickers, con la
        # fecha que declara Yahoo. Nunca se reasignan al ticker nuevo del ETF.
        first_trade = data.get("first_trade_date")
        rows = normalize_rows(
            data["records"], reference_price=reference,
            listed_from=first_trade if isinstance(first_trade, date) else None,
        )
        consensus = AnalystConsensus(
            low=_positive(consensus_raw.get("low")),
            high=_positive(consensus_raw.get("high")),
            mean=_positive(consensus_raw.get("mean")),
            median=_positive(consensus_raw.get("median")),
        )
        has_consensus = any(
            value is not None for value in (consensus.low, consensus.high, consensus.mean, consensus.median)
        )
        if press:
            # Segunda pasada de prensa con consultas por firma para las casas
            # cuya fila de Yahoo va envejecida: Bing posiciona mejor
            # «"ASTS" "Cantor Fitzgerald"» que la consulta general. Presupuesto
            # acotado para no pasar el timeout del front; sin tiempo, se
            # devuelve lo de la primera pasada (o solo Yahoo).
            today = datetime.now(UTC).date()
            cutoff = (today - timedelta(days=STALE_FIRM_DAYS)).isoformat()
            stale_firms = [row.firm for row in rows if row.date < cutoff]
            remaining = deadline - time.monotonic()
            if stale_firms and remaining > 0.75:
                from app.services.analyst_targets_press import fetch_press_targets, firm_queries

                # nosemgrep: gerarai-broad-except-pass -- prensa de mejor esfuerzo: sin ella o sin tiempo, el panel devuelve Yahoo tal cual
                try:
                    more = await asyncio.wait_for(
                        fetch_press_targets(key, today=today, queries=firm_queries(key, stale_firms)),
                        timeout=min(PRESS_FIRM_TIMEOUT_SECONDS, remaining),
                    )
                    press_targets = [*press_targets, *more]
                except Exception:  # noqa: BLE001 - mejor esfuerzo: sin tiempo, Yahoo tal cual
                    pass
        if press_targets:
            rows = merge_press_rows(
                rows, press_targets, reference_price=reference, currency=data.get("currency")
            )
        # Disponible tambien con SOLO consenso agregado (sin detalle por firma,
        # p.ej. PNG.V): el consenso es dato real y se etiqueta como agregado.
        note_code: Literal["consensus_only", "no_targets", "with_press"] | None
        if any(row.source != SOURCE for row in rows):
            note, note_code = (
                "Incluye notas de prensa recientes con su medio, fecha y enlace.",
                "with_press",
            )
        elif rows:
            note, note_code = None, None
        elif has_consensus:
            note, note_code = "Solo hay consenso agregado, sin detalle por firma.", "consensus_only"
        else:
            note, note_code = "No hay precios objetivo por analista para este valor.", "no_targets"
        result = AnalystTargets(
            symbol=key,
            status="available" if rows or has_consensus else "empty",
            source_url=SOURCE_URL.format(symbol=key),
            fetched_at=fetched_at,
            currency=data.get("currency"),
            reference_price=reference,
            reference_price_source="fuente de mercado, precio al obtener los datos" if reference else None,
            reference_price_source_code="market_at_fetch" if reference else None,
            consensus=consensus if has_consensus else None,
            rows=rows,
            note=note,
            note_code=note_code,
        )
        self._cache[cache_key] = (now, result)
        return result


analyst_targets_service = AnalystTargetsService()
