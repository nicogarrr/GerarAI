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
from dataclasses import asdict
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import redact_secrets
from app.models import Company, FinancialFact
from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules

logger = logging.getLogger(__name__)

SERVICE_VERSION = "shareholder-irr-service-v1"
HISTORY_YEARS = 10
_FLOW = ("revenue", "operating_income", "depreciation_amortization", "ebitda", "net_income",
         "net_income_attributable", "operating_cash_flow", "capital_expenditure", "dividends_paid",
         "common_stock_repurchased", "acquisitions", "stock_based_compensation", "shares_diluted",
         "eps_diluted", "free_cash_flow", "interest_expense")
_POINT = ("cash_and_equivalents", "short_term_investments", "total_debt", "long_term_debt",
          "operating_lease_liabilities", "lease_liabilities_current", "lease_liabilities_noncurrent",
          "minority_interest", "hybrid_capital", "shares_outstanding", "total_equity")
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
            cur = point.get(fact.metric)
            if cur is None or end > cur[0] or (end == cur[0] and rank < cur[1]):
                point[fact.metric] = (end, rank, _cite(fact))
    return ({m: {y: c for y, (_, c) in v.items()} for m, v in annual.items()},
            {m: c for m, (_, _, c) in point.items()})


def _mill(cite: Mapping[str, Any] | None) -> float | None:
    v = _f((cite or {}).get("value"))
    return None if v is None else v / 1_000_000.0


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
    years = sorted(set(annual.get("revenue", {})))[-HISTORY_YEARS:]
    if not years:
        raise ValueError("sin ingresos anuales")
    last = years[-1]

    def series(metric: str) -> list[float | None]:
        return [_mill(annual.get(metric, {}).get(y)) for y in years]

    def ebitda_for(y: int) -> float | None:
        oi = _mill(annual.get("operating_income", {}).get(y))
        da = _mill(annual.get("depreciation_amortization", {}).get(y))
        if oi is not None and da is not None:
            return oi + abs(da)
        return _mill(annual.get("ebitda", {}).get(y))

    revenue = series("revenue")
    ebitda = [ebitda_for(y) for y in years]
    ni_attr = series("net_income_attributable")
    net_income = [a if a is not None else n for a, n in zip(ni_attr, series("net_income"), strict=True)]
    reporting = str((annual.get("revenue", {}).get(last) or {}).get("unit") or company.currency or "USD").upper()[:3]
    financial = _is_financial(company)
    method = choose_method(revenue=revenue[-1], ebitda_years=ebitda, net_income=net_income[-1],
                           financial=financial, segment_ebitda=False)
    chosen_basis = basis or ("pe" if method["chosen"] == "tir_per" else "ev_ebitda")
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
    # acciones diluidas: media diluida del último ejercicio; si falta, beneficio / BPA diluido (derivado)
    shares = _mill(annual.get("shares_diluted", {}).get(last))
    if shares is not None:
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
        minorities=minorities if chosen_basis != "pe" else 0.0, currency=reporting, basis=chosen_basis,
        sources={"revenue": f"revenue {last}:FY", "ebitda": "resultado operativo + amortizaciones del ejercicio"},
    )
    earnings_series = net_income if chosen_basis == "pe" else ebitda
    hist = rules.History(
        years=years, revenue=revenue, earnings=earnings_series,
        operating_cash_flow=series("operating_cash_flow"), capex=series("capital_expenditure"),
        dividends=series("dividends_paid"), buybacks=series("common_stock_repurchased"),
        acquisitions=series("acquisitions"), sbc=sbc,
    )
    if not any(a for a in hist.acquisitions if a):
        warnings.append("adquisiciones sin dato: el crecimiento histórico (que puede incluir compras) se toma como orgánico")
    cites["annual"] = {m: {str(y): annual[m][y] for y in years if y in annual.get(m, {})} for m in _FLOW if m in annual}
    cites["method"] = method
    cites["ifrs16_leases_in_debt"] = use_leases
    return sp, hist, warnings, cites


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
    if cites["method"]["chosen"] == "sotp":
        return {"status": "not_applicable", "method": cites["method"], "ticker": company.ticker,
                "warnings": warnings}
    peers = _peer_multiples(db, company, sp.basis, today)
    multiples = [p["multiple"] for p in peers if p.get("multiple")]
    guidance = None  # la guía citada de fuentes-1 entra aquí cuando esté en main (company_guidance)
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
                                   "enterprise_value": sp.enterprise_value, "multiple": sp.multiple},
                "citations": cites, "warnings": warnings, "fingerprint": fp}
    out["discount_rate_source"] = rate_source
    out.update({"status": "ok", "ticker": company.ticker, "as_of": today.isoformat(), "fingerprint": fp,
                "method": cites["method"], "peers": peers, "citations": cites,
                "warnings": warnings + out["warnings"], "guidance_growth": guidance})
    return out


__all__ = ["choose_method", "company_facts", "fingerprint", "run_valuation", "starting_point", "value_company"]
