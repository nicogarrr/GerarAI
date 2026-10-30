"""Dated, tenant-scoped digest of held symbols. Related news is not causal proof."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice, NewsEvent, PortfolioMoveDigest, Position
from app.services.trading_sessions import missing_sessions

VERSION = "current-holdings-adjusted-moves-v4"
DAILY_BAR_SOURCES = frozenset({"yfinance"})


def build_digest(db: Session, as_of: date, generated_at: datetime | None = None) -> PortfolioMoveDigest:
    if db.info.get("tenant_id") is None:
        raise ValueError("Tenant context required")
    generated_at = generated_at or datetime.now(UTC)
    # An as-of day that has not finished in UTC cannot be called a completed close.
    if generated_at.tzinfo is None or as_of >= generated_at.astimezone(UTC).date():
        raise ValueError("Only prior completed UTC dates may be summarized")
    positions = db.scalars(select(Position).where(Position.quantity > 0).order_by(Position.id)).all()
    items = []
    for position in positions:
        company = db.get(Company, position.company_id)
        if not company:
            continue
        prices = db.scalars(select(MarketPrice).where(
            MarketPrice.company_id == company.id,
            MarketPrice.date <= as_of,
            MarketPrice.date >= as_of - timedelta(days=8),
            MarketPrice.source.in_(DAILY_BAR_SOURCES),
            MarketPrice.adj_close.is_not(None),
        ).order_by(desc(MarketPrice.date)).limit(2)).all()
        current = prices[0] if prices and prices[0].date == as_of and prices[0].adj_close and prices[0].adj_close > 0 else None
        prior = prices[1] if current and len(prices) > 1 and prices[1].adj_close and prices[1].adj_close > 0 else None
        item = {"position_id": position.id, "company_id": company.id, "ticker": company.ticker,
                "quantity": str(position.quantity), "date": as_of.isoformat(), "status": "sin datos",
                "catalyst": "sin catalizador identificado", "related_news": []}
        # Variacion de UNA sesion: si entre el cierre anterior guardado y el
        # de as_of falta una sesion de la bolsa (no festivo), el cociente es un
        # movimiento de varias sesiones; no se presenta como el del dia.
        gap = missing_sessions(db, company, prior.date, current.date) if current and prior else []
        if gap:
            item.update(status="hueco de sesión", previous_date=prior.date.isoformat(),
                        missing_sessions=[day.isoformat() for day in gap])
        elif current and prior:
            # Adjusted closes, not quoted closes: splits and distributions
            # must not become a spurious portfolio-movement signal.
            change_pct = (Decimal(current.adj_close) / Decimal(prior.adj_close) - 1) * 100
            item.update(status="disponible", adjusted_close=str(current.adj_close),
                        previous_adjusted_close=str(prior.adj_close),
                        previous_date=prior.date.isoformat(), price_change_pct=round(float(change_pct), 4),
                        return_basis="cierres ajustados yfinance; variación del valor, no P&L de la posición",
                        price_source=current.source, previous_price_source=prior.source,
                        price_ids=[prior.id, current.id])
            # GDELT articles retain publisher domain as source and independently
            # carry connector provenance; neither proximity nor coverage proves cause.
            start = datetime.combine(as_of, time.min, tzinfo=UTC)
            end = start + timedelta(days=1)
            # Filtro connector en SQL ANTES del LIMIT: si se filtra en Python
            # tras el LIMIT, 5 noticias RSS/manual recientes ocultan todas las
            # GDELT del día aunque existan.
            news = db.scalars(select(NewsEvent).where(
                NewsEvent.company_id == company.id, NewsEvent.date >= start, NewsEvent.date < end,
                NewsEvent.url.is_not(None),
                NewsEvent.metadata_["connector"].as_string() == "gdelt",
            ).order_by(desc(NewsEvent.date)).limit(5)).all()
            item["related_news"] = [{"id": row.id, "title": row.title, "url": row.url,
                                    "source": row.source, "connector": "gdelt", "published_at": row.date.isoformat()}
                                   for row in news]
        else:
            item["missing"] = ["barra diaria ajustada fechada" if not current else "barra diaria anterior"]
        items.append(item)
    coverage = "sin posiciones" if not items else "completa" if all(item["status"] == "disponible" for item in items) else "parcial"
    checksum = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(PortfolioMoveDigest).where(
        PortfolioMoveDigest.tenant_id == db.info["tenant_id"],
        PortfolioMoveDigest.digest_date == as_of, PortfolioMoveDigest.version == VERSION,
        PortfolioMoveDigest.input_hash == checksum,
    ))
    if previous:
        return previous
    digest = PortfolioMoveDigest(tenant_id=db.info["tenant_id"], digest_date=as_of,
                                 version=VERSION, input_hash=checksum, items=items,
                                 coverage=coverage, generated_at=generated_at)
    db.add(digest)
    db.commit()
    db.refresh(digest)
    return digest


def latest_digest(db: Session) -> dict:
    if db.info.get("tenant_id") is None:
        raise ValueError("Tenant context required")
    digest = db.scalar(select(PortfolioMoveDigest).where(
        PortfolioMoveDigest.tenant_id == db.info["tenant_id"],
    ).order_by(desc(PortfolioMoveDigest.digest_date), desc(PortfolioMoveDigest.id)).limit(1))
    if digest is None:
        return {"status": "sin datos", "items": [], "coverage": "sin datos"}
    age = (datetime.now(UTC).date() - digest.digest_date).days
    return {"status": "obsoleto" if age > 4 else "disponible", "date": digest.digest_date.isoformat(),
            "generated_at": digest.generated_at.isoformat(), "version": digest.version,
            "coverage": digest.coverage, "items": digest.items,
            "universe": "posiciones actuales al generar el digest; no cartera histórica del día del cierre",
            "positions_sampled_at": digest.generated_at.isoformat(),
            "note": "Variación calculada con cierres ajustados; noticias relacionadas por fecha, no atribución causal; sin catalizador identificado."}
