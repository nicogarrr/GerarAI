"""Informe tipo analista: datos de mercado y cifras reales por periodo.

Vista de solo lectura para ``GET /api/companies/{ticker}/analyst-report``.
Junta lo que ya guarda GerarAI, sin inventar nada:

* **Datos de mercado**: último cierre propio (``market_prices``), volumen medio
  de las últimas 63 sesiones con volumen, acciones (en circulación y diluidas
  del último periodo, con la misma regla de :mod:`app.services.ttm_service`),
  capitalización = cierre × acciones y EV = capitalización + deuda − caja
  (solo si deuda y caja son del MISMO cierre y su divisa es la del precio).
* **Cifras reales**: ingresos y EBITDA por ejercicio y trimestre. EBITDA =
  resultado operativo + amortizaciones del mismo periodo (SEC/ESEF); si falta
  alguno, el EBITDA que traiga la fuente (FMP...) con su nombre; si no, vacío.
  Un Q4 que no se presenta se deriva como FY − Q1 − Q2 − Q3 y se marca.

Las estimaciones del usuario NO salen de aquí: viven en su desglose por partes
y su tesis, y la ficha las pinta etiquetadas como suyas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, FinancialFact
from app.models.entities import MarketPrice
from app.services.esef_fact_quarantine import fact_quarantine_reason
from app.services.financial_ingestion_service import SOURCE_PRIORITY
from app.services.holding_nav import latest_published_nav
from app.services.split_adjustment import split_events_by_company
from app.services.ttm_service import _is_segment, _period_end, compute_company_ttm
from app.valuation.currency import normalize_currency

REPORT_VERSION = "analyst-report-v1"
AVG_VOLUME_SESSIONS = 63  # ~3 meses de sesiones
ANNUAL_PERIODS = 4
QUARTER_PERIODS = 6
_QUARTERS = ("Q1", "Q2", "Q3", "Q4")
FLOW_METRICS = ("revenue", "operating_income", "depreciation_amortization", "ebitda")
_POINT_METRICS = ("shares_outstanding", "shares_diluted", "cash_and_equivalents", "total_debt")


@dataclass(frozen=True)
class FactRow:
    """Un hecho ya filtrado (sin segmentos ni cuarentena)."""

    metric: str
    kind: str  # "FY" | "Q"
    quarter: str  # "FY" | "Q1".."Q4"
    end: date
    value: Decimal
    unit: str
    reported: bool
    source: str
    rank: tuple[float, float]
    derived: bool = False


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def best_rows(rows: list[FactRow]) -> dict[tuple[str, str, date], FactRow]:
    """Por (métrica, FY/Q, cierre) gana la mejor fuente y, a empate, la ingesta más nueva."""
    best: dict[tuple[str, str, date], FactRow] = {}
    for row in rows:
        key = (row.metric, row.kind, row.end)
        if key not in best or row.rank < best[key].rank:
            best[key] = row
    return best


def _cell(row: FactRow | None, *, basis: str = "reported") -> dict | None:
    if row is None:
        return None
    return {
        "value": _num(row.value),
        "unit": row.unit,
        "source": row.source,
        "reported": row.reported and not row.derived,
        "basis": basis,
        "derived_q4": row.derived,
    }


def _derive_q4(best: dict[tuple[str, str, date], FactRow], metric: str) -> None:
    """Q4 = FY − Q1 − Q2 − Q3 cuando el 10-K no trae el cuarto trimestre."""
    for (m, kind, fy_end), annual in list(best.items()):
        if m != metric or kind != "FY":
            continue
        # Q1-Q3 del MISMO ejercicio: el Q1 cierra ~273 días antes del FY (también en
        # años de 52/53 semanas); el Q4 del ejercicio anterior (~365 días) queda fuera.
        start = fy_end - timedelta(days=300)
        inside = sorted(
            (row for (mm, kk, end), row in best.items() if mm == metric and kk == "Q" and start < end <= fy_end),
            key=lambda row: row.end,
        )
        if any(row.end == fy_end for row in inside) or len(inside) != 3:
            continue
        if {row.quarter for row in inside} != {"Q1", "Q2", "Q3"} or {row.unit for row in inside} != {annual.unit}:
            continue
        q4_end = fy_end
        best[(metric, "Q", q4_end)] = FactRow(
            metric=metric, kind="Q", quarter="Q4", end=q4_end,
            value=annual.value - sum((row.value for row in inside), Decimal("0")),
            unit=annual.unit, reported=False, source=annual.source, rank=annual.rank, derived=True,
        )


def _ebitda(best: dict[tuple[str, str, date], FactRow], kind: str, end: date) -> dict | None:
    op = best.get(("operating_income", kind, end))
    da = best.get(("depreciation_amortization", kind, end))
    if op is not None and da is not None and op.unit == da.unit:
        return {
            "value": _num(op.value + abs(da.value)),
            "unit": op.unit,
            "source": op.source,
            "reported": op.reported and da.reported and not (op.derived or da.derived),
            "basis": "operating_income_plus_da",
            "derived_q4": op.derived or da.derived,
        }
    return _cell(best.get(("ebitda", kind, end)), basis="source_ebitda")


def build_estimates(rows: list[FactRow], *, annual: int = ANNUAL_PERIODS, quarters: int = QUARTER_PERIODS) -> dict:
    """Ingresos y EBITDA reales por ejercicio (últimos ``annual``) y trimestre (últimos ``quarters``)."""
    best = best_rows(rows)
    for metric in FLOW_METRICS:
        _derive_q4(best, metric)

    def periods(kind: str, limit: int) -> list[dict[str, Any]]:
        ends = sorted({end for (m, k, end) in best if k == kind and m in FLOW_METRICS}, reverse=True)[:limit]
        out = []
        for end in sorted(ends):
            quarter = "FY"
            if kind == "Q":
                quarter = next((best[(m, "Q", end)].quarter for m in FLOW_METRICS if (m, "Q", end) in best), "Q")
            revenue = _cell(best.get(("revenue", kind, end)))
            ebitda = _ebitda(best, kind, end)
            if revenue is None and ebitda is None:
                continue
            out.append({"period_end": end, "fiscal_quarter": quarter, "revenue": revenue, "ebitda": ebitda})
        return out

    return {"annual": periods("FY", annual), "quarterly": periods("Q", quarters)}


def build_market(
    *,
    price: Decimal | None,
    price_date: date | None,
    price_currency: str | None,
    volumes: list[int],
    points: dict[str, Any],
) -> dict:
    """Bloque de datos de mercado. ``points`` = TtmValue de acciones, caja y deuda."""

    def point(metric: str) -> dict | None:
        item = points.get(metric)
        if item is None or item.value is None:
            return None
        return {"value": _num(item.value), "unit": item.unit, "period_end": item.period_end,
                "provenance": item.provenance}

    shares = point("shares_outstanding")
    diluted = point("shares_diluted")
    cash = point("cash_and_equivalents")
    debt = point("total_debt")
    avg_volume = round(sum(volumes) / len(volumes)) if volumes else None
    major_currency, price_divisor = normalize_currency(price_currency)
    market_cap = None
    market_cap_basis = None
    if price is not None and price > 0:
        major_price = price / price_divisor
        if shares and shares["value"] and shares["value"] > 0:
            market_cap, market_cap_basis = float(major_price) * shares["value"], "shares_outstanding"
        elif diluted and diluted["value"] and diluted["value"] > 0:
            market_cap, market_cap_basis = float(major_price) * diluted["value"], "shares_diluted"
    enterprise_value = None
    ev_reason = None
    if market_cap is None:
        ev_reason = "no_market_cap"
    elif cash is None or debt is None:
        ev_reason = "missing_cash_or_debt"
    elif cash["period_end"] != debt["period_end"]:
        ev_reason = "cash_debt_different_dates"
    elif not major_currency or normalize_currency(cash["unit"])[0] != major_currency or normalize_currency(debt["unit"])[0] != major_currency:
        ev_reason = "currency_mismatch"
    else:
        enterprise_value = (
            market_cap + debt["value"] / normalize_currency(debt["unit"])[1]
            - cash["value"] / normalize_currency(cash["unit"])[1]
        )
    return {
        "price": _num(price),
        "price_date": price_date,
        "currency": price_currency,
        "avg_volume": avg_volume,
        "avg_volume_sessions": len(volumes),
        "shares_outstanding": shares,
        "shares_diluted": diluted,
        "market_cap": market_cap,
        "market_cap_basis": market_cap_basis,
        "market_cap_currency": major_currency,
        "enterprise_value_currency": major_currency,
        "cash": cash,
        "total_debt": debt,
        "enterprise_value": enterprise_value,
        "enterprise_value_reason": ev_reason,
    }


def _fact_rows(facts: list[FinancialFact]) -> list[FactRow]:
    rows = []
    for fact in facts:
        quarter = (fact.fiscal_quarter or "").upper()
        if quarter not in _QUARTERS and quarter != "FY":
            continue
        if fact.value is None or fact_quarantine_reason(fact) or _is_segment(fact):
            continue
        end = _period_end(fact)
        if end is None:
            continue
        rows.append(FactRow(
            metric=fact.metric, kind="FY" if quarter == "FY" else "Q", quarter=quarter, end=end,
            value=Decimal(fact.value), unit=fact.unit or "USD", reported=bool(fact.is_reported),
            source=fact.source_type or "",
            rank=(float(SOURCE_PRIORITY.get(fact.source_type or "", 50)),
                  -(fact.created_at.timestamp() if fact.created_at else 0.0)),
        ))
    return rows


def build_company_report(db: Session, company: Company, *, today: date | None = None) -> dict:
    """Respuesta de ``GET /api/companies/{ticker}/analyst-report``."""
    today = today or date.today()
    facts = list(db.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id,
               FinancialFact.metric.in_(FLOW_METRICS + _POINT_METRICS))
        .options(selectinload(FinancialFact.source))
    ).all())
    flow = [fact for fact in facts if fact.metric in FLOW_METRICS]
    points = compute_company_ttm(
        [fact for fact in facts if fact.metric in _POINT_METRICS],
        split_events_by_company(db, [company.id]).get(company.id, []),
        today,
    )
    prices = list(db.scalars(
        select(MarketPrice)
        .where(MarketPrice.company_id == company.id, MarketPrice.close > 0, MarketPrice.date <= today)
        .order_by(desc(MarketPrice.date))
        .limit(AVG_VOLUME_SESSIONS)
    ).all())
    last = prices[0] if prices else None
    volumes = [int(p.volume) for p in prices if p.volume]
    currency = (last.quote_currency if last is not None and last.quote_currency else None) or company.currency
    return {
        "ticker": company.ticker.upper(),
        "company": company.name,
        "version": REPORT_VERSION,
        "market": build_market(
            price=Decimal(last.close) if last is not None else None,
            price_date=last.date if last is not None else None,
            price_currency=currency,
            volumes=volumes,
            points=points,
        ),
        "estimates": build_estimates(_fact_rows(flow)),
        # Holdings (p. ej. Georgia Capital): NAV por acción que publica la propia
        # empresa en sus resultados (NSM / web de inversores) y descuento del
        # precio sobre él, con documento, fecha y cita.
        "nav": latest_published_nav(
            db,
            company,
            price=float(last.close) if last is not None else None,
            price_currency=currency,
            price_date=last.date if last is not None else None,
            today=today,
        ),
        "notes": {
            "avg_volume": f"Media de las últimas {AVG_VOLUME_SESSIONS} sesiones con volumen en nuestros cierres.",
            "ebitda": "EBITDA = resultado operativo + amortizaciones del mismo periodo; si falta, el EBITDA de la fuente.",
            "q4": "Un Q4 sin 10-Q se deriva como ejercicio − Q1 − Q2 − Q3.",
            "user_estimates": "Las estimaciones del usuario salen de su desglose por partes y su tesis, etiquetadas como suyas.",
            "nav": "NAV por acción tal como lo publica la empresa (último documento publicado); descuento = precio / NAV − 1.",
        },
    }
