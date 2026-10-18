"""Market cap derivado cuando ningun proveedor lo cubre (QA: AENA/ASML N/D).

market_cap = ultimo precio (MarketPrice, cierre fechado, <= 7 dias) x
acciones en circulacion. Las acciones salen del shares_outstanding reportado
(SEC dei tras la cobertura de capital); para emisores ESEF sin conteo XBRL
(AENA: su filing 2024 no etiqueta acciones, medido) se derivan como
net_income / eps_diluted DEL MISMO ejercicio - media ponderada reportada,
no un conteo actual, y asi se declara.

El derivado es RESPALDO: un market_cap de proveedor (FMP_profile) nunca se
pisa. El hecho se escribe is_reported=False, source_type="derived", con la
fecha del precio como period y la divisa de la compania como unit. Sin
precio fresco o sin acciones: no se escribe nada (N/D honesto, nunca
inventado). Idempotente: cada refresco reemplaza los derivados anteriores.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import FinancialFact, MarketPrice
from app.models.entities import Company

MAX_PRICE_AGE = timedelta(days=7)
DERIVED_SOURCE = "derived"


def _latest_price(db: Session, company: Company, *, today: date) -> MarketPrice | None:
    return db.scalars(
        select(MarketPrice)
        .where(
            MarketPrice.company_id == company.id,
            MarketPrice.close > 0,
            MarketPrice.date >= today - MAX_PRICE_AGE,
        )
        .order_by(MarketPrice.date.desc())
        .limit(1)
    ).first()


def _latest_fact(db: Session, company: Company, metric: str) -> FinancialFact | None:
    return db.scalars(
        select(FinancialFact)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == metric,
            FinancialFact.is_reported.is_(True),
        )
        .order_by(FinancialFact.period.desc(), FinancialFact.id.desc())
        .limit(1)
    ).first()


def _vendor_market_cap_fresh(db: Session, company: Company, price_date: date) -> bool:
    """Hay market_cap de proveedor igual o mas reciente que nuestro precio."""
    vendor = db.scalars(
        select(FinancialFact)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
            FinancialFact.is_reported.is_(True),
            FinancialFact.source_type != DERIVED_SOURCE,
        )
        .order_by(FinancialFact.period.desc(), FinancialFact.id.desc())
        .limit(1)
    ).first()
    if vendor is None:
        return False
    try:
        return date.fromisoformat(str(vendor.period).split(":")[0]) >= price_date
    except ValueError:
        return False


def _shares_outstanding(db: Session, company: Company) -> tuple[Decimal, str] | None:
    """(acciones, base): reported SEC dei o derivado net_income/eps ESEF."""
    shares = _latest_fact(db, company, "shares_outstanding")
    if shares is not None and shares.value and Decimal(shares.value) > 0:
        return Decimal(shares.value), "reported_shares_outstanding"
    eps = _latest_fact(db, company, "eps_diluted")
    income = _latest_fact(db, company, "net_income")
    if (
        eps is not None
        and income is not None
        and eps.value
        and Decimal(eps.value) > 0
        and income.value
        and Decimal(income.value) > 0
        # Mismo ejercicio: mezclar anos seria inventar el cruce.
        and eps.fiscal_year is not None
        and eps.fiscal_year == income.fiscal_year
    ):
        return Decimal(income.value) / Decimal(eps.value), (
            f"derived_net_income_over_eps FY{eps.fiscal_year}"
        )
    return None


def refresh_derived_market_cap(
    db: Session, company: Company, *, today: date | None = None
) -> dict[str, Any]:
    """Escribe (o refresca) el market_cap derivado de una empresa."""
    today = today or datetime.now(UTC).date()
    tenant_id = db.info.get("tenant_id")
    tenant_filter = (
        FinancialFact.tenant_id == tenant_id
        if tenant_id is not None
        else FinancialFact.tenant_id.is_(None)
    )
    # Idempotencia: los derivados anteriores se reemplazan siempre.
    db.execute(
        delete(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
            FinancialFact.source_type == DERIVED_SOURCE,
            tenant_filter,
        )
    )
    price = _latest_price(db, company, today=today)
    if price is None:
        db.flush()
        return {"status": "unavailable", "reason": "no_fresh_price"}
    if _vendor_market_cap_fresh(db, company, price.date):
        db.flush()
        return {"status": "skipped", "reason": "vendor_market_cap_fresh"}
    shares = _shares_outstanding(db, company)
    if shares is None:
        db.flush()
        return {"status": "unavailable", "reason": "no_shares"}
    value, basis = shares
    market_cap = Decimal(price.close) * value
    db.add(
        FinancialFact(
            company_id=company.id,
            metric="market_cap",
            value=market_cap,
            unit=str(getattr(company, "currency", "") or "USD"),
            period=price.date.isoformat(),
            fiscal_year=None,
            fiscal_quarter=None,
            source_id=None,
            source_type=DERIVED_SOURCE,
            is_reported=False,
            is_adjusted=False,
            confidence=Decimal("0.70"),
        )
    )
    db.flush()
    return {
        "status": "ok",
        "market_cap": float(market_cap),
        "price_date": price.date.isoformat(),
        "price": float(price.close),
        "shares_basis": basis,
        "currency": str(getattr(company, "currency", "") or "USD"),
    }
