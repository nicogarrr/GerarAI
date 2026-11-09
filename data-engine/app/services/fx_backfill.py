"""Tipos de cambio que faltan para valorar una empresa, pedidos en el momento a las fuentes gratuitas del repo.

Caso real (9-nov-2026, tanda de tesis sobre la BD de pruebas): la tesis de TSM se paraba en «sin tipo de
cambio USD→TWD» porque la etapa FX del refresco de mercado solo pide las divisas de la cartera y del
seguimiento; una empresa que se valora sin estar en ninguna de las dos (o una BD sembrada solo con la
tabla del BCE) no tiene el tipo de su divisa de reporte, y lo mismo el lari de CGEO.L.

Ruta GENERAL, para cualquier divisa (nunca por emisor ni por divisa concreta):

1. Las divisas que la valoración necesita: las de reporte de sus hechos y la de cotización (subunidades
   como GBp → GBP).
2. Las que no tienen tipo guardado frente al euro con fecha ≤ hoy y como mucho ``MAX_AGE_DAYS`` días de
   antigüedad se piden al BCE (``eurofxref-daily``); las que el BCE no publica, al banco central emisor
   que el repo ya conoce (``official_fx``: NBG para GEL, CBC para TWD).
3. Se guardan como las filas del refresco (euros por 1 divisa, con su fuente y su fecha reales).
4. La que siga sin tipo queda en ``missing`` con su motivo: no se adivina ni se pone 1, y la valoración
   la mostrará como N/D con ese motivo.

Sin modelos: solo descargas públicas, una por fuente.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Company, FinancialFact
from app.services.connectors.official_fx import OFFICIAL_FEEDS
from app.services.portfolio_fx_service import TAX_CURRENCY, PortfolioFXService
from app.valuation.currency import normalize_currency, reporting_currencies

logger = logging.getLogger(__name__)

#: Un tipo más viejo que esto no sirve para la valoración de hoy: se vuelve a pedir.
MAX_AGE_DAYS = 10
PIVOT = TAX_CURRENCY  # el BCE publica contra el euro; ``convert_amount`` cruza por él


def company_currencies(db: Session, company: Company) -> set[str]:
    """Divisas que necesita la valoración: las de reporte de sus hechos y la de cotización."""
    units = db.scalars(
        select(FinancialFact.unit)
        .where(FinancialFact.company_id == company.id, *tenant_filters(db, FinancialFact))
        .distinct()
    ).all()
    found = reporting_currencies(units) | reporting_currencies([getattr(company, "currency", None)])
    return {(normalize_currency(c)[0] or c).upper() for c in found if c}


def missing_currencies(db: Session, currencies: set[str], *, as_of: date, max_age_days: int = MAX_AGE_DAYS
                       ) -> set[str]:
    """Las que no tienen tipo frente al pivote con fecha ≤ ``as_of`` y de menos de ``max_age_days`` días."""
    fx = PortfolioFXService()
    out: set[str] = set()
    for currency in {c.upper() for c in currencies} - {PIVOT}:
        found = fx.rate_with_provenance(db, quote_currency=currency, base_currency=PIVOT, as_of=as_of)
        stamp = (found or {}).get("rate_date")
        if found is None or (isinstance(stamp, date) and stamp < as_of - timedelta(days=max_age_days)):
            out.add(currency)
    return out


async def backfill(db: Session, currencies: set[str], *, as_of: date, refresh_service: Any = None
                   ) -> dict[str, Any]:
    """Pide y guarda los tipos de ``currencies`` (euros por 1 divisa). Nunca lanza.

    Devuelve ``{"written": [...], "missing": [{"currency", "reason"}]}``.
    """
    from app.services.market_refresh_service import MarketRefreshService

    wanted = {c.upper() for c in currencies} - {PIVOT}
    result: dict[str, Any] = {"written": [], "missing": []}
    if not wanted:
        return result
    service = refresh_service or MarketRefreshService()
    fx = PortfolioFXService()
    errors: list[dict] = []
    official = {c for c in wanted if c in OFFICIAL_FEEDS}
    try:
        snapshot = await service.fx_provider.fetch(
            base_currency=PIVOT, quote_currencies=wanted | ({"USD"} if official else set()))
    except Exception as exc:  # noqa: BLE001 - sin BCE, las divisas quedan sin tipo con el motivo
        reason = redact_secrets(f"BCE: {type(exc).__name__}: {str(exc)[:160]}")
        result["missing"] = [{"currency": c, "reason": reason} for c in sorted(wanted)]
        return result
    pending: set[str] = set()
    for currency in sorted(wanted):
        rate = snapshot.rates.get(currency)
        if rate is None:
            pending.add(currency)
            continue
        fx.upsert_rate(db, base_currency=PIVOT, quote_currency=currency, rate=rate,
                       rate_date=snapshot.rate_date, source="ECB")
        result["written"].append({"currency": currency, "source": "ECB", "rate_date": snapshot.rate_date.isoformat()})
    feeds = {c for c in pending if c in OFFICIAL_FEEDS}
    if feeds:
        before = set(feeds)
        await service._official_fx(db, fx, PIVOT, feeds, snapshot, as_of, errors)  # noqa: SLF001 - misma etapa
        still = missing_currencies(db, before, as_of=as_of)
        for currency in sorted(before - still):
            result["written"].append({"currency": currency, "source": OFFICIAL_FEEDS[currency].upper()})
        pending = (pending - before) | still
    for currency in sorted(pending):
        why = "; ".join(str(e.get("reason") or "") for e in errors if e.get("currency") == currency)
        if not why:
            why = ("ni el BCE ni ningún banco central emisor conocido publican esta divisa" if currency not in
                   OFFICIAL_FEEDS else "el banco central emisor no dio un tipo con fecha ≤ hoy")
        result["missing"].append({"currency": currency, "reason": redact_secrets(why)})
    db.flush()
    return result


def ensure_company_fx(db: Session, company: Company, *, as_of: date | None = None,
                      refresh_service: Any = None) -> dict[str, Any]:
    """Antes de valorar: los tipos que falten de sus divisas, pedidos y guardados. Nunca lanza."""
    from app.core.config import get_settings
    from app.services.async_bridge import run_from_any_context

    day = as_of or date.today()
    if refresh_service is None and getattr(get_settings(), "app_env", "") == "test":
        return {"written": [], "missing": [], "skipped": "app_env=test: sin red"}  # pruebas herméticas
    try:
        needed = missing_currencies(db, company_currencies(db, company), as_of=day)
        if not needed:
            return {"written": [], "missing": []}
        out = run_from_any_context(backfill(db, needed, as_of=day, refresh_service=refresh_service))
        db.commit()
        return out
    except Exception as exc:  # noqa: BLE001 - la valoración sigue y dirá qué tipo falta
        db.rollback()
        logger.warning("fx_backfill %s: %s", getattr(company, "ticker", "?"), type(exc).__name__)
        return {"written": [], "missing": [], "error": redact_secrets(f"{type(exc).__name__}: {str(exc)[:160]}")}


__all__ = ["MAX_AGE_DAYS", "backfill", "company_currencies", "ensure_company_fx", "missing_currencies"]
