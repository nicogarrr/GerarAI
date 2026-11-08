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
from app.valuation.ebitda_components import DERIVED as EBITDA_DERIVED
from app.valuation.ebitda_components import FORMULAS as EBITDA_FORMULAS
from app.valuation.ebitda_components import (
    OPERATING_PLUS_DA,
    PRETAX_COMPONENTS,
    ebitda_from_components,
    pretax_income,
)

logger = logging.getLogger(__name__)

SERVICE_VERSION = "shareholder-irr-service-v2"
HISTORY_YEARS = 10
_FLOW = ("revenue", "operating_income", "depreciation_amortization", "ebitda", "net_income",
         "net_income_attributable", "operating_cash_flow", "capital_expenditure", "dividends_paid",
         "common_stock_repurchased", "acquisitions", "stock_based_compensation", "shares_diluted",
         "eps_diluted", "free_cash_flow", "interest_expense", "earned_premiums", "lease_income",
         "gain_on_sale_real_estate", "income_before_tax", "income_tax_expense", "finance_income_cost",
         "net_income_total")
_POINT = ("cash_and_equivalents", "short_term_investments", "total_debt", "long_term_debt",
          "operating_lease_liabilities", "lease_liabilities_current", "lease_liabilities_noncurrent",
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


def _end(period: str) -> str:
    return str(period or "").split(":")[0]


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
            try:
                year = int(_end(period)[:4])
            except ValueError:
                continue
            slot = annual.setdefault(fact.metric, {})
            if year not in slot or rank < slot[year][0]:
                slot[year] = (rank, _cite(fact))
        elif fact.metric in _POINT:
            end = _end(period)
            if fact.metric in _POINT_ANNUAL and period.endswith(":FY"):
                try:
                    year = int(end[:4])
                except ValueError:
                    year = None
                if year is not None:
                    slot = annual.setdefault(fact.metric, {})
                    if year not in slot or rank < slot[year][0]:
                        slot[year] = (rank, _cite(fact))
            cur = point.get(fact.metric)
            if cur is None or end > cur[0] or (end == cur[0] and rank < cur[1]):
                point[fact.metric] = (end, rank, _cite(fact))
    return ({m: {y: c for y, (_, c) in v.items()} for m, v in annual.items()},
            {m: c for m, (_, _, c) in point.items()})


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
    top = max(x for x in (rev, lease, 0.0) if x is not None)
    if key == "pre_revenue" or top < PRE_REVENUE_MAX:
        return "pre_revenue", (f"ingresos de {last} por debajo de {PRE_REVENUE_MAX:g} M" if top < PRE_REVENUE_MAX
                               else "preingresos según la clasificación de la ficha")
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
        fcf = (ocf - abs(capex or 0.0)) if ocf is not None else None
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


def starting_point(db: Session, company: Company, *, today: date, basis: str | None = None,
                   include_leases: bool | None = None
                   ) -> tuple[engine.StartingPoint, rules.History, list[str], dict[str, Any]]:
    """Punto de partida normalizado + historia anual. Devuelve también avisos y las citas usadas."""
    from app.services.user_sotp_service import _price, convert_amount

    annual, point = company_facts(db, company)
    warnings: list[str] = []
    cites: dict[str, Any] = {}
    kind, kind_reason = company_kind(company, annual)
    if kind == "real_estate":
        # Un REIT etiqueta a menudo solo el arrendamiento (Camden: «Revenues» hasta 2016 y después
        # OperatingLeaseLeaseIncome): los ingresos de cada año son el mayor de los dos datos.
        rev_slot = annual.setdefault("revenue", {})
        for y, cite in (annual.get("lease_income") or {}).items():
            if _mill(cite) is not None and (_mill(rev_slot.get(y)) or 0.0) < (_mill(cite) or 0.0):
                rev_slot[y] = cite
    years = sorted(set(annual.get("revenue", {})))[-HISTORY_YEARS:]
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
    reporting = str((annual.get("revenue", {}).get(last) or {}).get("unit") or company.currency or "USD").upper()[:3]
    financial = _is_financial(company) or kind in ("insurer", "bank", "holding")
    method = choose_method(revenue=revenue[-1], ebitda_years=ebitda, net_income=net_income[-1],
                           financial=financial, segment_ebitda=False)
    book = [None] * len(years)
    earnings_label = ""
    if kind in ("insurer", "bank", "holding"):
        eq, pref = series("total_equity"), series("preferred_stock")
        book = [None if e is None else e - (p or 0.0) for e, p in zip(eq, pref, strict=True)]
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
        else:
            warnings.append("sin valor contable por ejercicio: se valora por el beneficio (PER) y se avisa")
    elif kind == "real_estate":
        gains = series("gain_on_sale_real_estate")
        da = series("depreciation_amortization")
        ffo = [None if n is None else n + abs(d or 0.0) - (g or 0.0) for n, d, g in zip(net_income, da, gains, strict=True)]
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
            if gains[-1] is None:
                warnings.append("plusvalías por ventas de inmuebles sin etiquetar: el FFO puede estar inflado")
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
    if price_ccy != reporting:
        conv = convert_amount(db, float(price), price_ccy, reporting, today)
        if conv is None:
            raise ValueError(f"sin tipo de cambio {price_ccy}→{reporting}")
        price, fx_note = conv[0], "; ".join(x for x in (fx_note, conv[1]) if x)
    cites["price"] = {"value": price, "as_of": price_as_of, "currency": reporting, "fx": fx_note,
                      "document": "Cierre de mercado guardado por GerarAI"}
    # acciones: las de la portada del último informe (dei:EntityCommonStockSharesOutstanding) si son
    # posteriores al cierre y coherentes con la media diluida (±20 %: una portada por clase no es el total);
    # si no, la media diluida del último ejercicio; si falta, beneficio / BPA diluido (derivado)
    shares = _mill(annual.get("shares_diluted", {}).get(last))
    cover = point.get("shares_outstanding")
    cover_sh = _mill(cover)
    fy_end = _end(str((annual.get("revenue", {}).get(last) or annual.get("net_income", {}).get(last) or {}).get("period") or ""))
    cover_end = _end(str((cover or {}).get("period") or ""))
    if cover_sh and cover_end > fy_end and (shares is None or 0.8 <= cover_sh / shares <= 1.2):
        if shares is not None and cover_sh < shares:
            warnings.append("acciones de la portada del último informe (sin opciones ni convertibles): por debajo "
                            "de la media diluida del ejercicio")
        shares = cover_sh
        cites["shares"] = cover
    elif shares is not None:
        cites["shares"] = annual["shares_diluted"][last]
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
    cash = (_mill(point.get("cash_and_equivalents")) or 0.0) + (_mill(point.get("short_term_investments")) or 0.0)
    for k in ("cash_and_equivalents", "short_term_investments", "total_debt", "minority_interest", "hybrid_capital"):
        if k in point:
            cites[k] = point[k]
    debt = _mill(point.get("total_debt"))
    if debt is None:
        debt = _mill(point.get("long_term_debt"))
        if debt is None:
            warnings.append("deuda sin dato: se toma 0 y se avisa")
            debt = 0.0
    ifrs = reporting != "USD" or any(str((c or {}).get("source_type") or "").lower().startswith("esef")
                                     for c in annual.get("revenue", {}).values())
    leases_ifrs = (_mill(point.get("lease_liabilities_current")) or 0.0) + (_mill(point.get("lease_liabilities_noncurrent")) or 0.0)
    use_leases = ifrs if include_leases is None else include_leases
    leases = leases_ifrs if use_leases else 0.0
    if use_leases and not leases_ifrs:
        warnings.append("EBITDA bajo IFRS 16 (incluye los alquileres) pero sin dato de pasivos por arrendamiento: "
                        "la deuda neta no los incluye y el EV queda corto")
    hybrids = _mill(point.get("hybrid_capital")) or 0.0
    if not hybrids:
        warnings.append("capital híbrido: sin dato etiquetado (si existe, se trataría como deuda)")
    minorities = _mill(point.get("minority_interest")) or 0.0
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
        hist = rules.History(years=years, revenue=book, earnings=net_income, operating_cash_flow=dist,
                             capex=[None] * len(years), dividends=series("dividends_paid"),
                             buybacks=series("common_stock_repurchased"), acquisitions=(), sbc=sbc)
    else:
        earnings_series = net_income if chosen_basis == "pe" else ebitda
        hist = rules.History(
            years=years, revenue=revenue, earnings=earnings_series,
            operating_cash_flow=series("operating_cash_flow"), capex=series("capital_expenditure"),
            dividends=series("dividends_paid"), buybacks=series("common_stock_repurchased"),
            acquisitions=series("acquisitions"), sbc=sbc,
        )
    if chosen_basis != "pb" and not any(a for a in hist.acquisitions if a):
        warnings.append("adquisiciones sin dato: el crecimiento histórico (que puede incluir compras) se toma como orgánico")
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
    fcf = None if ocf is None else ocf - abs(capex or 0.0)
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
        return {"status": "not_meaningful", "ticker": company.ticker, "as_of": today.isoformat(),
                "reason": ("empresa sin beneficio que proyectar (" + cites["method"]["kind_reason"] + "): se valora por "
                           "su caja, su consumo y su dilución, y por la suma de partes de lo que aún no factura"),
                "method": cites["method"], "runway": runway(sp, hist, cites),
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
