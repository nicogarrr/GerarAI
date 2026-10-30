"""Sesiones bursatiles entre dos cierres guardados, sin calendario externo.

No hay calendario de mercado por bolsa en el repo (ni dependencia para ello).
Para saber si entre dos cierres guardados de una empresa falta una sesion se
usa un calendario lunes-viernes y, como prueba de festivo, los cierres de las
demas empresas de la misma bolsa (``market_prices`` es global):

- Ningun dia laborable entre los dos cierres: sesiones consecutivas.
- Algun otro valor de la misma bolsa tiene cierre en un dia laborable
  intermedio: ese dia hubo sesion y a esta empresa le falta.
- Los demas valores de la bolsa tienen cierre en ambas fechas y ninguno en
  medio: festivo de la bolsa (como mucho ``MAX_HOLIDAY_WEEKDAYS`` seguidos; mas
  dias sin ningun cierre es un hueco de datos, no un festivo).
- Sin otros valores de la bolsa con cierre en ambas fechas no hay prueba de
  festivo: cada dia laborable intermedio cuenta como sesion que falta.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice

# Cierres de mercado de mas de 2 dias laborables seguidos son excepcionales
# (Viernes Santo + Lunes de Pascua son 2); mas dias sin cierres es un hueco.
MAX_HOLIDAY_WEEKDAYS = 2

# Mismo calendario (NYSE) para todas las etiquetas de bolsa de EE. UU.
_US_EXCHANGES = frozenset({
    "NASDAQ", "NMS", "NGM", "NCM", "NYSE", "NYQ", "NYSEARCA", "PCX", "ARCA",
    "AMEX", "ASE", "BATS", "US",
})


def _exchange_group(exchange: str | None) -> frozenset[str]:
    key = (exchange or "").strip().upper()
    if not key:
        return frozenset()
    return _US_EXCHANGES if key in _US_EXCHANGES else frozenset({key})


def weekdays_between(previous: date, latest: date) -> list[date]:
    """Dias lunes-viernes estrictamente entre ``previous`` y ``latest``."""
    days: list[date] = []
    day = previous + timedelta(days=1)
    while day < latest:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def missing_sessions(
    db: Session, company: Company | None, previous: date, latest: date
) -> list[date]:
    """Sesiones de la bolsa de ``company`` sin cierre suyo entre dos cierres.

    Lista vacia = los dos cierres son sesiones consecutivas.
    """
    gap = weekdays_between(previous, latest)
    if not gap:
        return []
    group = _exchange_group(company.exchange if company is not None else None)
    if not group or company is None:
        return gap
    peers = (
        select(MarketPrice.date)
        .join(Company, Company.id == MarketPrice.company_id)
        .where(Company.exchange.in_(group), MarketPrice.company_id != company.id)
    )
    traded = set(db.scalars(peers.where(MarketPrice.date.in_(gap)).distinct()).all())
    if traded:
        return sorted(traded)
    # Festivo solo si la bolsa tiene otros valores con cierre en AMBAS fechas.
    bound_dates = peers.where(MarketPrice.date.in_([previous, latest])).subquery()
    bounds = db.scalar(select(func.count(func.distinct(bound_dates.c.date))))
    if bounds == 2 and len(gap) <= MAX_HOLIDAY_WEEKDAYS:
        return []
    return gap
