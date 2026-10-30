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

Escritura acotada (revision auditor 19-oct-2026): se calcula SIEMPRE el
valor actual y solo se escribe cuando difiere de lo almacenado (valor,
divisa, periodo o ajuste) o cuando una fila identica supera DERIVED_TTL
(6h). Una fila erronea se corrige en la primera lectura aunque sea
fresca: el TTL acota reescrituras, nunca blinda un valor malo. Si el
respaldo pierde su base (sin precio fresco, sin acciones o con cap de
proveedor fresco) el derivado se BORRA: un valor viejo servido como
vigente es peor que un N/D. Al refrescar se ACTUALIZA la fila existente
en vez de delete+insert y se borran los duplicados: dos GET a la vez
convergen en la misma fila y no nacen filas gemelas (la carrera residual
del primer derivado simultaneo la repara el siguiente refresco). El
barrido nocturno llama con ttl=None: sin reescrituras de filas
identicas; escribe solo cuando algo cambia.

Los recuentos de acciones son de la fecha de SU hecho y el precio es de
hoy: si hubo un split entre ambos, el cap sale desplazado por el factor
(caso real medido en prod 19-oct-2026: AENA, split 10:1 tras el FY2025 -
precio post-split 25,70 x acciones pre-split 153M = 3,93B en vez de
~39,3B; el PER ya lo corregia, el cap no). Misma regla que el PER y que
long_term_model_service: se multiplica por el factor acumulado de los
splits posteriores al cierre del periodo del hecho; sin CorporateAction
registrado, factor 1 (nunca se adivina). El ajuste se declara:
is_adjusted=True y la base lo nombra.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import FinancialFact, MarketPrice
from app.models.entities import Company
from app.services.price_units import close_in_company_currency
from app.services.split_adjustment import (
    cumulative_split_factor_after,
    period_end_date,
    split_events_by_company,
)
from app.valuation.engines.base import ADR_TAG_PREFIX, adr_ratio

MAX_PRICE_AGE = timedelta(days=7)
DERIVED_SOURCE = "derived"
# Frescura de un derivado para NO reescribirlo: un backup calculado no
# cambia mas rapido que sus entradas (cierre diario + hechos anuales).
DERIVED_TTL = timedelta(hours=6)


def _derived_rows(db: Session, company: Company, tenant_filter) -> list[FinancialFact]:
    return list(db.scalars(
        select(FinancialFact)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
            FinancialFact.source_type == DERIVED_SOURCE,
            tenant_filter,
        )
        .order_by(FinancialFact.updated_at.desc(), FinancialFact.id.desc())
    ).all())


def _age(updated_at: datetime, now: datetime) -> timedelta:
    # SQLite devuelve datetimes naive aunque la columna sea tz-aware.
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return now - updated_at


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
    row = db.scalars(
        select(FinancialFact).options(selectinload(FinancialFact.source))
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == metric,
            FinancialFact.is_reported.is_(True),
        )
        .order_by(FinancialFact.period.desc(), FinancialFact.id.desc())
        .limit(1)
    ).first()

    from app.services.esef_fact_quarantine import fact_quarantine_reason

    return row if row is None or not fact_quarantine_reason(row) else None


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


def _split_note(factor: Decimal) -> str:
    return "" if factor == 1 else f", acciones ajustadas por split x{factor.normalize():f}"


def _shares_outstanding(
    db: Session, company: Company
) -> tuple[Decimal, str, Decimal] | None:
    """(acciones actuales, base, factor split): reported SEC dei o derivado
    net_income/eps ESEF. El recuento se expresa en acciones ACTUALES: se
    multiplica por el factor acumulado de los splits posteriores al cierre
    del periodo del hecho (misma regla que long_term_model_service y que
    el ajuste de EPS del PER)."""
    events = split_events_by_company(db, [company.id]).get(company.id, [])
    shares = _latest_fact(db, company, "shares_outstanding")
    if shares is not None and shares.value and Decimal(shares.value) > 0:
        factor = cumulative_split_factor_after(events, period_end_date(shares.period))
        return Decimal(shares.value) * factor, (
            "reported_shares_outstanding" + _split_note(factor)
        ), factor
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
        # El periodo del EPS ancla el factor (mismo ejercicio que el
        # net_income por la guarda de arriba).
        factor = cumulative_split_factor_after(events, period_end_date(eps.period))
        return Decimal(income.value) / Decimal(eps.value) * factor, (
            f"derived_net_income_over_eps FY{eps.fiscal_year}" + _split_note(factor)
        ), factor
    return None


def refresh_derived_market_cap(
    db: Session,
    company: Company,
    *,
    today: date | None = None,
    ttl: timedelta | None = DERIVED_TTL,
) -> dict[str, Any]:
    """Escribe (o refresca) el market_cap derivado de una empresa."""
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC)
    tenant_id = db.info.get("tenant_id")
    tenant_filter = (
        FinancialFact.tenant_id == tenant_id
        if tenant_id is not None
        else FinancialFact.tenant_id.is_(None)
    )
    existing = _derived_rows(db, company, tenant_filter)
    newest = existing[0] if existing else None

    def _drop_derived() -> None:
        # Sin base el respaldo se BORRA, no se conserva: servir un valor
        # viejo como vigente es peor que un N/D (revision auditor).
        for row in existing:
            db.delete(row)
        db.flush()

    price = _latest_price(db, company, today=today)
    if price is None:
        _drop_derived()
        return {"status": "unavailable", "reason": "no_fresh_price"}
    if _vendor_market_cap_fresh(db, company, price.date):
        _drop_derived()
        return {"status": "skipped", "reason": "vendor_market_cap_fresh"}
    shares = _shares_outstanding(db, company)
    if shares is None:
        _drop_derived()
        return {"status": "unavailable", "reason": "no_shares"}
    value, basis, split_factor = shares
    # El cap va en la divisa de la compania; un cierre cotizado en otra
    # divisa (SHEL.L en GBp con cuentas en USD) se convierte con FX
    # point-in-time. Sin tipo valido: N/D, nunca peniques etiquetados USD.
    close = close_in_company_currency(
        db, Decimal(price.close), quote_currency=price.quote_currency,
        company=company, on=price.date,
    )
    if close is None:
        _drop_derived()
        return {"status": "unavailable", "reason": "no_fx_for_quote_currency"}
    # Un ADR cotiza por ADR (N ordinarias) y las acciones del filing son
    # ORDINARIAS: precio x acciones salia N veces inflado (BABA 8:1, un cap
    # de billones). Precio por ordinaria = cierre del ADR / N. Ficha marcada
    # ADR sin ratio valido: N/D, nunca un cap con la base equivocada.
    ratio = adr_ratio(company)
    if ratio is None and any(
        str(tag).strip().lower() == "adr" or str(tag).strip().lower().startswith(ADR_TAG_PREFIX)
        for tag in (company.factor_tags or [])
    ):
        _drop_derived()
        return {"status": "unavailable", "reason": "adr_ratio_unknown"}
    if ratio:
        close = close / Decimal(str(ratio))
    # La columna es Numeric(24,6): sin cuantizar a 6 decimales lo calculado
    # (una division larga) nunca iguala lo almacenado y cada GET reescribe
    # (medido con AENA: dos refrescos seguidos devolvian ok, no skipped).
    market_cap = (close * value).quantize(Decimal("0.000001"))
    unit = str(getattr(company, "currency", "") or "USD")
    period = price.date.isoformat()
    adjusted = split_factor != 1
    if newest is not None:
        same = (
            # Postgres Numeric(24,6) devuelve Decimal exacto; SQLite devuelve
            # float y a magnitudes grandes su redondeo supera el quantum
            # (medido: 39,3B -> 1,1e-6). 1e-4 es ordenes de magnitud menor
            # que cualquier cambio real (un tick x acciones >= miles).
            abs(Decimal(newest.value) - market_cap) <= Decimal("0.0001")
            and newest.unit == unit
            and newest.period == period
            and bool(newest.is_adjusted) == adjusted
        )
        # Solo se escribe si el valor cambio (una fila erronea se corrige
        # en la primera lectura) o si una fila identica supera el TTL.
        if same and (ttl is None or _age(newest.updated_at, now) < ttl):
            return {"status": "skipped", "reason": "fresh_derived"}
        # Update-in-place: sin delete+insert no hay ventana sin fila ni
        # duplicados por GET concurrentes.
        newest.value = market_cap
        newest.unit = unit
        newest.period = period
        newest.is_adjusted = adjusted
        newest.confidence = Decimal("0.70")
    else:
        db.add(
            FinancialFact(
                company_id=company.id,
                metric="market_cap",
                value=market_cap,
                unit=unit,
                period=period,
                fiscal_year=None,
                fiscal_quarter=None,
                source_id=None,
                source_type=DERIVED_SOURCE,
                is_reported=False,
                is_adjusted=adjusted,
                confidence=Decimal("0.70"),
            )
        )
    # Reparacion de duplicados (p. ej. dos primeros refrescos concurrentes):
    # se conserva la fila mas reciente y el resto se borra.
    for extra in existing[1:]:
        db.delete(extra)
    db.flush()
    return {
        "status": "ok",
        "market_cap": float(market_cap),
        "price_date": price.date.isoformat(),
        "price": float(close),
        "quote_currency": price.quote_currency,
        "shares_basis": basis,
        "split_factor": float(split_factor),
        "adr_ratio": ratio,
        "currency": str(getattr(company, "currency", "") or "USD"),
    }
