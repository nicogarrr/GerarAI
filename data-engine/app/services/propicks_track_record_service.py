"""Track record vivo de ProPicks ("Ganadores anteriores") desde propick_snapshots.

Reglas de rotulado honesto (nada inventado, cada cifra con fuente y fecha):
- Entrada = mes del snapshot; precio de entrada = el congelado en el payload
  con la fecha en que se guardo.
- Precio actual = ultimo cierre en market_prices con su fecha; si tiene mas
  de 7 dias se reporta como sin dato actual (current_stale=true), nunca se
  muestra un precio viejo como si fuera el de hoy.
- Salida = el ticker deja de estar en el snapshot del mes siguiente; precio
  de salida = ultimo cierre persistido a fecha del as_of de ese snapshot.
- Columna fija de 90 dias desde la fecha del precio de entrada.
- Rentabilidades del pick con adj_close (entrada y final) cuando existe,
  como la de SPY; un split no se lee como caida. Sin adj_close: cierre vs
  precio congelado.
- vs SPY = serie diaria ingerida de Yahoo en benchmark_prices (job diario);
  si aun no hay filas, se usa la descarga directa con cache y se etiqueta la
  fuente; si tampoco hay, los campos vs SPY salen null.
- Sin agregado anual ni compuesto: con menos de 12 snapshots solo se expone
  "N meses de historial".
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice
from app.models.benchmark_price import BenchmarkPrice
from app.models.propick_snapshot import PropickSnapshot

SPY_SYMBOL = "SPY"
STALE_DAYS = 7
HORIZON_DAYS = 90
# Un cruce "a fecha de" acepta el ultimo cierre dentro de esta ventana; mas
# alla seria vender un precio de otro momento como el de esa fecha.
MATCH_TOLERANCE_DAYS = 10


def ingest_spy_prices(
    db: Session,
    *,
    period: str = "1y",
    fetcher: Callable[..., dict[str, list[Any]]] | None = None,
) -> dict[str, Any]:
    """Ingesta diaria de SPY (Yahoo, gratis) en benchmark_prices.

    Upsert por (symbol, date); devuelve barras escritas. La fuente queda
    registrada en cada fila.
    """
    if fetcher is None:
        from app.services.propicks_price_service import fetch_history_yfinance

        fetcher = fetch_history_yfinance
    history = fetcher([SPY_SYMBOL], period=period)
    bars = history.get(SPY_SYMBOL) or []
    written = 0
    for bar in bars:
        existing = db.scalar(
            select(BenchmarkPrice).where(
                BenchmarkPrice.symbol == SPY_SYMBOL,
                BenchmarkPrice.date == bar.day,
            )
        )
        if existing is not None:
            existing.close = bar.close
            existing.adj_close = bar.adj_close
            existing.source = "yfinance"
        else:
            db.add(
                BenchmarkPrice(
                    symbol=SPY_SYMBOL,
                    date=bar.day,
                    close=bar.close,
                    adj_close=bar.adj_close,
                    source="yfinance",
                )
            )
        written += 1
    db.commit()
    latest = db.scalar(
        select(BenchmarkPrice.date)
        .where(BenchmarkPrice.symbol == SPY_SYMBOL)
        .order_by(BenchmarkPrice.date.desc())
        .limit(1)
    )
    return {
        "status": "ok" if bars else "empty",
        "symbol": SPY_SYMBOL,
        "bars_written": written,
        "latest_date": latest.isoformat() if latest else None,
    }


def _spy_series(db: Session, cutoff: date) -> tuple[list[tuple[date, Decimal]], str]:
    """Serie SPY (fecha, precio) ascendente y su fuente.

    Preferimos la serie ingerida (adj_close si existe, close si no); si no
    hay filas, la descarga directa de Yahoo ya ajustada (cache de 6h); si ni
    una ni otra, lista vacia y los campos vs SPY salen null.
    """
    rows = db.scalars(
        select(BenchmarkPrice)
        .where(BenchmarkPrice.symbol == SPY_SYMBOL, BenchmarkPrice.date >= cutoff)
        .order_by(BenchmarkPrice.date)
    ).all()
    series = [
        (r.date, Decimal(str(r.adj_close if r.adj_close is not None else r.close)))
        for r in rows
        if (r.adj_close is not None and r.adj_close > 0) or (r.close is not None and r.close > 0)
    ]
    if series:
        return series, "yahoo (ingerido)"
    try:
        from app.services.portfolio_intelligence_service import _live_benchmark_prices

        live = _live_benchmark_prices(cutoff)
    except Exception:
        live = None
    if not live:
        return [], "sin_datos"
    return [(r.date, Decimal(str(r.adj_close))) for r in live if r.adj_close], "yahoo (directo)"


def _price_at_or_before(
    series: list[tuple[date, Decimal]], target: date, *, tolerance_days: int = MATCH_TOLERANCE_DAYS
) -> tuple[date, Decimal] | None:
    """Ultimo punto de la serie en target o antes, dentro de la tolerancia."""
    if not series:
        return None
    idx = bisect_right([d for d, _ in series], target) - 1
    if idx < 0:
        return None
    day, price = series[idx]
    if (target - day).days > tolerance_days:
        return None
    return day, price


def _latest_price(db: Session, company_id: int) -> MarketPrice | None:
    return db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id, MarketPrice.close.isnot(None))
        .order_by(MarketPrice.date.desc())
        .limit(1)
    )


class _PricePoint:
    """Fila de market_prices precargada (close/adj_close/date), misma lectura
    que el ORM para los consumidores de abajo."""

    __slots__ = ("date", "close", "adj_close")

    def __init__(self, day: date, close, adj_close) -> None:
        self.date = day
        self.close = close
        self.adj_close = adj_close


def _preload_prices(
    db: Session, company_ids: list[int], min_target: date
) -> dict[int, list[_PricePoint]]:
    """Un SELECT para todos los cierres que el track record puede necesitar.

    Sustituye los ~5 SELECTs por pick (entrada/salida/horizonte/actual).
    Cota inferior: el candidato de ``_price_at`` mas viejo que aun pasa la
    tolerancia (target - MATCH_TOLERANCE_DAYS). Lo mas antiguo fuera de la
    ventana nunca era elegible (tolerancia) salvo en ``_latest_price``: esa
    compañia sin filas en ventana cae en el fallback SQL de ``_series_latest``,
    que conserva el comportamiento exacto.
    """
    lower = min_target - timedelta(days=MATCH_TOLERANCE_DAYS)
    rows = db.execute(
        select(
            MarketPrice.company_id,
            MarketPrice.date,
            MarketPrice.close,
            MarketPrice.adj_close,
        )
        .where(
            MarketPrice.company_id.in_(company_ids),
            MarketPrice.close.isnot(None),
            MarketPrice.date >= lower,
        )
        .order_by(MarketPrice.company_id, MarketPrice.date)
    ).all()
    series: dict[int, list[_PricePoint]] = {}
    for company_id, day, close, adj_close in rows:
        series.setdefault(company_id, []).append(_PricePoint(day, close, adj_close))
    return series


def _series_price_at(points: list[_PricePoint], target: date) -> _PricePoint | None:
    """``_price_at`` en memoria: max fecha <= target, tolerancia identica."""
    idx = bisect_right([p.date for p in points], target) - 1
    if idx < 0:
        return None
    point = points[idx]
    if (target - point.date).days > MATCH_TOLERANCE_DAYS:
        return None
    return point


def _series_latest(
    db: Session, series: dict[int, list[_PricePoint]], company_id: int
) -> _PricePoint | MarketPrice | None:
    """``_latest_price`` en memoria; fallback SQL si la compañia no tiene
    cierres dentro de la ventana precargada (su ultimo cierre es mas viejo:
    mismo resultado que la consulta original, sin tolerancia)."""
    points = series.get(company_id)
    if points:
        return points[-1]
    return _latest_price(db, company_id)


def _price_at(db: Session, company_id: int, target: date) -> MarketPrice | None:
    row = db.scalar(
        select(MarketPrice)
        .where(
            MarketPrice.company_id == company_id,
            MarketPrice.close.isnot(None),
            MarketPrice.date <= target,
        )
        .order_by(MarketPrice.date.desc())
        .limit(1)
    )
    if row is not None and (target - row.date).days > MATCH_TOLERANCE_DAYS:
        return None
    return row


def _pct(end: Decimal | None, start: Decimal | None) -> float | None:
    if end is None or start is None or start <= 0:
        return None
    return float((end - start) / start)


def _pick_return(
    price_at,
    end_row,
    entry_price: Decimal | None,
    entry_price_date: date | None,
) -> float | None:
    """Rentabilidad del pick entre la entrada y ``end_row``.

    El precio de entrada congelado y ``close`` NO estan ajustados: un split
    entre ambas fechas (4:1 -> el cierre cae a la cuarta parte) se leia como
    una caida del 75 %. Si hay ``adj_close`` en la fecha de entrada y en la
    final, el precio congelado se lleva a la misma base ajustada con el factor
    de ajuste de su fecha (adj_close/close) y se compara con el ``adj_close``
    final: rentabilidad ajustada por splits y dividendos, la misma base que
    SPY. Se conserva el precio congelado como referencia (puede venir de otra
    hora o fuente que el cierre persistido). Sin adj_close en alguna de las
    dos fechas se mantiene el calculo anterior.
    """
    if (
        entry_price is not None
        and entry_price_date is not None
        and end_row.adj_close is not None
        and end_row.adj_close > 0
    ):
        entry_row = price_at(entry_price_date)
        if (
            entry_row is not None
            and entry_row.adj_close is not None
            and entry_row.adj_close > 0
            and entry_row.close is not None
            and entry_row.close > 0
        ):
            factor = Decimal(str(entry_row.adj_close)) / Decimal(str(entry_row.close))
            return _pct(Decimal(str(end_row.adj_close)), entry_price * factor)
    return _pct(Decimal(str(end_row.close)), entry_price)


def build_track_record(db: Session, *, today: date | None = None) -> dict[str, Any]:
    """Track record por pick a partir de los snapshots mensuales congelados."""
    today = today or date.today()
    snapshots = db.scalars(select(PropickSnapshot).order_by(PropickSnapshot.month)).all()
    if not snapshots:
        return {
            "snapshots_count": 0,
            "history_label": "sin snapshots mensuales todavia",
            "months": [],
            "stale_threshold_days": STALE_DAYS,
            "horizon_days": HORIZON_DAYS,
            "spy": {"available": False, "source": "sin_datos", "latest_date": None},
            "picks": [],
        }

    months = [s.month for s in snapshots]
    picks_by_month: list[dict[str, dict]] = [
        {p["ticker"]: p for p in (s.payload.get("picks") or []) if p.get("ticker")}
        for s in snapshots
    ]
    tickers = sorted({t for picks in picks_by_month for t in picks})
    companies = {
        c.ticker: c for c in db.scalars(select(Company).where(Company.ticker.in_(tickers))).all()
    } if tickers else {}

    entry_dates = [
        date.fromisoformat(p["price_date"])
        for picks in picks_by_month
        for p in picks.values()
        if p.get("price_date")
    ]
    cutoff = min(entry_dates) - timedelta(days=2 * MATCH_TOLERANCE_DAYS) if entry_dates else today - timedelta(days=400)
    spy, spy_source = _spy_series(db, cutoff)
    spy_latest_date = spy[-1][0].isoformat() if spy else None

    # Precarga por lotes de los cierres de todas las compañias del track
    # record: antes eran ~5 SELECTs por pick (855 ms medidos en el barrido
    # 2026-10-31); ahora 1 SELECT constante + lookups en memoria.
    price_targets: list[date] = []
    for idx, snapshot in enumerate(snapshots):
        next_snapshot = snapshots[idx + 1] if idx + 1 < len(snapshots) else None
        for ticker, pick in picks_by_month[idx].items():
            epd = date.fromisoformat(pick["price_date"]) if pick.get("price_date") else None
            if epd is not None:
                price_targets.append(epd)
                horizon_target = epd + timedelta(days=HORIZON_DAYS)
                if horizon_target <= today:
                    price_targets.append(horizon_target)
            if (
                next_snapshot is not None
                and ticker not in picks_by_month[idx + 1]
            ):
                price_targets.append(next_snapshot.as_of.date())
    series = _preload_prices(
        db,
        [c.id for c in companies.values()],
        min(price_targets) if price_targets else today,
    )

    rows: list[dict[str, Any]] = []
    for idx, snapshot in enumerate(snapshots):
        next_snapshot = snapshots[idx + 1] if idx + 1 < len(snapshots) else None
        next_tickers = set(picks_by_month[idx + 1]) if next_snapshot is not None else set()
        for ticker, pick in sorted(picks_by_month[idx].items()):
            company = companies.get(ticker)
            entry_price = Decimal(str(pick["price"])) if pick.get("price") else None
            entry_price_date = date.fromisoformat(pick["price_date"]) if pick.get("price_date") else None

            status = "activo" if next_snapshot is None or ticker in next_tickers else "salio"
            exit_month = exit_price = exit_price_date = None
            exit_pct = spy_pct_exit = None
            if status == "salio" and next_snapshot is not None:
                exit_month = next_snapshot.month
                exit_target = next_snapshot.as_of.date()
                if company is not None:
                    row = _series_price_at(series.get(company.id, []), exit_target)
                    if row is not None:
                        exit_price = float(row.close)
                        exit_price_date = row.date.isoformat()
                        exit_pct = _pick_return(
                            lambda target, cid=company.id: _series_price_at(
                                series.get(cid, []), target
                            ),
                            row,
                            entry_price,
                            entry_price_date,
                        )
                        spy_point = _price_at_or_before(spy, row.date)
                        spy_entry = _price_at_or_before(spy, entry_price_date) if entry_price_date else None
                        if spy_point and spy_entry:
                            spy_pct_exit = _pct(spy_point[1], spy_entry[1])

            current_price = current_price_date = None
            current_stale = False
            pct_since_entry = spy_pct_since_entry = None
            # En un pick que ya salio, el retorno "desde entrada" es el de la
            # salida; comparar con el precio de hoy mezclaria dos periodos.
            if status == "activo" and company is not None:
                latest = _series_latest(db, series, company.id)
                if latest is not None:
                    current_stale = (today - latest.date).days > STALE_DAYS
                    if not current_stale:
                        current_price = float(latest.close)
                        current_price_date = latest.date.isoformat()
                        pct_since_entry = _pick_return(
                            lambda target, cid=company.id: _series_price_at(
                                series.get(cid, []), target
                            ),
                            latest,
                            entry_price,
                            entry_price_date,
                        )
                        spy_point = _price_at_or_before(spy, latest.date)
                        spy_entry = _price_at_or_before(spy, entry_price_date) if entry_price_date else None
                        if spy_point and spy_entry:
                            spy_pct_since_entry = _pct(spy_point[1], spy_entry[1])
                    else:
                        current_price_date = latest.date.isoformat()

            pct_90d = spy_pct_90d = None
            horizon_date = None
            if entry_price_date is not None:
                horizon_target = entry_price_date + timedelta(days=HORIZON_DAYS)
                horizon_date = horizon_target.isoformat()
                if horizon_target <= today and company is not None:
                    row = _series_price_at(series.get(company.id, []), horizon_target)
                    if row is not None:
                        pct_90d = _pick_return(
                            lambda target, cid=company.id: _series_price_at(
                                series.get(cid, []), target
                            ),
                            row,
                            entry_price,
                            entry_price_date,
                        )
                        spy_point = _price_at_or_before(spy, row.date)
                        spy_entry = _price_at_or_before(spy, entry_price_date)
                        if spy_point and spy_entry:
                            spy_pct_90d = _pct(spy_point[1], spy_entry[1])

            rows.append(
                {
                    "ticker": ticker,
                    "name": pick.get("name") or (company.name if company else ticker),
                    "currency": pick.get("currency"),
                    "entry_month": snapshot.month,
                    "entry_price": float(entry_price) if entry_price is not None else None,
                    "entry_price_date": entry_price_date.isoformat() if entry_price_date else None,
                    "status": status,
                    "exit_month": exit_month,
                    "exit_price": exit_price,
                    "exit_price_date": exit_price_date,
                    "exit_pct": exit_pct,
                    "spy_pct_exit": spy_pct_exit,
                    "current_price": current_price,
                    "current_price_date": current_price_date,
                    "current_stale": current_stale,
                    "pct_since_entry": pct_since_entry,
                    "spy_pct_since_entry": spy_pct_since_entry,
                    "horizon_date": horizon_date,
                    "pct_90d": pct_90d,
                    "spy_pct_90d": spy_pct_90d,
                }
            )

    rows.sort(key=lambda r: (r["entry_month"], r["ticker"]), reverse=True)
    return {
        "snapshots_count": len(snapshots),
        "history_label": f"{len(snapshots)} {'mes' if len(snapshots) == 1 else 'meses'} de historial",
        "months": months,
        "stale_threshold_days": STALE_DAYS,
        "horizon_days": HORIZON_DAYS,
        "spy": {
            "available": bool(spy),
            "source": spy_source,
            "latest_date": spy_latest_date,
        },
        "picks": rows,
    }
