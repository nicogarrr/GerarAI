"""Valoración por TIR para el accionista con datos de GerarAI (lectura pura; sin modelo, sin red).

Junta el punto de partida normalizado, la historia anual citada y los comparables CALCULADOS, aplica la
regla pre-registrada (:mod:`app.valuation.shareholder_irr_rules`) y devuelve los tres escenarios, la TIR a
5 y 10 años con su descomposición, la tabla de sensibilidad, la elección del método con sus razones y una
huella (mismos datos → misma huella → mismo resultado para cualquier usuario).

Cada cifra lleva su fuente: el hecho (métrica, periodo, documento, URL, fecha de presentación) o la fórmula
con la que se calcula a partir de otros hechos.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import redact_secrets
from app.models import Company, FinancialFact
from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules
from app.valuation.attributable import attributable_shares, scale_flows
from app.valuation.ebitda_components import DERIVED as EBITDA_DERIVED
from app.valuation.ebitda_components import FORMULAS as EBITDA_FORMULAS
from app.valuation.ebitda_components import (
    OPERATING_PLUS_DA,
    PRETAX_COMPONENTS,
    ebitda_from_components,
    pretax_income,
)
from app.valuation.share_units import rescale_shares

logger = logging.getLogger(__name__)

SERVICE_VERSION = "shareholder-irr-service-v2"
HISTORY_YEARS = 10
_FLOW = ("revenue", "operating_income", "depreciation_amortization", "ebitda", "net_income",
         "net_income_attributable", "operating_cash_flow", "capital_expenditure", "dividends_paid",
         "common_stock_repurchased", "acquisitions", "stock_based_compensation", "shares_diluted",
         "eps_diluted", "free_cash_flow", "interest_expense", "earned_premiums", "lease_income",
         "gain_on_sale_real_estate", "income_before_tax", "income_tax_expense", "finance_income_cost",
         "net_income_total", "net_income_minority")
_POINT = ("cash_and_equivalents", "short_term_investments", "total_debt", "long_term_debt",
          "operating_lease_liabilities", "lease_liabilities", "lease_liabilities_current", "lease_liabilities_noncurrent",
          "minority_interest", "hybrid_capital", "shares_outstanding", "total_equity", "preferred_stock")
#: Saldos de balance que además se leen por ejercicio (cierre del año fiscal) para la base de valor contable.
_POINT_ANNUAL = ("total_equity", "preferred_stock", "minority_interest")
#: Umbral de «sin ingresos» para el método de caja (millones de la moneda de los informes).
PRE_REVENUE_MAX = 50.0
#: Sectores/códigos SIC en los que el EBITDA consolidado no es del accionista (deuda de filiales, balance
#: financiero): la TIR se calcula sobre el beneficio (PER).
FINANCIAL_SIC = range(6000, 6800)
FINANCIAL_WORDS = ("financial", "bank", "insurance", "asset management", "reit", "holding", "financier", "banca",
                   "seguros")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _cite(fact: FinancialFact) -> dict[str, Any]:
    src = fact.source
    return {
        "metric": fact.metric,
        "period": fact.period,
        "value": _f(fact.value),
        "unit": fact.unit,
        "document": getattr(src, "title", None),
        "url": fact.source_url if src is not None else None,
        "filed": fact.filed.isoformat() if fact.filed is not None else None,
        "accession": getattr(fact, "accession_number", None),
        "source_type": fact.source_type,
    }


def _share_cite(fact: FinancialFact) -> dict[str, Any]:
    """Cita de una portada de acciones con su desglose por clase (hecho derivado de la suma de clases)."""
    from app.valuation.current_shares import class_members, is_class_sum

    cite = _cite(fact)
    meta = getattr(fact.source, "metadata_", None) if fact.source is not None else None
    if is_class_sum(meta, fact.period):
        cite["class_sum"] = True
        members = class_members(meta, fact.period)
        if members:
            cite["class_members"] = members
    return cite


def _end(period: str) -> str:
    return str(period or "").split(":")[0]


def _fiscal_year(period: str) -> int | None:
    """Ejercicio de un cierre anual por su mes nominal: un año de 52/53 semanas que cierra el 2-ene-2026 es el
    ejercicio 2025 (el año del calendario lo contaba como 2026 y chocaba con el cierre del 31-dic-2026)."""
    from app.services.own_consensus import fiscal_year_of

    try:
        return fiscal_year_of(date.fromisoformat(_end(period)[:10]))
    except ValueError:
        return None


def company_facts(db: Session, company: Company) -> tuple[dict[str, dict[int, dict]], dict[str, dict]]:
    """Ejercicios anuales {métrica: {año: cita}} y último dato de balance {métrica: cita}, mejor fuente."""
    from app.services.analyst_report import SOURCE_PRIORITY
    from app.services.esef_fact_quarantine import fact_quarantine_reason
    from app.services.ttm_service import _is_segment

    rows = list(db.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id, FinancialFact.metric.in_(_FLOW + _POINT))
        .options(selectinload(FinancialFact.source))
        .order_by(desc(FinancialFact.period), desc(FinancialFact.id))
    ).all())
    annual: dict[str, dict[int, tuple[tuple[float, float], dict]]] = {}
    point: dict[str, tuple[str, tuple[float, float], dict]] = {}
    for fact in rows:
        if fact.value is None or _is_segment(fact) or fact_quarantine_reason(fact):
            continue
        rank = (float(SOURCE_PRIORITY.get(fact.source_type or "", 50)),
                -(fact.created_at.timestamp() if fact.created_at else 0.0))
        period = str(fact.period or "")
        if fact.metric in _FLOW and period.endswith(":FY"):
            year = _fiscal_year(period)
            if year is None:
                continue
            slot = annual.setdefault(fact.metric, {})
            if year not in slot or rank < slot[year][0]:
                slot[year] = (rank, _cite(fact))
        elif fact.metric in _POINT:
            end = _end(period)
            if fact.metric in _POINT_ANNUAL and period.endswith(":FY"):
                year = _fiscal_year(period)
                if year is not None:
                    slot = annual.setdefault(fact.metric, {})
                    if year not in slot or rank < slot[year][0]:
                        slot[year] = (rank, _cite(fact))
            cur = point.get(fact.metric)
            if cur is None or end > cur[0] or (end == cur[0] and rank < cur[1]):
                point[fact.metric] = (end, rank, _share_cite(fact) if fact.metric == "shares_outstanding" else _cite(fact))
    return ({m: {y: c for y, (_, c) in v.items()} for m, v in annual.items()},
            {m: c for m, (_, _, c) in point.items()})


def _primary_point_at(db: Session, company: Company, metric: str, period: str) -> dict[str, Any] | None:
    """Cita primaria del saldo ``metric`` en ``period`` (``AAAA-MM-DD:FY``): primero el mismo tipo de periodo
    (el 10-K del cierre anual, no la comparativa de un 10-Q posterior, que puede traer solo la parte no
    corriente), después cualquier filing del mismo cierre, el más reciente."""
    end = period.split(":")[0]
    from app.services.ttm_service import _is_segment
    from app.valuation.balance_bridge import PRIMARY_SOURCES

    rows = db.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id, FinancialFact.metric == metric,
               FinancialFact.period.like(f"{end}:%"), FinancialFact.source_type.in_(PRIMARY_SOURCES))
        .options(selectinload(FinancialFact.source))
        .order_by(desc(FinancialFact.filed), desc(FinancialFact.id))
    ).all()
    rows = sorted(rows, key=lambda f: f.period != period)  # estable: dentro de cada grupo, el más reciente
    for fact in rows:
        if fact.value is not None and not _is_segment(fact):
            return _cite(fact)
    return None


def _mill(cite: Mapping[str, Any] | None) -> float | None:
    v = _f((cite or {}).get("value"))
    return None if v is None else v / 1_000_000.0


#: Tipos de empresa y el método que les corresponde (lo decide el código; el modelo no lo elige).
KIND_METHODS = {
    "operating": "TIR para el accionista sobre EV/EBITDA o PER",
    "insurer": "TIR sobre el valor contable: ROE, reparto y P/VC (el float queda dentro del balance)",
    "bank": "TIR sobre el valor contable: ROE, reparto y P/VC",
    "holding": "TIR sobre el valor contable o NAV por acción y el P/VC (descuento sobre NAV)",
    "real_estate": "TIR sobre el FFO (beneficio + amortización de inmuebles − plusvalías por ventas) y el P/FFO",
    "pre_revenue": "caja, consumo y meses de margen (runway), dilución y suma de partes para lo que aún no factura",
}


def company_kind(company: Company, annual: Mapping[str, Mapping[int, dict]]) -> tuple[str, str]:
    """(tipo, por qué). Primero la clasificación de la ficha (tipo de empresa, industria: el mismo
    registro que usan los motores de valoración); si no decide, los propios hechos del último ejercicio:
    primas devengadas ≥ 50 % de los ingresos → aseguradora; ingresos por arrendamiento ≥ 50 % → inmobiliaria
    (las dos, solo si la industria de la ficha es desconocida o es la de seguros / inmobiliaria);
    ingresos < 50 M o EBITDA, beneficio y flujo libre negativos los dos últimos años → preingresos/quema caja."""
    try:
        from app.valuation.engines.registry import classification_engine_key

        key = classification_engine_key(company)
    except Exception:  # noqa: BLE001 - sin registro, solo los hechos
        key = "standard_dcf"
    years = sorted({y for m in ("revenue", "net_income", "lease_income", "earned_premiums")
                    for y in annual.get(m, {})})
    last = years[-1] if years else None

    def v(metric: str, year: int | None = last) -> float | None:
        return _mill(annual.get(metric, {}).get(year)) if year is not None else None

    rev, prem, lease = v("revenue"), v("earned_premiums"), v("lease_income")
    # Los hechos solo deciden donde la ficha no dice otra cosa: una industria conocida que no es seguros
    # (UNH, «Health Care»: primas de salud con márgenes de distribuidor) o inmobiliaria no se reclasifica.
    industry = str(getattr(company, "industry", None) or "").strip().lower()
    unknown = industry in ("", "unknown", "n/a", "none")
    if key in ("insurer", "bank"):
        return key, f"clasificación de la ficha ({'aseguradora' if key == 'insurer' else 'banco'})"
    if key == "holding_company":
        return "holding", "holding o gestora según la clasificación de la ficha"
    if prem and rev and prem / rev >= 0.5 and (unknown or "insur" in industry):
        return "insurer", f"primas devengadas = {prem / rev:.0%} de los ingresos de {last}"
    if key == "reit":
        return "real_estate", "REIT según la industria de la ficha"
    if lease and (not rev or lease >= 0.5 * rev) and (unknown or "real estate" in industry or "reit" in industry):
        return "real_estate", f"ingresos por arrendamiento ≥ 50 % de los ingresos de {last}"
    # Regla «preingresos-ejercicios-v1» (9-nov-2026): por ingresos, solo con ingresos PUBLICADOS. Un ejercicio
    # sin dato de ingresos no es un ejercicio sin ingresos (L3Harris: beneficio de 2025 cargado y sus ingresos
    # no) y un solo año bajo no basta: los dos últimos ejercicios con dato deben estar por debajo del umbral.
    reported = sorted({y for m in ("revenue", "lease_income") for y, c in (annual.get(m) or {}).items()
                       if _mill(c) is not None})
    tops = [max(x for x in (v("revenue", y), v("lease_income", y), 0.0) if x is not None) for y in reported[-2:]]
    low = max(tops) < PRE_REVENUE_MAX if tops else True
    if key == "pre_revenue" or low:
        span = (f"{reported[-1]}" if len(reported) == 1 else f"{reported[-2]} y {reported[-1]}") if reported else ""
        why = (f"ingresos de {span} por debajo de {PRE_REVENUE_MAX:g} M" if span
               else "sin ingresos publicados en ningún ejercicio")
        return "pre_revenue", (why if low else "preingresos según la clasificación de la ficha")
    burning = 0
    for y in years[-2:]:
        oi, da, ni = v("operating_income", y), v("depreciation_amortization", y), v("net_income", y)
        ocf, capex = v("operating_cash_flow", y), v("capital_expenditure", y)
        ebitda, _basis = ebitda_from_components(
            operating_income=oi, depreciation_amortization=da, ebitda_reported=v("ebitda", y),
            income_before_tax=pretax_income(income_before_tax=v("income_before_tax", y),
                                            profit_loss=v("net_income_total", y),
                                            income_tax_expense=v("income_tax_expense", y)),
            interest_expense=v("interest_expense", y), net_finance_result=v("finance_income_cost", y))
        fcf = (ocf - abs(capex)) if ocf is not None and capex is not None else None
        if all(x is not None and x <= 0 for x in (ebitda, ni, fcf)):
            burning += 1
    if len(years) >= 2 and burning == 2:
        return "pre_revenue", "EBITDA, beneficio y flujo libre negativos en los dos últimos ejercicios: quema caja"
    return "operating", ""


def _is_financial(company: Company) -> bool:
    sic = _f(getattr(company, "sic_code", None) or getattr(company, "sic", None))
    if sic is not None and int(sic) in FINANCIAL_SIC:
        return True
    text = " ".join(str(getattr(company, a, "") or "") for a in ("sector", "industry", "company_type")).lower()
    return any(w in text for w in FINANCIAL_WORDS)


def choose_method(*, revenue: float | None, ebitda_years: Sequence[float | None], net_income: float | None,
                  financial: bool, segment_ebitda: bool) -> dict[str, Any]:
    """Método principal y por qué se descartan los demás. Las razones las da el código, no el modelo."""
    reasons: dict[str, str] = {}
    positive_ebitda = [e for e in ebitda_years[-3:] if e is not None]
    ebitda_ok = len(positive_ebitda) >= 2 and all(e > 0 for e in positive_ebitda)
    if not revenue or revenue <= 0:
        chosen = "sotp"
        reasons["tir_ev_ebitda"] = "sin ingresos: no hay un EBITDA que proyectar"
        reasons["tir_per"] = "sin ingresos ni beneficio"
    elif financial and net_income and net_income > 0:
        chosen = "tir_per"
        reasons["tir_ev_ebitda"] = ("empresa financiera u holding: la deuda consolidada es de las filiales y el "
                                    "EBITDA consolidado no pertenece al accionista")
    elif ebitda_ok:
        chosen = "tir_ev_ebitda"
        reasons["tir_per"] = ("el beneficio neto lo distorsionan la amortización de intangibles, los partidas "
                              "no recurrentes y la estructura de capital; queda como contraste")
    elif net_income and net_income > 0:
        chosen = "tir_per"
        reasons["tir_ev_ebitda"] = "sin EBITDA positivo en al menos dos de los tres últimos ejercicios"
    else:
        chosen = "sotp"
        reasons["tir_ev_ebitda"] = "sin EBITDA positivo"
        reasons["tir_per"] = "sin beneficio positivo"
    reasons["dcf"] = ("un DCF con un único coste de capital y crecimiento perpetuo es muy sensible a esas dos "
                      "cifras; se muestra como contraste, no como ancla")
    if chosen != "sotp":
        reasons["sotp"] = ("la suma de partes necesita EBITDA por segmento y la empresa solo publica ingresos "
                           "por segmento" if not segment_ebitda else
                           "solo para las partes que aún no facturan, sumadas encima")
    return {"chosen": chosen, "discarded": reasons}


def _peer_multiples(db: Session, company: Company, basis: str, today: date) -> list[dict[str, Any]]:
    """Comparables que elige el servicio de comparables de GerarAI, con su múltiplo CALCULADO aquí con la
    misma fórmula que la empresa. Un comparable sin datos queda listado sin múltiplo."""
    try:
        from app.services.peer_comparison_service import PeerComparisonService

        peers, basis_label, _trace = PeerComparisonService()._find_peers(db, company, 8)
    except Exception as exc:  # noqa: BLE001 - sin comparables la regla lo dice
        logger.info("irr peers: %s", type(exc).__name__)
        return []
    out = []
    for peer in peers:
        try:
            start, _hist, _w, _c = starting_point(db, peer, today=today, basis=basis)
        except Exception:  # noqa: BLE001
            start = None
        out.append({"ticker": peer.ticker, "name": peer.name, "selection": basis_label,
                    "multiple": start.multiple if start is not None else None})
    return out


_FILING_SOURCES = ("sec", "esef")


def _is_filing(cite: Mapping[str, Any] | None) -> bool:
    return str((cite or {}).get("source_type") or "").lower().startswith(_FILING_SOURCES)


def _to_listed_share_basis(company: Any, annual: dict[str, dict[int, dict]], point: dict[str, dict],
                           warnings: list[str], cites: dict[str, Any]) -> None:
    """Emisor con ADR: todos los recuentos y el BPA en la unidad que cotiza (el ADS), como el precio.

    Los 20-F dan acciones ORDINARIAS y BPA por ordinaria; un agregador puede dar ADS (TSM: 25.930 M de
    ordinarias en la SEC frente a 5.186 M de ADS el último año, 1 ADS = 5). Se clasifica cada cifra frente
    al dato oficial más cercano (``share_units.count_basis``) y se pasa a ADS; lo que no cuadra con
    ninguna de las dos unidades no se toca. Sin ratio conocido no cambia nada."""
    from types import SimpleNamespace

    from app.valuation.engines.base import adr_ratio
    from app.valuation.share_units import count_basis, nearest_reference

    ratio = adr_ratio(SimpleNamespace(factor_tags=getattr(company, "factor_tags", None),  # type: ignore[arg-type]
                                      ticker=getattr(company, "ticker", "") or ""))
    if not ratio or ratio <= 1:
        return
    converted: list[dict[str, Any]] = []
    unresolved: list[str] = []

    def refs(metric: str) -> dict[int, float]:
        return {y: v for y, c in (annual.get(metric) or {}).items()
                if _is_filing(c) and (v := _f((c or {}).get("value"))) and v > 0}

    share_refs = refs("shares_diluted")
    eps_refs = refs("eps_diluted")

    def convert(metric: str, key: str, cite: dict, ref: float | None, per_share: bool) -> dict:
        value = _f(cite.get("value"))
        if value is None or value == 0:
            return cite
        if _is_filing(cite):
            basis = "ordinary"
        elif per_share:
            # BPA por ADS = BPA por ordinaria × ratio: se compara al revés que un recuento.
            flipped = count_basis(ref, abs(value), ratio) if ref else None
            basis = {"ads": "ordinary", "ordinary": "ads"}.get(flipped) if flipped else None
        else:
            basis = count_basis(value, ref, ratio)
        if basis is None:
            unresolved.append(f"{metric} {key}")
            return cite
        if basis == "ads":
            return cite
        new = value * ratio if per_share else value / ratio
        converted.append({"metric": metric, "period": key, "from": value, "to": new, "source_type": cite.get("source_type")})
        return {**cite, "value": new, "share_basis": f"convertido de ordinarias a ADS (1 ADS = {ratio:g})"}

    for metric, per_share, references in (("shares_diluted", False, share_refs), ("eps_diluted", True, eps_refs)):
        slot = annual.get(metric) or {}
        for y in list(slot):
            ref = nearest_reference(y, references)
            slot[y] = convert(metric, str(y), slot[y], abs(ref) if ref else None, per_share)
    if point.get("shares_outstanding"):
        end = _end(str(point["shares_outstanding"].get("period") or ""))
        try:
            year = int(end[:4])
        except ValueError:
            year = max(share_refs) if share_refs else 0
        point["shares_outstanding"] = convert("shares_outstanding", end, point["shares_outstanding"],
                                              nearest_reference(year, share_refs), False)
    cites["adr_share_basis"] = {"ordinary_per_ads": ratio, "converted": converted, "unresolved": unresolved}
    if converted:
        warnings.append(f"ADR: acciones y BPA en ADS (1 ADS = {ratio:g} ordinarias), la unidad del precio")
    if unresolved:
        warnings.append("ADR: recuentos que no cuadran ni en ordinarias ni en ADS, sin convertir: " + ", ".join(unresolved))


#: Patrimonio / activo a partir del cual un balance sin ingresos es el de una sociedad de inversión (sin
#: deuda propia relevante: el activo son participadas y caja).
INVESTMENT_EQUITY_RATIO = 0.8


def _latest_fy_value(db: Session, company: Company, metric: str, year: int) -> float | None:
    fact = db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id, FinancialFact.metric == metric,
                                    FinancialFact.period.like(f"{year}-%:FY"))
        .order_by(desc(FinancialFact.id))
    ).first()
    return _f(fact.value) if fact is not None and fact.value is not None else None


def investment_holding_reason(db: Session, company: Company, annual: Mapping[str, Mapping[int, dict]],
                              kind: str, kind_reason: str) -> str | None:
    """Por qué una empresa SIN ingresos operativos es una holding/sociedad de inversión que se valora por NAV,
    o None. General, nunca por emisor:
    - tipo de entidad: la ficha la clasifica como holding o gestora; o
    - estructura del filing: ninguna línea de ingresos (ni arrendamientos ni primas) en ningún ejercicio,
      beneficio positivo el último año (plusvalías y dividendos de participadas) y patrimonio ≥ 80 % del
      activo (el balance de una sociedad de inversión: participadas a valor razonable, sin deuda propia).
    Necesita patrimonio y beneficio por ejercicio: sin ellos no hay NAV que seguir."""
    if any(annual.get(m) for m in ("revenue", "lease_income", "earned_premiums")):
        return None
    equity_years = sorted(set(annual.get("total_equity", {})) & set(annual.get("net_income", {})))
    if not equity_years:
        return None
    last = equity_years[-1]
    if kind == "holding":
        return f"{kind_reason}; sin ingresos operativos: su valor es el NAV (patrimonio a valor razonable)"
    equity, income = _mill(annual["total_equity"][last]), _mill(annual["net_income"][last])
    assets = _latest_fy_value(db, company, "total_assets", last)
    if equity is None or income is None or assets is None or assets <= 0 or equity <= 0 or income <= 0:
        return None
    ratio = equity * 1_000_000 / assets
    if ratio < INVESTMENT_EQUITY_RATIO:
        return None
    return (f"sin ingresos operativos, beneficio positivo y patrimonio = {ratio:.0%} del activo en {last}: "
            "balance de sociedad de inversión, su valor es el NAV")


def nav_from_filing(company: Company, year: int, currency: str, aggregator_nav: float | None,
                    warnings: list[str]) -> dict[str, Any] | None:
    """NAV del último ejercicio leído de las cuentas depositadas (OCR de Companies House, ya en caché: sin
    red), con su página y su línea. Solo si el balance cuadró, el cierre es de ``year`` y la divisa es la de
    los informes. Si difiere más de un 1 % del dato del agregador, manda el del filing y se avisa."""
    try:
        from app.services.scanned_accounts import for_ticker, page_url
    except Exception:  # noqa: BLE001
        return None
    best: dict[str, Any] | None = None
    for read in for_ticker(getattr(company, "ticker", "") or ""):
        for fig in read.get("figures") or []:
            if fig.get("metric") != "net_assets" or fig.get("value_millions") is None:
                continue
            if str(fig.get("period_end") or "")[:4] != str(year) or str(fig.get("currency") or "").upper() != currency:
                continue
            cand = {**fig, "document": read.get("company_name"), "document_url": read.get("document_url"),
                    "url": page_url(read.get("document_url"), fig.get("page")), "source_type": "companies_house_ocr",
                    "made_up_to": read.get("made_up_to")}
            # Las cuentas de la matriz (sociedad de inversión) antes que unas consolidadas de otra entidad.
            if best is None or (fig.get("consolidated") is False and best.get("consolidated") is not False):
                best = cand
    if best is None:
        return None
    if aggregator_nav and abs(best["value_millions"] / aggregator_nav - 1) > 0.01:
        warnings.append(f"NAV {year}: las cuentas depositadas dicen {best['value_millions']:,.1f} M {currency} "
                        f"(pág. {best.get('page')}) y el agregador {aggregator_nav:,.1f} M: manda el filing")
    return best


def nav_holding_debt(db: Session, company: Company, year: int, warnings: list[str]
                     ) -> tuple[float | None, dict[str, Any] | None]:
    """Deuda de una sociedad de inversión sin deuda etiquetada (millones), con su fuente, o (None, None).

    1. Las cuentas depositadas (OCR) con el balance CUADRADO y sin ninguna línea de préstamos: deuda 0
       probada por el filing (un 0 explícito con su página), no supuesta.
    2. Si no, el pasivo total del ejercicio como cota superior (todo el pasivo tratado como deuda).
    3. Sin ninguno de los dos: N/D (el llamador lo dice)."""
    try:
        from app.services.scanned_accounts import for_ticker, page_url
    except Exception:  # noqa: BLE001
        for_ticker = None  # type: ignore[assignment]
    for read in (for_ticker(getattr(company, "ticker", "") or "") if for_ticker else []):
        figs = read.get("figures") or []
        bal = ((read.get("checks") or {}).get("balance") or {})
        nav = next((f for f in figs if f.get("metric") == "net_assets"
                    and str(f.get("period_end") or "")[:4] == str(year)), None)
        if nav is None or not bal.get("ok") or any(f.get("metric") == "borrowings" for f in figs):
            continue
        return 0.0, {"metric": "total_debt", "value": 0.0, "period": f"{nav.get('period_end')}",
                     "unit": nav.get("currency"), "source_type": "companies_house_ocr",
                     "document": read.get("company_name"), "url": page_url(read.get("document_url"), nav.get("page")),
                     "formula": (f"balance cuadrado ({bal.get('why')}) sin línea de préstamos: deuda financiera 0 "
                                 "según las cuentas depositadas")}
    liabilities = _latest_fy_value(db, company, "total_liabilities", year)
    if liabilities is not None and liabilities >= 0:
        warnings.append(f"deuda sin etiquetar: se toma todo el pasivo de {year} ({liabilities / 1e6:,.1f} M) como deuda, "
                        "cota superior")
        return liabilities / 1e6, {"metric": "total_debt", "value": liabilities, "period": f"{year}:FY",
                                   "formula": "pasivo total del ejercicio (cota superior: todo el pasivo como deuda)"}
    return None, None


def starting_point(db: Session, company: Company, *, today: date, basis: str | None = None,
                   include_leases: bool | None = None
                   ) -> tuple[engine.StartingPoint, rules.History, list[str], dict[str, Any]]:
    """Punto de partida normalizado + historia anual. Devuelve también avisos y las citas usadas."""
    from app.services.user_sotp_service import _price, convert_amount

    annual, point = company_facts(db, company)
    warnings: list[str] = []
    cites: dict[str, Any] = {}
    _to_listed_share_basis(company, annual, point, warnings, cites)
    kind, kind_reason = company_kind(company, annual)
    if kind == "real_estate":
        # Un REIT etiqueta a menudo solo el arrendamiento (Camden: «Revenues» hasta 2016 y después
        # OperatingLeaseLeaseIncome): los ingresos de cada año son el mayor de los dos datos.
        rev_slot = annual.setdefault("revenue", {})
        for y, cite in (annual.get("lease_income") or {}).items():
            if _mill(cite) is not None and (_mill(rev_slot.get(y)) or 0.0) < (_mill(cite) or 0.0):
                rev_slot[y] = cite
    years = sorted(set(annual.get("revenue", {})))[-HISTORY_YEARS:]
    nav_path = False
    if not years:
        # Holding o sociedad de inversión sin ingresos operativos (CGEO.L): su valor es el NAV (patrimonio a
        # valor razonable). Se valora por el valor contable = NAV y el P/VC = descuento sobre el NAV.
        holding_reason = investment_holding_reason(db, company, annual, kind, kind_reason)
        if holding_reason:
            kind, kind_reason, nav_path = "holding", holding_reason, True
            years = sorted(set(annual.get("total_equity", {})) & set(annual.get("net_income", {})))[-HISTORY_YEARS:]
    if not years and kind == "pre_revenue":
        years = sorted(set(annual.get("net_income", {})))[-HISTORY_YEARS:]
    if not years:
        raise ValueError("sin ingresos anuales")
    last = years[-1]

    def series(metric: str) -> list[float | None]:
        return [_mill(annual.get(metric, {}).get(y)) for y in years]

    ebitda_basis: dict[int, str | None] = {}

    def ebitda_for(y: int) -> float | None:
        value, how = ebitda_from_components(
            operating_income=_mill(annual.get("operating_income", {}).get(y)),
            depreciation_amortization=_mill(annual.get("depreciation_amortization", {}).get(y)),
            ebitda_reported=_mill(annual.get("ebitda", {}).get(y)),
            income_before_tax=pretax_income(
                income_before_tax=_mill(annual.get("income_before_tax", {}).get(y)),
                profit_loss=_mill(annual.get("net_income_total", {}).get(y)),
                income_tax_expense=_mill(annual.get("income_tax_expense", {}).get(y))),
            interest_expense=_mill(annual.get("interest_expense", {}).get(y)),
            net_finance_result=_mill(annual.get("finance_income_cost", {}).get(y)),
        )
        ebitda_basis[y] = how
        return value

    revenue = series("revenue")
    ebitda = [ebitda_for(y) for y in years]
    ni_attr = series("net_income_attributable")
    net_income = [a if a is not None else n for a, n in zip(ni_attr, series("net_income"), strict=True)]
    if net_income[-1] is None and series("net_income_total")[-1] is not None:
        # Solo hay beneficio total: sin señal de que no haya minoritarios no se toma como del accionista.
        warnings.append(f"beneficio {last} atribuible no verificable: el emisor solo etiqueta el total y ninguna "
                        "señal (minoritarios a 0, línea atribuible o estado de patrimonio) prueba que no haya "
                        "minoritarios; el PER y el P/VC quedan N/D y el puente EV → capital resta 0 minoritarios sin verificar")
        cites["attributable_unverified"] = {"year": last, "total": annual.get("net_income_total", {}).get(last),
                                            "reason": "atribuible no verificable"}
    reporting = str((annual.get("revenue", {}).get(last)
                     or (annual.get("total_equity", {}).get(last) if nav_path else None)
                     or {}).get("unit") or company.currency or "USD").upper()[:3]
    financial = _is_financial(company) or kind in ("insurer", "bank", "holding")
    method = choose_method(revenue=revenue[-1], ebitda_years=ebitda, net_income=net_income[-1],
                           financial=financial, segment_ebitda=False)
    book = [None] * len(years)
    earnings_label = ""
    if kind in ("insurer", "bank", "holding"):
        eq, pref = series("total_equity"), series("preferred_stock")
        book = [None if e is None else e - (p or 0.0) for e, p in zip(eq, pref, strict=True)]
        nav_cite = None
        if nav_path:
            nav_cite = nav_from_filing(company, last, reporting, book[-1], warnings)
            if nav_cite is not None:
                book[-1] = nav_cite["value_millions"]
        if book[-1] is not None and book[-1] > 0 and net_income[-1] is not None:
            method = {"chosen": "tir_pb", "discarded": {
                "tir_ev_ebitda": ("el EBITDA de una aseguradora, un banco o un holding no es del accionista: la deuda y "
                                  "las reservas son parte del negocio"),
                "tir_per": ("el beneficio de un año lo mueven la siniestralidad, las plusvalías y las revalorizaciones; "
                            "lo que compone es el valor contable al ROE, y el PER queda como contraste"),
                "dcf": method["discarded"].get("dcf", ""),
                "sotp": ("la suma de partes necesita el valor de cada filial; con NAV publicado, el P/VC ya es "
                         "el descuento sobre ese NAV"),
            }}
            cites["book_value"] = {"formula": "patrimonio atribuible a la matriz − preferentes al cierre del ejercicio",
                                   "inputs": [annual.get("total_equity", {}).get(last),
                                              annual.get("preferred_stock", {}).get(last)]}
            if nav_path:
                cites["book_value"] = {
                    "formula": ("NAV = patrimonio de la sociedad de inversión (participadas a valor razonable) al "
                                "cierre del ejercicio"),
                    "inputs": [nav_cite or annual.get("total_equity", {}).get(last)]}
        else:
            warnings.append("sin valor contable por ejercicio: se valora por el beneficio (PER) y se avisa")
    elif kind == "real_estate":
        gains = series("gain_on_sale_real_estate")
        da = series("depreciation_amortization")
        # FFO = beneficio + amortizaciones − plusvalías: sin amortización o sin plusvalías en todas las fuentes
        # el FFO de ese año es N/D (no beneficio + 0 ni plusvalías = 0). Un 0 declarado por el emisor sí vale.
        ffo = [None if n is None or d is None or g is None else n + abs(d) - g
               for n, d, g in zip(net_income, da, gains, strict=True)]
        ffo_missing = [", ".join(x for x, v in (("beneficio neto", n), ("amortizaciones", d),
                                                  ("plusvalías por ventas de inmuebles", g)) if v is None)
                       for n, d, g in zip(net_income, da, gains, strict=True)]
        if ffo[-1] is None:
            warnings.append(f"FFO {last} N/D (sin {ffo_missing[-1]} en ninguna fuente): no se valora por FFO "
                            "y se usa el método general, avisado")
        elif any(v is None for v in ffo[:-1]):
            warnings.append("FFO N/D en " + "; ".join(f"{y} (sin {m})" for y, v, m in zip(years, ffo, ffo_missing, strict=True)
                                                     if v is None) + ": esos años quedan fuera de la historia del FFO")
        if ffo[-1] is not None and ffo[-1] > 0:
            net_income = ffo
            earnings_label = "FFO"
            method = {"chosen": "tir_ffo", "discarded": {
                "tir_ev_ebitda": "un REIT reparte casi todo: lo que gana el accionista es el FFO, no el EBITDA",
                "tir_per": ("el beneficio neto resta la amortización de los inmuebles (que no pierden valor como una "
                            "máquina) y suma las plusvalías de ventas: el FFO corrige las dos cosas"),
                "dcf": method["discarded"].get("dcf", ""),
                "sotp": ("el NAV (NOI / tasa de capitalización) necesita la tasa de capitalización de mercado, que "
                         "no es un dato gratuito citado; queda como contraste"),
            }}
            cites["ffo"] = {"formula": "beneficio neto + amortizaciones − plusvalías por ventas de inmuebles",
                            "inputs": [annual.get("net_income", {}).get(last),
                                       annual.get("depreciation_amortization", {}).get(last),
                                       annual.get("gain_on_sale_real_estate", {}).get(last)]}
    elif kind == "pre_revenue":
        method = {"chosen": "caja_runway", "discarded": {
            "tir_ev_ebitda": "sin EBITDA positivo: no hay beneficio que proyectar con una TIR",
            "tir_per": "sin beneficio positivo",
            "dcf": "un DCF de una empresa que aún no gana dinero es la suma de supuestos sin historia propia",
            "sotp": ("se usa solo para las partes que aún no facturan y con sus propias probabilidades; lo que "
                     "decide hoy es cuánta caja queda y cuánto se diluye"),
        }}
    method = {**method, "kind": kind, "kind_reason": kind_reason, "kind_method": KIND_METHODS[kind]}
    chosen_basis = basis or {"tir_per": "pe", "tir_ffo": "pe", "tir_pb": "pb"}.get(method["chosen"], "ev_ebitda")
    price, price_ccy, price_as_of = _price(db, company)
    if price is None:
        raise ValueError("sin precio")
    from app.valuation.currency import normalize_currency

    major, factor = normalize_currency(price_ccy or company.currency or reporting)
    price_ccy = (major or reporting).upper()
    fx_note = None
    if factor and factor != 1:  # cotiza en peniques (GBp/GBX) o centavos: a la unidad de los informes
        price = float(price) / factor
        fx_note = f"cotización en subunidad (÷{factor})"
    listing_price, listing_ccy = float(price), price_ccy
    if price_ccy != reporting:
        conv = convert_amount(db, float(price), price_ccy, reporting, today)
        if conv is None:
            raise ValueError(f"sin tipo de cambio {price_ccy}→{reporting}")
        price, fx_note = conv[0], "; ".join(x for x in (fx_note, conv[1]) if x)
    cites["price"] = {"value": price, "as_of": price_as_of, "currency": reporting, "fx": fx_note,
                      "document": "Cierre de mercado guardado por GerarAI"}
    # acciones (regla «acciones-vigentes-v1», app.valuation.current_shares): las de la portada del último informe
    # (dei:EntityCommonStockSharesOutstanding, TODAS las clases) si es posterior al cierre; si no vale, la media
    # diluida del último ejercicio, avisando; si falta, beneficio / BPA diluido (derivado). Up-C: las clases
    # emparejadas con unidades canjeables se cuentan como acciones (bases EV) o quedan fuera con los
    # minoritarios (bases sobre beneficio atribuible), nunca las dos cosas.
    from app.valuation import current_shares as cs

    shares = _mill(annual.get("shares_diluted", {}).get(last))
    cover = point.get("shares_outstanding")
    cover_sh = _mill(cover)
    eps_last = _f((annual.get("eps_diluted", {}).get(last) or {}).get("value"))
    ni_last = ni_attr[-1] if ni_attr[-1] is not None else series("net_income")[-1]  # no el FFO de un REIT
    implied = (ni_last / eps_last) if (eps_last and ni_last) else None
    shares, rescaled = rescale_shares(shares, cover_sh, implied)
    if rescaled:
        warnings.append(rescaled)
        cites["shares_scale"] = {"factor": 1000, "reason": rescaled,
                                 "references": [x for x in (cover, annual.get("eps_diluted", {}).get(last)) if x]}
    fy_end = _end(str((annual.get("revenue", {}).get(last) or annual.get("net_income", {}).get(last) or {}).get("period") or ""))
    cover_end = _end(str((cover or {}).get("period") or ""))
    by_class = bool((cover or {}).get("class_sum"))
    cover_reject = (cs.cover_check(cover_sh, shares, by_class=by_class) if cover_sh and cover_end > fy_end
                    else ("sin portada posterior al cierre del ejercicio" if cover_sh else "sin portada"))
    upc = None
    if cover_reject is None:
        assert cover_sh is not None
        members = (cover or {}).get("class_members")
        nci_now = _mill(point.get("minority_interest"))
        eq_now = _mill(point.get("total_equity"))
        upc = cs.up_c({k: float(v) / 1_000_000.0 for k, v in members.items()} if members else None,
                      minority_interest=nci_now, total_equity=eq_now,
                      ni_minority=series("net_income_minority")[-1], ni_total=series("net_income_total")[-1])
        if shares is not None and cover_sh < shares:
            warnings.append("acciones de la portada del último informe (sin opciones ni convertibles): por debajo "
                            "de la media diluida del ejercicio")
        if members:
            warnings.append("acciones de la portada: suma de todas las clases (" + ", ".join(
                f"{cs.short(k)} {float(v) / 1e6:,.1f} M" for k, v in sorted(members.items())) + f") a {cover_end}")
        shares = cover_sh
        cites["shares"] = cover
        if upc is not None:
            paired = ", ".join(cs.short(m) for m in upc["paired_classes"])
            if chosen_basis in cs.EV_BASES:
                warnings.append(f"Up-C: las clases {paired} ({upc['paired_shares']:,.1f} M) van con unidades canjeables "
                                f"({upc['share_of_paired_classes']:.0%} de las acciones, minoritarios "
                                f"{upc['share_of_minorities']:.0%} según {upc['minorities_basis']}): cuentan como "
                                "acciones y los minoritarios no se restan")
            else:
                shares = float(upc["listed_shares"])
                warnings.append(f"Up-C: beneficio atribuible por acción de la clase {cs.short(upc['listed_class'])} "
                                f"({shares:,.1f} M); las clases {paired} van con los minoritarios")
            cites["shares_up_c"] = {**upc, "basis": chosen_basis}
    elif shares is not None:
        cites["shares"] = annual["shares_diluted"][last]
        warnings.append(f"acciones: media diluida del ejercicio {last} ({cover_reject})")
    else:
        eps = _f((annual.get("eps_diluted", {}).get(last) or {}).get("value"))
        ni = net_income[-1]
        if eps and ni:
            shares = ni / eps
            cites["shares"] = {"formula": "beneficio neto / BPA diluido del mismo ejercicio",
                               "inputs": [annual.get("net_income", {}).get(last), annual["eps_diluted"][last]]}
            warnings.append("acciones diluidas derivadas como beneficio / BPA diluido (sin dato directo)")
        else:
            raise ValueError("sin acciones diluidas")
    cash_eq = _mill(point.get("cash_and_equivalents"))
    if cash_eq is None:
        # Sin caja la deuda neta no se sabe: N/D con motivo, no caja = 0.
        raise ValueError("sin caja en el último balance: la deuda neta no se puede calcular")
    from app.valuation import balance_bridge as bb

    sti, sti_cite, sti_warn = bb.short_term_investments(point)
    cash = cash_eq + sti
    if sti_warn:
        warnings.append(sti_warn)
    for k in ("cash_and_equivalents", "minority_interest", "hybrid_capital"):
        if k in point:
            cites[k] = point[k]
    if sti_cite is not None:
        cites["short_term_investments"] = sti_cite
    # Los pasivos por arrendamiento ``lease_liabilities*`` solo salen de los mapas IFRS (US GAAP usa
    # operating_lease_liabilities): su presencia identifica a un filer IFRS de la SEC que reporta en USD (BN).
    ifrs = (reporting != "USD"
            or any(str((c or {}).get("source_type") or "").lower().startswith("esef")
                   for c in annual.get("revenue", {}).values())
            or any(k in point for k in ("lease_liabilities", "lease_liabilities_current", "lease_liabilities_noncurrent")))
    debt, debt_cite0, leases_inside, debt_warns = bb.financial_debt(
        point, ifrs=ifrs, lease_at=lambda period: _primary_point_at(db, company, "operating_lease_liabilities", period))
    warnings.extend(debt_warns)
    if debt_cite0 is not None:
        cites["total_debt"] = debt_cite0
    if debt is None and nav_path:
        debt, debt_cite = nav_holding_debt(db, company, last, warnings)
        if debt_cite is not None:
            cites["total_debt"] = debt_cite
    if debt is None:
        # Deuda a largo como último recurso, solo del MISMO balance que la caja: un saldo de otro cierre
        # (TSLA: LongTermDebtNoncurrent de 2014 con la caja de 2026) no es la deuda de hoy.
        debt = _mill(point.get("long_term_debt")) if bb.same_close(point, "long_term_debt") else None
        if debt is not None:
            cites["total_debt"] = point["long_term_debt"]
        if debt is None:
            # Ausencia de etiqueta no prueba deuda 0 (la ingesta ya escribe 0 cuando el balance lo prueba).
            raise ValueError("sin deuda en el último balance: la deuda neta no se puede calcular")
    # El total declarado por el emisor manda; sin él, corriente + no corriente.
    leases_total = _mill(point.get("lease_liabilities"))
    leases_ifrs = leases_total if leases_total else (
        (_mill(point.get("lease_liabilities_current")) or 0.0) + (_mill(point.get("lease_liabilities_noncurrent")) or 0.0))
    for k in ("lease_liabilities", "lease_liabilities_current", "lease_liabilities_noncurrent"):
        if k in point:
            cites[k] = point[k]
    use_leases = ifrs if include_leases is None else include_leases
    if use_leases and leases_inside:
        use_leases = False  # el total del agregador ya los lleva dentro: una sola vez (caja-deuda-v1)
    leases = leases_ifrs if use_leases else 0.0
    if use_leases and not leases_ifrs:
        warnings.append("EBITDA bajo IFRS 16 (incluye los alquileres) pero sin dato de pasivos por arrendamiento: "
                        "la deuda neta no los incluye y el EV queda corto")
    hybrids = _mill(point.get("hybrid_capital")) or 0.0
    if not hybrids:
        warnings.append("capital híbrido: sin dato etiquetado (si existe, se trataría como deuda)")
    minorities = _mill(point.get("minority_interest")) or 0.0
    if minorities and chosen_basis == "ev_ebitda" and (note := bb.stale_note(point, "minority_interest", "minoritarios")):
        warnings.append(note)
    if upc is not None and chosen_basis in cs.EV_BASES:
        minorities = 0.0  # Up-C: ya están en las acciones (todas las clases)
    sbc = _mill(annual.get("stock_based_compensation", {}).get(last))
    sp = engine.StartingPoint(
        price=float(price), shares_diluted=shares, revenue=revenue[-1] or 0.0,
        ebitda=ebitda[-1], net_income=net_income[-1], cash=cash, debt=debt, leases=leases, hybrids=hybrids,
        minorities=minorities if chosen_basis == "ev_ebitda" else 0.0, currency=reporting, basis=chosen_basis,
        sources={"revenue": f"revenue {last}:FY",
                 "ebitda": EBITDA_FORMULAS.get(ebitda_basis.get(last) or OPERATING_PLUS_DA, "")},
        earnings_label=earnings_label,
    )
    if chosen_basis == "pb" and book[-1] is None:  # comparable valorado con la base de la empresa
        eq, pref = series("total_equity"), series("preferred_stock")
        book = [None if e is None else e - (p or 0.0) for e, p in zip(eq, pref, strict=True)]
        if book[-1] is None or book[-1] <= 0:
            raise ValueError("sin valor contable")
    if chosen_basis == "pb":
        # Valor contable: «ingresos» = valor contable, beneficio = el neto; lo repartido (dividendos +
        # recompras) hace de flujo para el accionista, sin capex ni adquisiciones aparte.
        dist = [None if d is None and b is None else abs(d or 0.0) + abs(b or 0.0)
                for d, b in zip(series("dividends_paid"), series("common_stock_repurchased"), strict=True)]
        sp = replace(sp, revenue=book[-1] or 0.0)
        # Lo repartido ya es flujo neto de inversión: su «capex» es 0 por construcción (no un dato ausente).
        hist = rules.History(years=years, revenue=book, earnings=net_income, operating_cash_flow=dist,
                             capex=[None if x is None else 0.0 for x in dist], dividends=series("dividends_paid"),
                             buybacks=series("common_stock_repurchased"), acquisitions=(), sbc=sbc)
    else:
        earnings_series = net_income if chosen_basis == "pe" else ebitda
        ocf, capex_s, acq = series("operating_cash_flow"), series("capital_expenditure"), series("acquisitions")
        if chosen_basis == "pe":
            # beneficio ATRIBUIBLE frente a flujos CONSOLIDADOS: los flujos, a la parte del accionista
            shares_attr = attributable_shares(ni_attr if any(x is not None for x in ni_attr) else net_income,
                                              series("net_income_minority"), series("total_equity"),
                                              series("minority_interest"))
            if any(x is not None and x[0] < 1.0 for x in shares_attr):
                ocf, capex_s, acq = (scale_flows(v, shares_attr) for v in (ocf, capex_s, acq))
                cites["attributable_share"] = {
                    "formula": ("flujo consolidado × parte del accionista (beneficio de la dominante / beneficio "
                                "total; si falta, patrimonio de la dominante / patrimonio total)"),
                    "years": {str(y): None if x is None else {"share": x[0], "from": x[1]}
                              for y, x in zip(years, shares_attr, strict=True)},
                }
                last_share = shares_attr[-1]
                if last_share is not None:
                    warnings.append(f"minoritarios: flujo de caja, capex y adquisiciones consolidados × {last_share[0]:.0%} "
                                    f"(parte del accionista según el {last_share[1]}) para compararlos con el beneficio "
                                    "atribuible")
        hist = rules.History(
            years=years, revenue=revenue, earnings=earnings_series,
            operating_cash_flow=ocf, capex=capex_s,
            dividends=series("dividends_paid"), buybacks=series("common_stock_repurchased"),
            acquisitions=acq, sbc=sbc,
        )
    if chosen_basis != "pb" and not any(a for a in hist.acquisitions if a):
        warnings.append("adquisiciones sin dato: el crecimiento histórico (que puede incluir compras) se toma como orgánico")
    if nav_path and chosen_basis == "pb" and book[-1] and shares:
        nav_ps = book[-1] / shares
        discount = float(price) / nav_ps - 1 if nav_ps > 0 else None
        cites["nav"] = {
            "nav": book[-1], "shares": shares, "nav_per_share": nav_ps, "price": float(price),
            "discount": discount, "currency": reporting, "year": last,
            "nav_per_share_listing": (nav_ps * listing_price / float(price)) if float(price) else None,
            "listing_currency": listing_ccy,
            "formula": "NAV por acción = NAV / acciones; descuento = precio / NAV por acción − 1",
            "source": (cites.get("book_value") or {}).get("inputs", [None])[0],
        }
        warnings.append(
            f"holding sin ingresos operativos: se valora por su NAV ({book[-1]:,.1f} M {reporting}, "
            f"{nav_ps:,.2f} {reporting} por acción a {last}"
            + (f", {nav_ps * listing_price / float(price):,.2f} {listing_ccy} al tipo del precio"
               if listing_ccy != reporting and float(price) else "") + ")"
            + (f"; el precio cotiza un {abs(discount):.0%} {'por debajo' if discount < 0 else 'por encima'} del NAV"
               if discount is not None else ""))
    cites["annual"] = {m: {str(y): annual[m][y] for y in years if y in annual.get(m, {})} for m in _FLOW if m in annual}
    cites["method"] = method
    cites["ifrs16_leases_in_debt"] = use_leases
    derived_years = [y for y in years if ebitda_basis.get(y) in EBITDA_DERIVED]
    if derived_years:
        how = ebitda_basis[derived_years[-1]] or PRETAX_COMPONENTS
        cites["ebitda_basis"] = {"formula": EBITDA_FORMULAS[how], "years": derived_years}
        warnings.append(f"EBITDA derivado como {EBITDA_FORMULAS[how].split(' (')[0]} "
                        f"en {', '.join(str(y) for y in derived_years)}: el emisor no etiqueta el resultado operativo")
    return sp, hist, warnings, cites


def runway(sp: engine.StartingPoint, hist: rules.History, cites: Mapping[str, Any]) -> dict[str, Any]:
    """Caja, consumo y meses de margen de una empresa que aún no gana dinero (fórmulas a la vista).

    consumo anual = −(flujo de caja operativo − capex) del último ejercicio (0 si genera caja);
    meses de margen = (caja + inversiones a corto) / consumo anual × 12;
    dilución = TCAC de las acciones diluidas de los tres últimos ejercicios."""
    ocf = hist.operating_cash_flow[-1] if hist.operating_cash_flow else None
    capex = hist.capex[-1] if hist.capex else None
    fcf = None if ocf is None or capex is None else ocf - abs(capex)
    burn = max(-fcf, 0.0) if fcf is not None else None
    months = (sp.cash / burn * 12.0) if burn else None
    annual = cites.get("annual") or {}
    sh = [(int(y), _mill(c)) for y, c in sorted((annual.get("shares_diluted") or {}).items()) if _mill(c)]
    dil = None
    if len(sh) >= 2:
        (y0, s0), (y1, s1) = sh[max(0, len(sh) - 4)], sh[-1]
        if y1 > y0 and s0 and s0 > 0:
            dil = (s1 / s0) ** (1 / (y1 - y0)) - 1
    rev = sp.revenue or None
    ev = sp.enterprise_value
    year = str(hist.years[-1]) if hist.years else ""
    return {
        "year": year, "cash": sp.cash, "debt": sp.debt, "operating_cash_flow": ocf, "capex": capex,
        "free_cash_flow": fcf, "burn": burn, "months": months, "dilution_cagr": dil,
        "missing": ("sin flujo de caja operativo" if ocf is None else "sin capex") if fcf is None else None,
        "ev_to_cash": (ev / sp.cash) if sp.cash > 0 else None, "ev_to_revenue": (ev / rev) if rev and rev > 0 else None,
        "formulas": {
            "consumo": "−(flujo de caja operativo − capex) del último ejercicio",
            "meses": "(caja + inversiones a corto) / consumo anual × 12",
            "dilucion": "TCAC de las acciones diluidas de los tres últimos ejercicios",
        },
        "sources": {"ocf": (annual.get("operating_cash_flow") or {}).get(year),
                    "capex": (annual.get("capital_expenditure") or {}).get(year)},
    }


def guidance_growth(db: Session, company: Company, last_year: int, revenue_last: float | None
                    ) -> tuple[float | None, dict[str, Any] | None]:
    """Crecimiento de ingresos que da la propia empresa para el ejercicio siguiente al último cerrado
    (guía citada de sus notas de resultados, ``company_guidance``: punto medio, con su frase y su URL)."""
    from app.models.declared_input_value import DeclaredInputValue

    if not revenue_last or revenue_last <= 0:
        return None, None
    row = db.scalars(select(DeclaredInputValue).where(
        DeclaredInputValue.company_id == company.id,
        DeclaredInputValue.input_key == f"guidance.revenue.fy{last_year + 1}",
        DeclaredInputValue.superseded_at.is_(None)).order_by(desc(DeclaredInputValue.id))).first()
    if row is None or row.base is None:
        return None, None
    growth = float(row.base) / 1_000_000.0 / revenue_last - 1
    if not -0.5 < growth < 1.0:
        return None, None
    return growth, {"input_key": row.input_key, "base": float(row.base), "low": _f(row.low), "high": _f(row.high),
                    "url": row.source_url, "quote": row.source_quote,
                    "as_of": row.as_of.isoformat() if row.as_of else None}


def fingerprint(sp: engine.StartingPoint, hist: rules.History, peers: Sequence[Mapping[str, Any]],
                guidance: float | None) -> str:
    blob = json.dumps({"engine": engine.ENGINE_VERSION, "rules": rules.RULES_VERSION, "svc": SERVICE_VERSION,
                       "sp": asdict(sp), "hist": asdict(hist), "peers": list(peers), "guidance": guidance},
                      sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _result_dict(res: Mapping[int, engine.HorizonResult]) -> dict[str, Any]:
    return {str(n): asdict(h) for n, h in res.items()}


def run_valuation(sp: engine.StartingPoint, hist: rules.History, *, peer_multiples: Sequence[float] = (),
                  guidance_growth: float | None = None, probability_choice: str | None = None,
                  discount_rate: float | None = None) -> dict[str, Any]:
    """Todo el cálculo puro: escenarios, TIR, descomposición, sensibilidad y ponderada."""
    scen = rules.build_scenarios(sp, hist, peer_multiples=peer_multiples, guidance_growth=guidance_growth)
    results = {k: engine.evaluate(sp, d) for k, d in scen.drivers.items()}
    prob_key, probs = rules.probabilities(probability_choice)
    growths, mults = rules.sensitivity_axes(sp, scen)
    table = engine.sensitivity(sp, scen.drivers["base"], growths, mults, years=5)
    base10 = results["base"][10]
    frozen = engine.evaluate(sp, engine.replace(scen.drivers["base"], exit_multiple=sp.multiple or 0.0), (10,))[10]
    values = ({k: engine.value_at_rate(sp, d, discount_rate) for k, d in scen.drivers.items()}
              if discount_rate else {})
    weighted_value = (sum(probs[k] * v for k, v in values.items() if v is not None)
                      if values and all(v is not None for v in values.values()) else None)
    return {
        "discount_rate": discount_rate,
        "value_per_share": values,
        "weighted_value_per_share": weighted_value,
        "starting_point": {**asdict(sp), "market_cap": sp.market_cap, "net_debt": sp.net_debt,
                           "enterprise_value": sp.enterprise_value, "multiple": sp.multiple, "margin": sp.margin},
        "scenarios": {k: {"label": rules.SCENARIO_LABELS[k], "drivers": asdict(scen.drivers[k]),
                          "horizons": _result_dict(results[k]),
                          "projection": [asdict(r) for r in engine.project(sp, scen.drivers[k], 10)]}
                      for k in rules.SCENARIOS},
        "trace": scen.trace,
        "warnings": scen.warnings,
        "probabilities": {"choice": prob_key, "values": probs},
        "weighted": {str(n): engine.weighted(results, probs, n) for n in engine.HORIZONS},
        "sensitivity": {"years": 5, "growths": growths, "multiples": mults, "irr": table},
        "base_frozen_multiple_irr_10": frozen.irr,
        "base_irr_10": base10.irr,
        "versions": {"engine": engine.ENGINE_VERSION, "rules": rules.RULES_VERSION},
    }


def value_company(db: Session, company: Company, *, today: date | None = None,
                  probability_choice: str | None = None) -> dict[str, Any]:
    """Lectura completa para la tesis y el Informe. Nunca escribe."""
    today = today or date.today()
    try:
        sp, hist, warnings, cites = starting_point(db, company, today=today)
    except ValueError as exc:
        return {"status": "insufficient", "reason": redact_secrets(str(exc)), "ticker": company.ticker}
    if cites["method"]["chosen"] == "caja_runway":
        rw = runway(sp, hist, cites)
        try:
            from app.services.pre_revenue_valuation import value_pre_revenue

            pre = value_pre_revenue(db, company, sp=sp, hist=hist, cites=cites, runway=rw, today=today)
        except Exception as exc:  # noqa: BLE001 - sin la ruta de preingresos queda el runway, nunca una ficha vacía
            logger.info("preingresos %s: %s", company.ticker, type(exc).__name__)
            pre = {"error": redact_secrets(f"{type(exc).__name__}: {exc}")[:300]}
        return {"status": "not_meaningful", "ticker": company.ticker, "as_of": today.isoformat(),
                "reason": ("empresa sin beneficio que proyectar (" + cites["method"]["kind_reason"] + "): se valora por "
                           "su caja, su consumo y su dilución, y por la suma de partes de lo que aún no factura"),
                "method": cites["method"], "runway": rw, "pre_revenue": pre,
                "peers": [{"ticker": p["ticker"], "name": p.get("name"), "selection": pre.get("peer_layer"),
                           "multiple": p["multiple"], "multiple_basis": "ev_sales"} for p in pre.get("peers") or []],
                "starting_point": {**asdict(sp), "market_cap": sp.market_cap, "net_debt": sp.net_debt,
                                   "enterprise_value": sp.enterprise_value, "multiple": sp.multiple,
                                   "margin": sp.margin},
                "citations": cites, "warnings": warnings, "fingerprint": fingerprint(sp, hist, [], None)}
    if cites["method"]["chosen"] == "sotp":
        return {"status": "not_applicable", "method": cites["method"], "ticker": company.ticker,
                "warnings": warnings}
    peers = _peer_multiples(db, company, sp.basis, today)
    multiples = [p["multiple"] for p in peers if p.get("multiple")]
    last_year = max(int(y) for y in cites["annual"].get("revenue", {"0": None}))
    # La guía de ingresos no es la de un valor contable: con la base pb no se usa.
    guidance, guidance_cite = guidance_growth(db, company, last_year, sp.revenue) if sp.basis != "pb" else (None, None)
    cites["guidance"] = guidance_cite
    fp = fingerprint(sp, hist, peers, guidance)
    rate = rate_source = None
    try:
        from app.services.expert_team.sotp_valuer import _capm_cost_of_equity

        capm = _capm_cost_of_equity(db, company)
        if capm is not None:
            rate, rate_source = capm
    except Exception:  # noqa: BLE001 - sin tasa no hay «valor a la tasa exigida», la TIR sigue
        rate = None
    try:
        out = run_valuation(sp, hist, peer_multiples=multiples, guidance_growth=guidance,
                            probability_choice=probability_choice, discount_rate=rate)
    except ValueError as exc:
        return {"status": "not_meaningful", "reason": redact_secrets(str(exc)), "ticker": company.ticker, "method": cites["method"],
                "starting_point": {**asdict(sp), "market_cap": sp.market_cap, "net_debt": sp.net_debt,
                                   "enterprise_value": sp.enterprise_value, "multiple": sp.multiple,
                                   "margin": sp.margin},
                "citations": cites, "warnings": warnings, "fingerprint": fp}
    out["discount_rate_source"] = rate_source
    out.update({"status": "ok", "ticker": company.ticker, "as_of": today.isoformat(), "fingerprint": fp,
                "method": cites["method"], "peers": peers, "citations": cites,
                "warnings": warnings + out["warnings"], "guidance_growth": guidance})
    return out


__all__ = ["KIND_METHODS", "choose_method", "company_facts", "company_kind", "runway", "fingerprint", "run_valuation", "starting_point", "value_company"]
