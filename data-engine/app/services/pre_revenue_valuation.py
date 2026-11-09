"""Datos de la ruta de valoración de preingresos / quema caja (lectura pura; sin modelo, sin red).

Junta, con su fuente, lo que la regla pre-registrada de :mod:`app.valuation.pre_revenue_irr` necesita: el
ancla de ingresos a 3–5 años (firmas citadas, consenso de prensa, guía de la empresa o cartera contratada
del filing) y los comparables MADUROS con su EV/ventas calculado con la misma fórmula que la empresa
(:func:`app.services.shareholder_irr_service.starting_point`), con la capa de selección usada.
General: nada depende del emisor.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import desc, select

from app.models import Company, FinancialFact
from app.valuation import pre_revenue_irr as rules

logger = logging.getLogger(__name__)

#: Candidatos máximos por capa ancha (industria, sector, base): acota el coste en una base grande.
MAX_CANDIDATES = 60
_MATURE_KINDS = ("operating",)


def _tenant(db: Any, company: Any) -> int | None:
    t = db.info.get("tenant_id") if hasattr(db, "info") else None
    if type(t) is int and t > 0:
        return t
    t = getattr(company, "tenant_id", None)
    return t if type(t) is int else None


def _convert(db: Any, value: float, unit: str | None, ccy: str, today: date) -> tuple[float | None, str | None]:
    unit = (unit or ccy or "").upper()[:3]
    if not unit or unit == ccy:
        return value, None
    try:
        from app.services.user_sotp_service import convert_amount

        conv = convert_amount(db, value, unit, ccy, today)
    except Exception:  # noqa: BLE001
        conv = None
    if conv is None:
        return None, f"en {unit} sin tipo de cambio guardado a {ccy}"
    return conv[0], conv[1]


def revenue_anchors(db: Any, company: Company, *, last_fy: int, ccy: str, today: date) -> list[rules.RevenueAnchor]:
    """Todas las anclas de ingresos (millones de ``ccy``) a 3–5 años que GerarAI ya tiene, con su cita."""
    out: list[rules.RevenueAnchor] = []
    years = range(last_fy + rules.HORIZON_MIN, last_fy + rules.HORIZON_MAX + 1)
    tenant = _tenant(db, company)
    try:
        from app.services.analyst_consensus import aggregate, history_for

        agg = aggregate(history_for(db, company, tenant)) if tenant is not None else []
    except Exception as exc:  # noqa: BLE001 - sin estimaciones, siguiente fuente
        logger.info("preingresos analistas: %s", type(exc).__name__)
        agg = []
    for item in agg:
        if item.get("metric") != "revenue" or item.get("year") not in years:
            continue
        unit = ccy  # las estimaciones de prensa se guardan en la divisa del listado (USD en EE. UU.)
        if item.get("n_firms") and item.get("median"):
            low = item["low"] if item["n_firms"] >= 2 else None
            high = item["high"] if item["n_firms"] >= 2 else None
            out.append(rules.RevenueAnchor(
                int(item["year"]), float(item["median"]), low, high, "analistas",
                f"mediana de {item['n_firms']} firma(s) citadas, ingresos {item['year']}",
                {"firms": item.get("firms"), "unit": unit}))
        pc = item.get("press_consensus")
        if pc and pc.get("value_millions"):
            out.append(rules.RevenueAnchor(int(item["year"]), float(pc["value_millions"]), None, None,
                                           "consenso_prensa", f"consenso citado en prensa, ingresos {item['year']}",
                                           {"url": pc.get("url"), "as_of": pc.get("as_of"), "unit": unit}))
    try:
        from app.models.declared_input_value import DeclaredInputValue

        rows = db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.company_id == company.id,
            DeclaredInputValue.input_key.in_([f"guidance.revenue.fy{y}" for y in years]),
            DeclaredInputValue.superseded_at.is_(None)).order_by(desc(DeclaredInputValue.id))).all()
    except Exception:  # noqa: BLE001
        rows = []
    seen: set[str] = set()
    for row in rows:
        if row.input_key in seen or row.base is None:
            continue
        seen.add(row.input_key)
        vals = []
        for v in (row.base, row.low, row.high):
            if v is None:
                vals.append(None)
                continue
            conv, _how = _convert(db, float(v) / 1e6, row.unit, ccy, today)
            vals.append(conv)
        if vals[0] is None:
            continue
        year = int(row.input_key.rsplit("fy", 1)[1])
        out.append(rules.RevenueAnchor(year, vals[0], vals[1], vals[2], "guia", f"guía de la empresa, ingresos {year}",
                                       {"url": row.source_url, "quote": row.source_quote,
                                        "as_of": row.as_of.isoformat() if row.as_of else None}))
    fact = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                  FinancialFact.metric == "backlog",
                                                  FinancialFact.value.is_not(None))
                      .order_by(desc(FinancialFact.period), desc(FinancialFact.id))).first()
    if fact is not None and float(fact.value) > 0:
        conv, _how = _convert(db, float(fact.value) / 1e6, fact.unit, ccy, today)
        if conv is not None:
            year = last_fy + rules.HORIZON_MIN
            from app.services.shareholder_irr_service import _cite

            out.append(rules.RevenueAnchor(
                year, conv / rules.HORIZON_MIN, None, None, "backlog",
                f"cartera contratada ({fact.period}) repartida en {rules.HORIZON_MIN} años: suelo contratado",
                {**_cite(fact), "total_millions": conv}))
    return out


def _mature_multiple(db: Any, peer: Company, today: date, memo: dict[int, Any]) -> rules.PeerMultiple | None:
    if peer.id in memo:
        return memo[peer.id]
    from app.services.shareholder_irr_service import _is_financial, starting_point

    res = None
    try:
        sp, _hist, _w, cites = starting_point(db, peer, today=today, basis="ev_ebitda")
        kind = (cites.get("method") or {}).get("kind")
        if (kind in _MATURE_KINDS and not _is_financial(peer) and sp.revenue and sp.revenue > 0
                and sp.enterprise_value > 0):
            res = rules.PeerMultiple(peer.ticker, peer.name, float(sp.enterprise_value), float(sp.revenue))
    except ValueError:  # sin precio, sin ingresos…: un comparable sin datos no entra
        res = None
    except Exception as exc:  # noqa: BLE001 - un comparable roto no tumba la ficha
        logger.info("preingresos comparable %s: %s", peer.ticker, type(exc).__name__)
        db.rollback()
        res = None
    memo[peer.id] = res
    return res


def _known(text: Any) -> str | None:
    t = str(text or "").strip()
    return None if t.lower() in ("", "unknown", "n/a", "none") else t


def mature_peers(db: Any, company: Company, today: date) -> tuple[list[rules.PeerMultiple], str | None, str | None,
                                                                   list[dict[str, Any]]]:
    """(comparables maduros, capa usada, motivo si no hay, intentos por capa)."""
    from app.services.peer_comparison_service import _same_issuer

    memo: dict[int, Any] = {}
    tried: list[dict[str, Any]] = []

    def run(label: str, cands: list[Company]) -> list[rules.PeerMultiple]:
        got = []
        for c in cands:
            if c.id == company.id or _same_issuer(company, c):
                continue
            pm = _mature_multiple(db, c, today, memo)
            if pm is not None:
                got.append(pm)
        tried.append({"capa": label, "candidatos": len(cands), "maduros": len(got)})
        return got

    try:
        from app.services.peer_comparison_service import PeerComparisonService

        svc_peers, _basis, _trace = PeerComparisonService()._find_peers(db, company, 8)
    except Exception as exc:  # noqa: BLE001
        logger.info("preingresos comparables: %s", type(exc).__name__)
        db.rollback()
        svc_peers = []
    with_revenue = (select(FinancialFact.company_id).where(FinancialFact.metric == "revenue",
                                                           FinancialFact.period.like("%:FY")).distinct())
    tiers: list[tuple[str, list[Company]]] = [("comparables del servicio de comparables", list(svc_peers))]
    industry, sector = _known(company.industry), _known(company.sector)
    base_q = select(Company).where(Company.id != company.id, Company.id.in_(with_revenue)).order_by(Company.ticker)
    if industry:
        tiers.append((f"misma industria ({industry})",
                      list(db.scalars(base_q.where(Company.industry == company.industry).limit(MAX_CANDIDATES)).all())))
    if sector:
        tiers.append((f"mismo sector ({sector})",
                      list(db.scalars(base_q.where(Company.sector == company.sector).limit(MAX_CANDIDATES)).all())))
    tiers.append(("toda la base no financiera (sin comparables suficientes del sector)",
                  list(db.scalars(base_q.limit(MAX_CANDIDATES)).all())))
    for label, cands in tiers:
        got = run(label, cands)
        if len(got) >= rules.MIN_PEERS:
            return got, label, None, tried
    return [], None, (f"menos de {rules.MIN_PEERS} comparables maduros con ingresos y EV positivos en ninguna capa "
                      "(servicio, industria, sector, base)"), tried


def value_pre_revenue(db: Any, company: Company, *, sp: Any, hist: Any, cites: Mapping[str, Any],
                      runway: Mapping[str, Any], today: date) -> dict[str, Any]:
    """Runway en trimestres, dilución histórica y proyectada, y la TIR de cada escenario o N/D con su motivo."""
    ccy = sp.currency
    last_fy = int(hist.years[-1]) if hist.years else today.year - 1
    rev_cite = ((cites.get("annual") or {}).get("revenue") or {}).get(str(last_fy)) or {}
    try:
        fy_month = int(str(rev_cite.get("period") or "")[5:7]) or 12
    except ValueError:
        fy_month = 12
    fcf = runway.get("free_cash_flow")
    rw = rules.runway(sp.cash, fcf, missing=runway.get("missing"))
    anchors = revenue_anchors(db, company, last_fy=last_fy, ccy=ccy, today=today)
    anchor, anchor_missing = rules.choose_anchor(anchors, last_fy)
    peers, layer, peers_missing, tried = mature_peers(db, company, today)
    stats = rules.peer_stats(peers)
    scen = rules.scenarios(today=today, price=sp.price, shares=sp.shares_diluted, cash=sp.cash,
                           debt=sp.debt + sp.leases, minorities=sp.minorities, hybrids=sp.hybrids, fcf=fcf,
                           dilution_hist=runway.get("dilution_cagr"), anchor=anchor, anchor_missing=anchor_missing,
                           peers=stats, peers_missing=peers_missing, last_fy=last_fy, fy_end_month=fy_month)
    payload = {
        "rules": rules.RULES_VERSION, "currency": ccy, "last_fiscal_year": last_fy,
        "runway": {**rw, "cash": sp.cash, "free_cash_flow": fcf,
                   "sources": {"cash": cites.get("cash_and_equivalents"),
                               "short_term_investments": cites.get("short_term_investments"),
                               **dict(runway.get("sources") or {})}},
        "dilution": {"historical_cagr": runway.get("dilution_cagr"),
                     "projected": {k: scen[k].get("dilution") for k in rules.SCENARIOS},
                     "price": sp.price},
        "revenue_anchor": None if anchor is None else {
            "year": anchor.year, "base": anchor.base, "low": anchor.low, "high": anchor.high, "source": anchor.source,
            "label": anchor.label, "cite": dict(anchor.cite)},
        "revenue_anchor_missing": anchor_missing,
        "anchors_found": [{"year": a.year, "source": a.source, "base": a.base} for a in anchors],
        "peers": [{"ticker": p.ticker, "name": p.name, "ev": p.ev, "revenue": p.revenue, "multiple": p.multiple}
                  for p in sorted(peers, key=lambda p: p.multiple)],
        "peer_layer": layer, "peer_stats": stats, "peers_missing": peers_missing, "peer_layers_tried": tried,
        "scenarios": scen, "formulas": rules.FORMULAS,
    }
    payload["fingerprint"] = hashlib.sha256(json.dumps(
        {k: payload[k] for k in ("rules", "runway", "revenue_anchor", "peers", "scenarios")},
        sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    return payload


__all__ = ["mature_peers", "revenue_anchors", "value_pre_revenue"]
