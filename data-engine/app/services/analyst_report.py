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
  alguno, el EBITDA que traiga la fuente (FMP...) con su nombre; si tampoco hay,
  y el emisor no etiqueta resultado operativo (IFRS: CNQ, Airbus), el EBITDA por
  componentes de la valoración (:mod:`app.valuation.ebitda_components`), solo con el
  resultado financiero neto etiquetado: beneficio antes de impuestos − resultado
  financiero neto + amortizaciones, marcado como derivado; si no, vacío.
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
from app.valuation.ebitda_components import DERIVED as EBITDA_DERIVED
from app.valuation.ebitda_components import ebitda_from_components, pretax_income
from app.valuation.engines.base import adr_ratio as company_adr_ratio

REPORT_VERSION = "analyst-report-v1"
AVG_VOLUME_SESSIONS = 63  # ~3 meses de sesiones
ANNUAL_PERIODS = 4
QUARTER_PERIODS = 6
_QUARTERS = ("Q1", "Q2", "Q3", "Q4")
FLOW_METRICS = ("revenue", "operating_income", "depreciation_amortization", "ebitda")
# Componentes del EBITDA derivado (sin resultado operativo etiquetado); no abren periodos por sí solos.
EBITDA_COMPONENT_METRICS = ("income_before_tax", "net_income_total", "income_tax_expense", "finance_income_cost")
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
    url: str | None = None


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
        "url": row.url,
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
            url=annual.url,
        )


def _ebitda(best: dict[tuple[str, str, date], FactRow], kind: str, end: date, *,
            derive: bool = True) -> dict | None:
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
            "url": op.url,
        }
    source = _cell(best.get(("ebitda", kind, end)), basis="source_ebitda")
    if source is not None or not derive or op is not None or da is None:
        return source
    return _ebitda_from_components(best, kind, end, da)


def _ebitda_from_components(best: dict[tuple[str, str, date], FactRow], kind: str, end: date,
                            da: FactRow) -> dict | None:
    """Sin resultado operativo etiquetado (IFRS): beneficio antes de impuestos − resultado financiero neto + D&A.

    La fórmula de la valoración (:func:`app.valuation.ebitda_components.ebitda_from_components`), pero SOLO con el
    resultado financiero NETO etiquetado (``FinanceIncomeCost``): «antes de impuestos + gastos financieros» mete
    ingresos y otros resultados no operativos (en US GAAP, p. ej., el valor razonable de warrants) y aquí se
    presentaría como cifra real. Todo en la MISMA unidad y cierre; si no, ``None``.
    """
    parts = {m: best.get((m, kind, end)) for m in EBITDA_COMPONENT_METRICS}
    finance = parts["finance_income_cost"]
    if finance is None:
        return None
    pretax_metrics = (("income_before_tax",) if parts["income_before_tax"] is not None
                      else ("net_income_total", "income_tax_expense"))
    rows = [da, finance, *(parts[m] for m in pretax_metrics)]
    if any(row is None or row.unit != da.unit for row in rows):
        return None

    def val(metric: str) -> float | None:
        row = parts[metric]
        return None if row is None else float(row.value)

    pretax = pretax_income(income_before_tax=val("income_before_tax"), profit_loss=val("net_income_total"),
                           income_tax_expense=val("income_tax_expense"))
    value, basis = ebitda_from_components(
        operating_income=None, depreciation_amortization=float(da.value), income_before_tax=pretax,
        net_finance_result=float(finance.value))
    if value is None or basis not in EBITDA_DERIVED:
        return None
    anchor = parts[pretax_metrics[0]] or da
    return {
        "value": value,
        "unit": da.unit,
        "source": anchor.source,
        "reported": False,
        "basis": basis,
        "derived_q4": any(row is not None and row.derived for row in rows),
        "url": anchor.url,
    }


def build_estimates(rows: list[FactRow], *, annual: int = ANNUAL_PERIODS, quarters: int = QUARTER_PERIODS,
                    derive_ebitda: bool = True) -> dict:
    """Ingresos y EBITDA reales por ejercicio (últimos ``annual``) y trimestre (últimos ``quarters``).

    ``derive_ebitda=False`` (bancos y aseguradoras): sin EBITDA por componentes, sus intereses son operativos.
    """
    best = best_rows(rows)
    for metric in FLOW_METRICS + EBITDA_COMPONENT_METRICS:
        _derive_q4(best, metric)

    def periods(kind: str, limit: int) -> list[dict[str, Any]]:
        ends = sorted({end for (m, k, end) in best if k == kind and m in FLOW_METRICS}, reverse=True)[:limit]
        out = []
        for end in sorted(ends):
            quarter = "FY"
            if kind == "Q":
                quarter = next((best[(m, "Q", end)].quarter for m in FLOW_METRICS if (m, "Q", end) in best), "Q")
            revenue = _cell(best.get(("revenue", kind, end)))
            ebitda = _ebitda(best, kind, end, derive=derive_ebitda)
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
    adr_ratio: float | None = None,
    cover: dict | None = None,
) -> dict:
    """Bloque de datos de mercado. ``points`` = TtmValue de acciones, caja y deuda.

    ``cover`` = portada del último informe (con TODAS las clases sumadas si hay varias; regla «acciones-
    vigentes-v1», la del motor de valoración): si no es más antigua que el recuento elegido, manda. Sin ella el
    Informe valoraba ASTS con la media diluida de la clase A (299 M) frente a 389 M (A + B + C) en la ficha,
    y RXRX con las acciones del balance de septiembre (561 M) frente a 623 M de la portada de octubre.

    ``adr_ratio`` = acciones ordinarias por ADR (``adr_ratio`` del motor de valoración).
    Si el precio es de un ADR, las acciones del filing son ordinarias: capitalización =
    precio × acciones / ratio (TSM: 1 ADR = 5 ordinarias; sin el ratio salía ×5).
    """

    def point(metric: str) -> dict | None:
        item = points.get(metric)
        if item is None or item.value is None:
            return None
        return {"value": _num(item.value), "unit": item.unit, "period_end": item.period_end,
                "provenance": item.provenance}

    shares = point("shares_outstanding")
    diluted = point("shares_diluted")
    if cover is not None and cover.get("value") and cover["value"] > 0:
        ends = [p["period_end"] for p in (shares, diluted) if p and p.get("period_end")]
        if not ends or all(cover["period_end"] >= e for e in ends):
            shares = cover
    cash = point("cash_and_equivalents")
    debt = point("total_debt")
    avg_volume = round(sum(volumes) / len(volumes)) if volumes else None
    major_currency, price_divisor = normalize_currency(price_currency)
    market_cap = None
    market_cap_basis = None
    if price is not None and price > 0:
        major_price = price / price_divisor
        per_listed = adr_ratio if adr_ratio is not None and adr_ratio > 0 else 1.0
        if shares and shares["value"] and shares["value"] > 0:
            market_cap, market_cap_basis = float(major_price) * shares["value"] / per_listed, "shares_outstanding"
        elif diluted and diluted["value"] and diluted["value"] > 0:
            market_cap, market_cap_basis = float(major_price) * diluted["value"] / per_listed, "shares_diluted"
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
        "market_cap_adr_ratio": adr_ratio if market_cap is not None and adr_ratio is not None and adr_ratio > 0 else None,
        "market_cap_currency": major_currency,
        "enterprise_value_currency": major_currency,
        "cash": cash,
        "total_debt": debt,
        "enterprise_value": enterprise_value,
        "enterprise_value_reason": ev_reason,
    }


def latest_cover(facts: list[FinancialFact]) -> dict | None:
    """La portada más reciente del último informe (regla «acciones-vigentes-v1», la de la valoración), en el
    formato de los puntos del Informe: la suma de TODAS las clases (hecho derivado de dei:EntityCommonStock-
    SharesOutstanding por clase, con su procedencia en el documento) o la portada SEC sin desglose
    (``<fecha>:DEI``). La portada sin desglose se descarta, con la misma regla, si queda por debajo del 80 % o
    por encima de 3× la media diluida más reciente (puede ser una sola clase o una escala distinta)."""
    from app.valuation import current_shares as cs

    def meta(fact: FinancialFact) -> Any:
        return getattr(getattr(fact, "source", None), "metadata_", None)

    diluted = [(end, f) for f in facts if f.metric == "shares_diluted" and f.value is not None
               and (end := _period_end(f)) is not None]
    last_diluted = float(max(diluted, key=lambda p: p[0])[1].value) if diluted else None
    best: tuple[date, bool, FinancialFact] | None = None
    for fact in facts:
        if fact.metric != "shares_outstanding" or fact.value is None or float(fact.value) <= 0:
            continue
        end = _period_end(fact)
        if end is None:
            continue
        source = fact.source_type or ""
        by_class = source == "derived" and cs.is_class_sum(meta(fact), fact.period)
        dei = source == "SEC" and str(fact.period or "").endswith(":DEI")
        if not (by_class or dei):
            continue
        if not by_class and cs.cover_check(float(fact.value), last_diluted, by_class=False) is not None:
            continue
        if best is None or (end, by_class) > (best[0], best[1]):
            best = (end, by_class, fact)
    if best is None:
        return None
    end, by_class, fact = best
    out = {"value": _num(Decimal(fact.value)), "unit": "shares", "period_end": end, "provenance": "OFICIAL",
           "basis": "class_sum" if by_class else "cover"}
    if by_class:
        members = cs.class_members(meta(fact), fact.period) or {}
        out["class_members"] = {cs.short(k): v for k, v in sorted(members.items())}
    return out


def _fact_rows(facts: list[FinancialFact], cik: str | None = None) -> list[FactRow]:
    from app.core.source_urls import sec_filing_url

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
            url=sec_filing_url(fact.source_url, fact.accession_number, cik),
        ))
    return rows


_LENDER_INSURER_SIC = (range(6000, 6200), range(6300, 6500))
_LENDER_INSURER_WORDS = ("bank", "banco", "insurance", "insurer", "aseguradora", "seguros", "reinsurance")


def interest_is_operating(company: Company) -> bool:
    """Bancos y aseguradoras: sus intereses y resultados financieros son el negocio, no hay EBITDA por componentes."""
    sic = getattr(company, "sic_code", None) or getattr(company, "sic", None)
    try:
        if sic is not None and any(int(sic) in band for band in _LENDER_INSURER_SIC):
            return True
    except (TypeError, ValueError):
        pass
    text = " ".join(str(getattr(company, a, "") or "") for a in ("sector", "industry", "company_type")).lower()
    return any(word in text for word in _LENDER_INSURER_WORDS)


def build_company_report(db: Session, company: Company, *, today: date | None = None) -> dict:
    """Respuesta de ``GET /api/companies/{ticker}/analyst-report``."""
    today = today or date.today()
    facts = list(db.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id,
               FinancialFact.metric.in_(FLOW_METRICS + EBITDA_COMPONENT_METRICS + _POINT_METRICS))
        .options(selectinload(FinancialFact.source))
    ).all())
    flow = [fact for fact in facts if fact.metric in FLOW_METRICS + EBITDA_COMPONENT_METRICS]
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
            adr_ratio=company_adr_ratio(company),
            cover=latest_cover(facts),
        ),
        "estimates": build_estimates(_fact_rows(flow, getattr(company, "cik", None)),
                                     derive_ebitda=not interest_is_operating(company)),
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
            "ebitda": ("EBITDA = resultado operativo + amortizaciones del mismo periodo; si falta, el EBITDA de la fuente; "
                       "si el emisor no etiqueta resultado operativo (IFRS), beneficio antes de impuestos − resultado "
                       "financiero neto + amortizaciones, marcado como derivado. Bancos y aseguradoras sin EBITDA "
                       "derivado."),
            "q4": "Un Q4 sin 10-Q se deriva como ejercicio − Q1 − Q2 − Q3.",
            "url": "Cada cifra enlaza al filing del que sale (índice EDGAR por número de acceso o el documento ESEF).",
            "user_estimates": "Las estimaciones del usuario salen de su desglose por partes y su tesis, etiquetadas como suyas.",
            "nav": "NAV por acción tal como lo publica la empresa (último documento publicado); descuento = precio / NAV − 1.",
            "shares": ("Acciones en circulación: la portada del último informe; con varias clases, la suma de todas "
                       "(la misma regla que la valoración)."),
        },
    }
