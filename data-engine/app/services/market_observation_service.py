"""Free, dated FRED observations; no query-time vendor traffic."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketObservation
from app.services.connectors.fred import FREDClient

FRED_SERIES = {
    "mortgage_30y_us": ("MORTGAGE30US", "porcentaje", 14),
    "treasury_10y_us": ("DGS10", "porcentaje", 5),
    "treasury_2y_us": ("DGS2", "porcentaje", 5),
    "breakeven_10y_us": ("T10YIE", "porcentaje", 5),
    "high_yield_spread_us": ("BAMLH0A0HYM2", "puntos porcentuales", 5),
    "vix_us": ("VIXCLS", "índice", 5),
}


def parse_points(rows: list[dict]) -> list[tuple[date, Decimal]]:
    points: dict[date, Decimal] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row["date"]))
            value = Decimal(str(row["value"]))
            if value.is_finite():
                points[day] = value
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return sorted(points.items())


def store_series(db: Session, key: str, rows: list[dict], fetched_at: datetime) -> dict:
    if key not in FRED_SERIES or fetched_at.tzinfo is None:
        raise ValueError("Serie u hora inválida")
    series_id, unit, _ = FRED_SERIES[key]
    added = 0
    revisions = 0
    points = [(d, v) for d, v in parse_points(rows) if d <= fetched_at.astimezone(UTC).date()]
    days = [d for d, _ in points]
    # Lote único por serie (anti N+1): la última observación «observed» de
    # cada día y los pares (día, vintage) existentes salen de dos consultas en
    # vez de dos POR PUNTO (~800 por serie y refresco). Mismos filtros que el
    # chequeo anterior: el de vintage no lleva geography/source/status.
    latest_by_day: dict[date, MarketObservation] = {}
    existing_vintages: set[tuple[date, str]] = set()
    if days:
        for row in db.scalars(
            select(MarketObservation).where(
                MarketObservation.metric_key == key,
                MarketObservation.geography == "US",
                MarketObservation.source == "FRED",
                MarketObservation.observation_date.in_(days),
                MarketObservation.status == "observed",
            ).order_by(
                MarketObservation.observation_date,
                MarketObservation.fetched_at.desc(),
                MarketObservation.id.desc(),
            )
        ).all():
            latest_by_day.setdefault(row.observation_date, row)
        existing_vintages = set(
            db.execute(
                select(MarketObservation.observation_date, MarketObservation.vintage).where(
                    MarketObservation.metric_key == key,
                    MarketObservation.observation_date.in_(days),
                )
            ).all()
        )
    for day, value in points:
        previous = latest_by_day.get(day)
        if previous and previous.value == value:
            continue
        if previous:
            # FRED's new CSV value is a sourced revision. Append, never overwrite:
            # old snapshots retain their input IDs and historical knowledge time.
            revisions += 1
            vintage = fetched_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + hashlib.sha256(str(value).encode()).hexdigest()[:12]
        else:
            vintage = "initial"
        status = "observed"
        if (day, vintage) in existing_vintages:
            continue
        existing_vintages.add((day, vintage))
        db.add(
            MarketObservation(
                metric_key=key,
                geography="US",
                observation_date=day,
                value=value,
                unit=unit,
                source="FRED",
                source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                fetched_at=fetched_at,
                vintage=vintage,
                status=status,
            )
        )
        db.flush()
        added += 1
    return {"added": added, "revisions_applied": revisions}


async def refresh_fred(db: Session, client: FREDClient | None = None) -> dict:
    client = client or FREDClient()
    outcome: dict = {"series": {}, "errors": {}}
    for key, (series_id, _, _) in FRED_SERIES.items():
        try:
            payload = await client.series_csv(series_id, limit=800)
            if not parse_points(payload.get("observations") or []):
                outcome["errors"][key] = "sin datos"
                continue
            outcome["series"][key] = store_series(db, key, payload["observations"], datetime.now(UTC))
            db.commit()
        except (httpx.HTTPError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            db.rollback()
            outcome["errors"][key] = type(exc).__name__
    return outcome
