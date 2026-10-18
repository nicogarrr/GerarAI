"""Explicit on-demand refresh, persisted reads, no provider work in GET."""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, ConnectorState
from app.services.cnmv_mapping import resolve_issuer
from app.services.connectors.cnmv_shorts import fetch_positions
from app.services.connectors.short_interest import fetch_short_interest, fetch_short_volume
from app.services.data_health_service import utc

CONNECTOR = "public_shorts"


def _state(db: Session, company: Company) -> ConnectorState | None:
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise ValueError("Tenant context required")
    return db.scalar(select(ConnectorState).where(ConnectorState.tenant_id == tenant,
                     ConnectorState.company_id == company.id, ConnectorState.connector == CONNECTOR,
                     ConnectorState.feed_url == "public-shorts"))


def read_shorts(db: Session, company: Company) -> dict:
    state = _state(db, company)
    payload = state.metadata_ if state and isinstance(state.metadata_, dict) else {}
    stamp = utc(state.last_success_at) if state else None
    stale = bool(stamp and datetime.now(UTC) - stamp > timedelta(days=4))
    if payload.get("source") == "FINRA" and payload.get("date"):
        stale = stale or (datetime.now(UTC).date() - date.fromisoformat(payload["date"]) > timedelta(days=4))
    return {"ticker": company.ticker, "status": "degraded" if state and state.consecutive_errors else "stale" if stale else "available" if payload else "empty",
            "fetched_at": stamp.isoformat() if stamp else None, "data": payload or None,
            "reason": "No hay mapeo revisado para esta bolsa o empresa." if state and state.last_error == "UnsupportedMarket" else "La fuente no devolvió datos verificables; el dato anterior conserva su fecha." if state and state.consecutive_errors else "Consulta o fecha de negociación fuera del límite de 4 días." if stale else "No hay consulta almacenada. Usa Actualizar para consultar la fuente pública." if not payload else None}


async def refresh_shorts(db: Session, company: Company) -> dict:
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise ValueError("Tenant context required")
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(f"public-shorts:{tenant}:{company.id}".encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    state = _state(db, company)
    now = datetime.now(UTC)
    if state and state.last_started_at and now - utc(state.last_started_at) < timedelta(hours=1):
        return read_shorts(db, company)
    if state is None:
        state = ConnectorState(tenant_id=db.info["tenant_id"], company_id=company.id,
                               connector=CONNECTOR, feed_url="public-shorts")
        db.add(state)
    previous = dict(state.metadata_ or {})
    ticker, exchange = company.ticker, company.exchange.upper()
    issuer = resolve_issuer(ticker)
    state_id = state.id
    state.last_started_at = now
    db.commit()
    state_id = state_id or state.id
    # End any refresh SELECT transaction before awaiting a provider.
    db.commit()
    try:
        if issuer:
            payload = await fetch_positions(issuer)
        elif exchange in {"NASDAQ", "NYSE", "AMEX", "NYSEARCA", "NYSE ARCA", "US"} and "." not in ticker:
            async with httpx.AsyncClient(timeout=5) as client:
                row = await fetch_short_volume(ticker, client=client, lookback_days=4)
                interest = await fetch_short_interest(ticker, client=client)
            if row is None:
                raise ValueError("No FINRA row")
            if date.fromisoformat(row["date"]) > now.date():
                raise ValueError("Future FINRA trade date")
            payload = {**row, "short_interest": interest, "source": "FINRA", "kind": "OFICIAL", "ratio_kind": "DERIVADO",
                       "note": "Volumen corto diario fuera de bolsa, no posiciones abiertas ni porcentaje total del mercado. No implica sentimiento bajista por sí solo."}
        else:
            state.last_error = "UnsupportedMarket"
            state.consecutive_errors = (state.consecutive_errors or 0) + 1
            db.commit()
            return read_shorts(db, company)
        state = db.get(ConnectorState, state_id)
        state.metadata_ = payload
        state.last_success_at = now
        state.consecutive_errors = 0
        state.last_error = None
        emit_shorts_increase(db, company, previous, payload, now)
    except Exception as exc:  # noqa: BLE001 - never expose upstream strings/secrets
        state = db.get(ConnectorState, state_id)
        state.consecutive_errors = (state.consecutive_errors or 0) + 1
        state.last_error = type(exc).__name__
    db.commit()
    return read_shorts(db, company)



def emit_shorts_increase(db: Session, company: Company, previous: dict, current: dict, now: datetime) -> None:
    """Open positions only. Daily FINRA short volume is never a position signal."""
    from app.models import Position, WatchItem
    from app.services.review_alert_service import ReviewAlertService

    # Solo valores que el tenant sigue: abrir la ficha de cualquier ticker no
    # debe generar alertas de un valor que no está en cartera ni watchlist.
    held = db.scalar(select(Position.id).where(Position.company_id == company.id, Position.quantity > 0).limit(1))
    watched = db.scalar(select(WatchItem.id).where(func.upper(WatchItem.symbol) == company.ticker.upper()).limit(1))
    if held is None and watched is None:
        return
    parts = None
    message = None
    source_url = None
    if current.get("source") == "CNMV" and previous.get("source") == "CNMV":
        # Same set of public holders avoids treating disclosure-threshold entry
        # as a real increase in the market's total open short interest.
        old = {r["holder"]: r for r in previous.get("positions", [])}
        new = {r["holder"]: r for r in current.get("positions", [])}
        valid_dates = bool(old and old.keys() == new.keys())
        advanced = False
        observation_dates = []
        if valid_dates:
            for holder in old:
                try:
                    before_date = date.fromisoformat(old[holder]["position_date"])
                    after_date = date.fromisoformat(new[holder]["position_date"])
                except (ValueError, TypeError, KeyError):
                    valid_dates = False
                    break
                # Conservative alert policy: never infer a fresh increase from
                # future, stale or backward holder disclosures. Public CNMV
                # positions can remain legally current for longer; we keep
                # them in the panel but do not call them a fresh increase.
                if not (before_date <= after_date <= now.date()
                        and now.date() - after_date <= timedelta(days=35)):
                    valid_dates = False
                    break
                if new[holder]["percent"] != old[holder]["percent"] and after_date <= before_date:
                    valid_dates = False
                    break
                advanced = advanced or after_date > before_date
                observation_dates.append(after_date.isoformat())
        if valid_dates and advanced:
            before = previous.get("public_total_percent")
            after = current.get("public_total_percent")
            if before is not None and after is not None and after > before:
                message = (f"{company.ticker}: suma de posiciones cortas públicas CNMV "
                           f"{before:g}% → {after:g}% (fechas de posición {min(observation_dates)} a {max(observation_dates)}). Mismos titulares; solo posiciones públicas >=0,5%, no el total del mercado.")
                parts = ["CNMV", *[f"{k}:{v['position_date']}:{v['percent']}" for k, v in sorted(new.items())]]
                source_url = current.get("source_url")
    interest = current.get("short_interest")
    if isinstance(interest, dict):
        stamp = interest.get("settlement_date")
        try:
            settled = date.fromisoformat(str(stamp)[:10])
        except ValueError:
            settled = None
        before, after = interest.get("previous_short_interest"), interest.get("short_interest")
        if (settled and timedelta(0) <= now.date() - settled <= timedelta(days=35)
                and before is not None and before > 0 and after is not None and after > before):
            message = (f"{company.ticker}: posiciones cortas FINRA {before:,} → {after:,} acciones "
                       f"a {stamp}. No es volumen corto diario ni porcentaje del capital.")
            parts = ["FINRA", str(stamp), str(after), str(before)]
            source_url = interest.get("source_url")
    if parts and message and source_url:
        ReviewAlertService().emit_alert(
            db, company_id=company.id, alert_type="shorts_rising", severity="medium",
            title=f"Posiciones cortas en aumento: {company.ticker}", message=message,
            fingerprint_parts=["shorts_rising", str(company.id), *parts],
            metadata={"source_url": source_url, "observed_at": now.isoformat(), "kind": "DERIVADO"},
        )
