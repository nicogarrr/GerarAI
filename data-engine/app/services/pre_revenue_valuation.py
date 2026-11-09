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


def revenue_anchors(db: Any, company: Company, *, last_fy: int, ccy: str, today: date,
                    last_revenue: float | None = None) -> list[rules.RevenueAnchor]:
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
    contract = official_contract_anchor(db, company, last_fy=last_fy, ccy=ccy, today=today)
    if contract is not None:
        filed = [a for a in out if a.source == "backlog"]
        if not filed or contract.cite["total_millions"] > float(filed[0].cite.get("total_millions") or 0):
            out.insert(out.index(filed[0]) if filed else len(out), contract)
    own = own_estimate_anchor(company, last_fy=last_fy, last_revenue=last_revenue)
    if own is not None:
        out.append(own)
    return out


def own_estimate_anchor(company: Company, *, last_fy: int, last_revenue: float | None) -> rules.RevenueAnchor | None:
    """Ancla e. del paso 3: estimación propia por fase e industria (solo la usa ``choose_anchor`` si no hay otra)."""
    from app.services.sic_classification import company_sic
    from app.valuation import revenue_phase_rates as phase_rates

    est, label = phase_rates.estimate(company_sic(company), last_revenue, rules.HORIZON_MAX)
    if est is None:
        return None
    return rules.RevenueAnchor(last_fy + rules.HORIZON_MAX, est["base"], est["low"], est["high"], "estimacion_propia",
                               label, {"rules": phase_rates.RULES_VERSION, "source": phase_rates.SOURCE,
                                       "phase": est["phase"], "sic_group": est["group"], "n": est["n"],
                                       "inactive_share": est["inactivas"], "ratios": est["ratios"],
                                       "last_revenue_millions": last_revenue, "last_fiscal_year": last_fy})


def official_contract_anchor(db: Any, company: Company, *, last_fy: int, ccy: str, today: date
                             ) -> rules.RevenueAnchor | None:
    """Un contrato oficial (8-K/6-K o nota de prensa) con importe EXPLÍCITAMENTE atribuido a la empresa, como
    cartera contratada repartida en ``HORIZON_MIN`` años. Sin importe atribuible (lo normal), None: nada cambia."""
    try:
        from app.services.official_catalysts import catalysts_for

        cats = [c for c in catalysts_for(db, company, today=today)
                if c.get("amount_for_company_value") and c.get("amount_currency")]
    except Exception as exc:  # noqa: BLE001
        logger.info("preingresos catalizadores: %s", type(exc).__name__)
        return None
    for c in cats:  # el más reciente primero
        conv, _how = _convert(db, float(c["amount_for_company_value"]) / 1e6, c["amount_currency"], ccy, today)
        if conv is None or conv <= 0:
            continue
        return rules.RevenueAnchor(
            last_fy + rules.HORIZON_MIN, conv / rules.HORIZON_MIN, None, None, "backlog",
            f"contrato oficial atribuido a la empresa ({c.get('date')}, {c.get('publisher')}) repartido en "
            f"{rules.HORIZON_MIN} años: suelo contratado",
            {"url": c.get("url"), "quote": c.get("summary"), "as_of": c.get("date"), "amount": c.get("amount_for_company"),
             "total_millions": conv})
    return None


#: Exchanges que no son una cotización (ficha de una empresa privada o sin mercado).
UNLISTED_EXCHANGES = frozenset({"", "PRIVATE", "PRIVADA", "UNLISTED", "NONE", "N/A", "UNKNOWN"})
#: Comparables del grupo SIC declarado: los de capitalización más cercana (distancia logarítmica).
GROUP_NEAREST = 12
#: Regla de afinidad de negocio dentro del grupo SIC (:mod:`app.services.business_affinity`).
AFFINITY_RULE = "afinidad-negocio-v1"
#: Banda de tamaño de los afines: capitalización a menos de 30 veces la del emisor (en los dos sentidos).
AFFINE_SIZE_RATIO = 30.0
PRIVATE_REASON = "N/D (privada, sin cotización)"


def _unlisted_reason(peer: Company, exc: Exception) -> str | None:
    """Motivo visible de un candidato que no puede dar múltiplo por no cotizar (None si es otro fallo)."""
    if "sin precio" not in str(exc):
        return None
    if str(getattr(peer, "exchange", "") or "").strip().upper() in UNLISTED_EXCHANGES:
        return PRIVATE_REASON
    return "N/D (sin precio de mercado guardado)"


def _mature_multiple(db: Any, peer: Company, today: date, memo: dict[int, Any],
                     excluded: dict[int, str] | None = None) -> rules.PeerMultiple | None:
    if peer.id in memo:
        return memo[peer.id]
    from app.services.shareholder_irr_service import _is_financial, starting_point

    res = None
    if (excluded is not None and str(getattr(peer, "exchange", "") or "").strip().upper() in UNLISTED_EXCHANGES
            and not getattr(peer, "cik", None)):
        # Sin cotización ni filings: nunca da múltiplo (ni con valoraciones de prensa).
        excluded[peer.id] = PRIVATE_REASON
        memo[peer.id] = None
        return None
    try:
        sp, _hist, _w, cites = starting_point(db, peer, today=today, basis="ev_ebitda")
        kind = (cites.get("method") or {}).get("kind")
        if (kind in _MATURE_KINDS and not _is_financial(peer) and sp.revenue and sp.revenue > 0
                and sp.enterprise_value > 0):
            res = rules.PeerMultiple(peer.ticker, peer.name, float(sp.enterprise_value), float(sp.revenue),
                                     revenue_cagr(db, peer))
        elif excluded is not None and kind == "pre_revenue":
            excluded[peer.id] = "sin múltiplo maduro (preingresos o quema caja: su EV/ventas no es de salida)"
    except ValueError as exc:  # sin precio, sin ingresos…: un comparable sin datos no entra
        res = None
        why = _unlisted_reason(peer, exc)
        if why and excluded is not None:
            excluded[peer.id] = why
    except Exception as exc:  # noqa: BLE001 - un comparable roto no tumba la ficha
        logger.info("preingresos comparable %s: %s", peer.ticker, type(exc).__name__)
        db.rollback()
        res = None
    memo[peer.id] = res
    return res


def revenue_cagr(db: Any, company: Company, years: int = 3) -> float | None:
    """TCAC de ingresos de los ``years`` últimos ejercicios (hechos FY), o None si falta un extremo."""
    try:
        rows = db.execute(select(FinancialFact.period, FinancialFact.value).where(
            FinancialFact.company_id == company.id, FinancialFact.metric == "revenue",
            FinancialFact.period.like("%:FY")).order_by(desc(FinancialFact.period))).all()
    except Exception:  # noqa: BLE001
        db.rollback()
        return None
    by_year: dict[int, float] = {}
    for period, value in rows:
        try:
            by_year.setdefault(int(str(period)[:4]), float(value))
        except (TypeError, ValueError):
            continue
    if not by_year:
        return None
    last = max(by_year)
    first = by_year.get(last - years)
    if not first or first <= 0 or by_year[last] <= 0:
        return None
    return (by_year[last] / first) ** (1 / years) - 1


def _known(text: Any) -> str | None:
    t = str(text or "").strip()
    return None if t.lower() in ("", "unknown", "n/a", "none") else t


def by_market_cap(db: Any, companies: list[Company]) -> list[Company]:
    """Las capas anchas se recortan por tamaño, no por orden alfabético: capitalización en USD descendente
    (la misma consulta del servicio de comparables), sin capitalización al final, desempate por ticker."""
    caps: dict[int, Any] = {}
    try:
        from app.services.peer_comparison_service import PeerComparisonService

        caps = PeerComparisonService()._latest_market_caps_usd(db, [c.id for c in companies])  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 - sin capitalizaciones, orden por ticker
        logger.info("preingresos capitalizaciones: %s", type(exc).__name__)
        db.rollback()
    return sorted(companies, key=lambda c: (caps.get(c.id) is None, -float(caps.get(c.id) or 0), str(c.ticker)))


def _derived_cap_usd(db: Any, company: Company) -> float | None:
    """Capitalización en USD cuando no hay una guardada: último cierre × acciones de la última portada (o media
    diluida), convertida con el tipo de cambio guardado. Solo ordena candidatos; nunca entra en un múltiplo."""
    try:
        from app.services.user_sotp_service import _price, convert_amount

        price, ccy, as_of = _price(db, company)
        if not price:
            return None
        fact = None
        for metric in ("shares_outstanding", "shares_diluted"):
            fact = db.scalars(select(FinancialFact).where(
                FinancialFact.company_id == company.id, FinancialFact.metric == metric,
                FinancialFact.value.is_not(None)).order_by(desc(FinancialFact.period), desc(FinancialFact.id))).first()
            if fact is not None and float(fact.value) > 0:
                break
            fact = None
        if fact is None:
            return None
        cap = float(price) * float(fact.value)
        code = str(ccy or company.currency or "USD").upper()
        if code != "USD":
            conv = convert_amount(db, cap, code, "USD", as_of or date.today())
            return float(conv[0]) if conv else None
        return cap
    except Exception as exc:  # noqa: BLE001 - sin capitalización, el candidato va al final
        logger.info("preingresos capitalización derivada %s: %s", getattr(company, "ticker", "?"), type(exc).__name__)
        db.rollback()
        return None


def _caps_usd(db: Any, company: Company, cands: list[Company]) -> dict[int, float]:
    """Capitalización en USD de la empresa y los candidatos (la de mercado o, si falta, la derivada)."""
    caps: dict[int, Any] = {}
    try:
        from app.services.peer_comparison_service import PeerComparisonService

        caps = PeerComparisonService()._latest_market_caps_usd(db, [company.id, *(c.id for c in cands)])  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        logger.info("preingresos capitalizaciones (grupo): %s", type(exc).__name__)
        db.rollback()
    for c in [company, *cands]:
        if not caps.get(c.id):
            derived = _derived_cap_usd(db, c)
            if derived:
                caps[c.id] = derived
    return {k: float(v) for k, v in caps.items() if v}


def _nearest_by_cap(db: Any, company: Company, cands: list[Company], n: int) -> list[Company]:
    """Los ``n`` candidatos de capitalización más cercana a la de ``company`` (|log(cap/cap_empresa)|); sin
    capitalización de la empresa, los mayores; sin la del candidato, al final. Desempate por ticker."""
    import math

    caps = _caps_usd(db, company, cands)
    own = float(caps.get(company.id) or 0)

    def key(c: Company) -> tuple[Any, ...]:
        cap = float(caps.get(c.id) or 0)
        if cap <= 0:
            return (1, 0.0, str(c.ticker))
        return (0, abs(math.log(cap / own)) if own > 0 else -cap, str(c.ticker))

    return sorted(cands, key=key)[:n]


def _affine_members(db: Any, company: Company, members: list[Company], n: int) -> list[Company]:
    """Los ``n`` ``members`` más afines que la ficha guarda (``afin:<CIK>:<coseno>``), de más a menos afín,
    quitando los de tamaño más de ``AFFINE_SIZE_RATIO`` veces distinto (cuando las dos capitalizaciones se
    conocen): parecerse en el texto no hace comparable a una empresa cien veces más pequeña."""
    from app.services.business_affinity import affine_from_tags

    affine = affine_from_tags(company)
    if not affine:
        return []
    by_cik: list[tuple[float, str, Company]] = []
    for c in members:
        try:
            cik = int(str(c.cik or "").strip())
        except ValueError:
            continue
        if cik in affine:
            by_cik.append((-affine[cik], str(c.ticker or ""), c))
    ranked = [c for _s, _t, c in sorted(by_cik, key=lambda r: (r[0], r[1]))]
    caps = _caps_usd(db, company, ranked) if ranked else {}
    own = caps.get(company.id) or 0.0

    def in_band(c: Company) -> bool:
        cap = caps.get(c.id) or 0.0
        return not (own > 0 and cap > 0) or max(own, cap) / min(own, cap) <= AFFINE_SIZE_RATIO

    return [c for c in ranked if in_band(c)][:n]


def mature_peers(db: Any, company: Company, today: date, excluded_out: list[dict[str, Any]] | None = None
                 ) -> tuple[list[rules.PeerMultiple], str | None, str | None, list[dict[str, Any]]]:
    """(comparables maduros, capa usada, motivo si no hay, intentos por capa).

    Capas (regla «comparables-sic-v1» + «afinidad-negocio-v1»): grupo SIC declarado
    (``sic_classification.SIC_INDUSTRY_GROUPS``) o, fuera de un grupo, el mismo SIC — primero solo los de negocio
    afín guardados en la ficha (``afin:``, los ``GROUP_NEAREST`` más afines dentro de la banda de tamaño), después
    todo el grupo (los ``GROUP_NEAREST`` de capitalización más cercana) —; después el servicio de
    comparables, la industria y el sector (la base entera, no: regla «comparables-sin-base-v1»). Los candidatos
    sin cotización de la capa usada van a
    ``excluded_out`` con su motivo («N/D (privada, sin cotización)») y nunca dan múltiplo."""
    from app.services.peer_comparison_service import _same_issuer
    from app.services.sic_classification import company_sic, group_label, industry_group

    memo: dict[int, Any] = {}
    excluded: dict[int, str] = {}
    tried: list[dict[str, Any]] = []

    def run(label: str, cands: list[Company]) -> list[rules.PeerMultiple]:
        got = []
        for c in cands:
            if c.id == company.id or _same_issuer(company, c):
                continue
            pm = _mature_multiple(db, c, today, memo, excluded)
            if pm is not None:
                got.append(pm)
        tried.append({"capa": label, "candidatos": len(cands), "maduros": len(got)})
        return got

    def done(cands: list[Company], used: list[Company]) -> None:
        for c in cands:
            if c.id not in memo and c.id != company.id:
                _mature_multiple(db, c, today, memo, excluded)
        if excluded_out is not None:
            excluded_out.extend({"ticker": c.ticker, "name": c.name, "motivo": excluded[c.id]}
                                for c in cands if c.id in excluded
                                and (c in used or excluded[c.id] == PRIVATE_REASON))

    try:
        from app.services.peer_comparison_service import PeerComparisonService

        svc_peers, _basis, _trace = PeerComparisonService()._find_peers(db, company, 8)
    except Exception as exc:  # noqa: BLE001
        logger.info("preingresos comparables: %s", type(exc).__name__)
        db.rollback()
        svc_peers = []
    with_revenue = (select(FinancialFact.company_id).where(FinancialFact.metric == "revenue",
                                                           FinancialFact.period.like("%:FY")).distinct())
    industry, sector = _known(company.industry), _known(company.sector)
    base_q = select(Company).where(Company.id != company.id, Company.id.in_(with_revenue))
    everyone = list(db.scalars(base_q).all())
    ranked = by_market_cap(db, everyone)
    tiers: list[tuple[str, list[Company]]] = []
    sic = company_sic(company)
    group = industry_group(sic)
    sic_members: list[Company] = []
    sic_label = ""
    if group is not None:
        sic_members = [c for c in everyone if industry_group(company_sic(c)) == group]
        sic_label = f"mismo grupo de industria: {group_label(group)}"
    elif sic is not None:
        sic_members = [c for c in everyone if company_sic(c) == sic]
        sic_label = f"mismo código SIC ({sic})"
    if sic_label:
        # Regla «afinidad-negocio-v1»: primero los del grupo cuyo negocio se parece de verdad (descripción del
        # informe anual en la SEC); el SIC solo, que junta satélites con equipos de red, queda como respaldo.
        affine = _affine_members(db, company, sic_members, GROUP_NEAREST)
        if affine:
            tiers.append((f"{sic_label}, de negocio afín: las {len(affine)} con la descripción del informe anual más "
                          f"parecida y tamaño a menos de {AFFINE_SIZE_RATIO:g} veces (regla {AFFINITY_RULE})",
                          affine))
        tiers.append((f"{sic_label}, las {GROUP_NEAREST} de capitalización más cercana",
                      _nearest_by_cap(db, company, sic_members, GROUP_NEAREST)))
    # Comparables declarados (servicio): los que no cotizan salen excluidos con su motivo, nunca con múltiplo.
    tiers.append(("comparables del servicio de comparables", list(svc_peers)))
    if industry:
        tiers.append((f"misma industria ({industry})",
                      [c for c in ranked if c.industry == company.industry][:MAX_CANDIDATES]))
    if sector:
        tiers.append((f"mismo sector ({sector})", [c for c in ranked if c.sector == company.sector][:MAX_CANDIDATES]))
    # Regla «comparables-sin-base-v1» (9-nov-2026): la base entera (las mayores por capitalización, sin relación de
    # negocio) no es un comparable: un biotec de anticuerpos salía con el EV/ventas de UNH, SNAP o POOL. Sin
    # comparables maduros del SIC, del servicio, de la industria ni del sector, el múltiplo de salida es N/D.
    declared = list(svc_peers)
    for label, cands in tiers:
        got = run(label, cands)
        if len(got) >= rules.MIN_PEERS:
            done([*cands, *[c for c in declared if c not in cands]], cands)
            return got, label, None, tried
    done(declared, [])
    return [], None, (f"N/D: menos de {rules.MIN_PEERS} comparables maduros con ingresos y EV positivos en su SIC, "
                      "sus comparables, su industria o su sector (la base entera no se usa: no es comparable)"), tried


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
    anchors = revenue_anchors(db, company, last_fy=last_fy, ccy=ccy, today=today,
                              last_revenue=float(sp.revenue) if sp.revenue and ccy == "USD" else None)
    anchor, anchor_missing = rules.choose_anchor(anchors, last_fy)
    excluded: list[dict[str, Any]] = []
    peers, layer, peers_missing, tried = mature_peers(db, company, today, excluded)
    stats = rules.peer_stats(peers)
    scen = rules.scenarios(today=today, price=sp.price, shares=sp.shares_diluted, cash=sp.cash,
                           debt=sp.debt + sp.leases, minorities=sp.minorities, hybrids=sp.hybrids, fcf=fcf,
                           dilution_hist=runway.get("dilution_cagr"), anchor=anchor, anchor_missing=anchor_missing,
                           peers=stats, peers_missing=peers_missing, last_fy=last_fy, fy_end_month=fy_month,
                           last_revenue=float(sp.revenue) if sp.revenue else None)
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
        "peers": [{"ticker": p.ticker, "name": p.name, "ev": p.ev, "revenue": p.revenue, "multiple": p.multiple,
                   "revenue_cagr_3y": p.growth}
                  for p in sorted(peers, key=lambda p: p.multiple)],
        "peer_layer": layer, "peer_stats": stats, "peers_missing": peers_missing, "peer_layers_tried": tried,
        "peers_excluded": excluded,
        "scenarios": scen, "formulas": rules.FORMULAS,
    }
    payload["fingerprint"] = hashlib.sha256(json.dumps(
        {k: payload[k] for k in ("rules", "runway", "revenue_anchor", "peers", "scenarios")},
        sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    return payload


__all__ = ["by_market_cap", "mature_peers", "official_contract_anchor", "own_estimate_anchor", "revenue_cagr", "revenue_anchors", "value_pre_revenue"]
