"""Tesis v2 de nivel comité de inversión: secciones de las tesis de referencia y más (8-nov-2026).

Nico (8-nov-2026, 14:13–14:16): «Que hagamos tesis así», «que lleguemos a un nivel de tesis mucho mejor
que estas dos» y «añade las secciones que hagan falta para explicar mejor la acción». La referencia son las
tesis de Numantia sobre Eurofins y Brookfield. Aquí:

* TODAS las cifras salen del código: la valoración por TIR (:mod:`app.services.shareholder_irr_service`),
  los hechos anuales citados y los comparables calculados. Al modelo le llegan como MARCADORES
  (``{{esc.base.tir10}}``) con su valor, y las tablas las pinta el código.
* El modelo escribe la prosa larga en español, con tono institucional, y solo ELIGE entre opciones dadas: el
  juego de probabilidades de ``PROBABILITY_SETS``, con su razón. El validador de #4745 rechaza los números
  libres: un reintento y, si vuelve a fallar, se quitan.
* Mismos datos → misma huella → mismo texto (caché en ``declared_input_values``, clave ``thesis_v2``, sin
  migración). Las cifras se sustituyen al mostrar con las del cálculo guardado junto al texto.

Secciones: las 9 de las tesis de referencia, más «Historial», «Comparables», «Por qué este método», «Qué
descuenta el precio», «Qué vigilar» (kill switches como umbrales de métricas) y, si aplica, «Balance y deuda».
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company
from app.services.expert_team.experts import Reasoner
from app.services.expert_team.sotp_narrative import MARKER, free_numbers, strip_free_numbers, unknown_markers

logger = logging.getLogger(__name__)

THESIS_V2_VERSION = "thesis-v2-1"
INPUT_KEY = "thesis_v2"
MAX_ATTEMPTS = 2
PASSAGES_PER_GROUP = 6
MAX_CHUNKS_PER_DOC = 1500

#: (clave, título, parte de la llamada, tablas que pinta el código debajo del texto)
SECTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("introduccion", "1. Introducción: qué estamos comprando realmente", "a", ("partida",)),
    ("sector_estrategia", "2. Sector y estrategia", "a", ()),
    ("ventaja_competitiva", "3. Ventaja competitiva: por qué podría perdurar", "a", ()),
    ("directivos_capital", "4. Directivos, cultura y asignación de capital", "a", ("capital",)),
    ("contabilidad", "5. Cómo leer la contabilidad", "a", ("ajustes",)),
    ("historial", "6. Historial: diez años en cifras", "a", ("historial",)),
    ("comparables", "7. Comparables calculados", "a", ("comparables",)),
    ("deuda_balance", "8. Balance y deuda", "a", ()),
    ("consenso_guia", "8 bis. Guía de la empresa y consenso", "a", ("guia",)),
    ("metodo", "9. Por qué este método", "b", ("metodos",)),
    ("valoracion", "10. Valoración: qué rentabilidad esperamos y de dónde sale", "b",
     ("escenarios", "descomposicion", "sensibilidad")),
    ("que_descuenta", "11. Qué descuenta el precio", "b", ()),
    ("riesgos", "12. Riesgos y kill switches", "b", ()),
    ("que_vigilar", "13. Qué vigilar", "b", ("vigilar",)),
    ("pre_mortem", "14. Pre-mortem: la inversión mirada desde dentro de cinco años", "b", ()),
    ("conclusion", "15. Conclusión: ¿empresa excelente? ¿oportunidad al precio?", "b", ()),
)
OPTIONAL = {"deuda_balance", "consenso_guia"}

PROMPT = (
    "Eres el equipo de analistas de GerarAI escribiendo una TESIS DE INVERSIÓN para un comité de inversión, "
    "al nivel de las mejores gestoras value europeas. Escribe en español, con tono institucional y prosa "
    "natural, larga y bien explicada: párrafos completos que razonan (qué es el negocio y cómo gana dinero, "
    "por qué esa cifra importa, qué tendría que pasar para que cambie), nunca listas de viñetas sueltas. "
    "Cada sección tiene la extensión que necesite (varios párrafos). Sé honesto: di lo que falta, lo que no "
    "está probado y lo que juega en contra. Te damos: las cifras ya calculadas por el código como MARCADORES "
    "con su valor, las tablas que el código pinta debajo de cada sección (no las repitas enteras: coméntalas), "
    "los avisos de datos y pasajes de los informes de la empresa con su documento. Lo cualitativo (negocio, "
    "sector, ventaja, directivos) apóyalo en esos pasajes; si no hay pasaje, dilo como lectura general del "
    "sector, sin inventar hechos concretos de la empresa; cuando uses un pasaje, nombra el documento («según el "
    "informe anual»). Los marcadores de múltiplo ya llevan la «x»: no añadas «veces» detrás."
)
CONTRACT = (
    "Responde SOLO con JSON: {{\"sections\": {{{keys}}}{extra}}}. REGLA ABSOLUTA: toda cifra (precios, %, "
    "millones, acciones, múltiplos, veces, probabilidades, años de recuperación…) se escribe SOLO con un "
    "marcador de la lista, tal cual ({{{{nombre}}}}); nunca escribas un número tú, ni en letra. Puedes "
    "escribir años (2031) y citar formularios (10-K, 40-F). No calcules nada nuevo."
)
PROB_FIELD = (", \"probabilidades\": una de {choices}, \"probabilidades_razon\": str (por qué ese juego "
              "de probabilidades, en una frase y sin números)")


def _es(value: float, decimals: int = 1) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def money(value: float | None, ccy: str, decimals: int = 2) -> str:
    if value is None:
        return "N/D"
    sign = "−" if value < 0 else ""
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(ccy, ccy)
    return f"{sign}{_es(abs(value), decimals)} {sym}"


def millions(value: float | None, ccy: str) -> str:
    if value is None:
        return "N/D"
    sym = {"USD": "M$", "EUR": "M€", "GBP": "M£"}.get(ccy, f"M {ccy}")
    sign = "−" if value < 0 else ""
    return f"{sign}{_es(abs(value), 0)} {sym}"


def pct(value: float | None, decimals: int = 1, signed: bool = False) -> str:
    if value is None:
        return "N/D"
    text = _es(value * 100, decimals)
    if signed and value > 0:
        text = "+" + text
    return text.replace("-", "−") + " %"


def pp(value: float | None) -> str:
    if value is None:
        return "N/D"
    return (_es(value * 100, 1) + " pp").replace("-", "−")


def times(value: float | None) -> str:
    return "N/D" if value is None else _es(value, 1) + "x"


def shares(value: float | None) -> str:
    return "N/D" if value is None else _es(value, 1) + " M"


# ----------------------------------------------------------------------------------------------- contexto

def _point_by_year(db: Session, company: Company, metrics: Sequence[str]) -> dict[str, dict[int, float]]:
    """Datos de balance al cierre de cada ejercicio (millones), mejor fuente por cierre."""
    from app.models import FinancialFact
    from app.services.ttm_service import _is_segment

    out: dict[str, dict[int, float]] = {}
    rows = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                   FinancialFact.metric.in_(tuple(metrics)))
                      .order_by(desc(FinancialFact.id))).all()
    for f in rows:
        if f.value is None or _is_segment(f):
            continue
        end = str(f.period or "").split(":")[0]
        try:
            year = int(end[:4])
        except ValueError:
            continue
        out.setdefault(f.metric, {}).setdefault(year, float(f.value) / 1e6)
    return out


def implied_growth(sp: Any, drivers: Any, rate: float, years: int = 10) -> float | None:
    """Crecimiento orgánico constante que hace que la TIR a ``years`` del escenario base sea ``rate``."""
    from dataclasses import replace

    from app.valuation import shareholder_irr as engine

    def f(g: float) -> float:
        d = replace(drivers, organic_growth=g, organic_growth_late=g)
        r = engine.evaluate(sp, d, (years,))[years].irr
        return (r if r is not None else -1.0) - rate

    lo, hi = -0.3, 0.6
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def kill_switches(val: Mapping[str, Any], hist_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Umbrales falsables sobre métricas que GerarAI vuelve a leer con cada informe. Derivados del propio
    escenario bajista: si la realidad cae por debajo de lo que ya suponía el bajista, la tesis está rota."""
    sp = val["starting_point"]
    ccy = sp["currency"]
    scen = val.get("scenarios") or {}
    bear = (scen.get("bear") or {}).get("drivers") or {}
    base = (scen.get("base") or {}).get("drivers") or {}
    last = hist_rows[-1] if hist_rows else {}
    prev = hist_rows[-2] if len(hist_rows) > 1 else {}
    out: list[dict[str, Any]] = []

    def add(key, metric, threshold_text, current, broken, action, why):
        out.append({"key": key, "metric": metric, "threshold": threshold_text, "current": current,
                    "status": "saltado" if broken else "ok", "action": action, "why": why})

    g_now = last.get("growth")
    g_prev = prev.get("growth")
    thr = bear.get("organic_growth")
    if thr is None:  # sin escenarios (valoración no proyectable): solo los umbrales que no dependen de ellos
        lev = (sp["net_debt"] / sp["ebitda"]) if sp.get("ebitda") else None
        sh_now, sh_prev = last.get("shares"), prev.get("shares")
        growth_sh = (sh_now / sh_prev - 1) if sh_now and sh_prev else None
        add("dilucion", "Variación anual de acciones diluidas", "> +2 % en un ejercicio", pct(growth_sh, signed=True),
            growth_sh is not None and growth_sh > 0.02, "revisar", "la emisión de acciones diluye al accionista")
        g_now = last.get("growth")
        add("crecimiento", "Crecimiento anual de ingresos", "< 0 % dos ejercicios seguidos", pct(g_now),
            g_now is not None and (prev.get("growth") or 0) < 0 and g_now < 0, "revisar", "el negocio encoge")
        if lev is not None:
            add("apalancamiento", "Deuda neta / EBITDA", f"> {times(max(2.5, lev + 1.0))}", times(lev),
                lev > max(2.5, lev + 1.0), "reducir", "el balance pasa a ser un riesgo")
        return out
    add("crecimiento", "Crecimiento anual de ingresos", f"< {pct(thr)} dos ejercicios seguidos",
        pct(g_now), g_now is not None and g_prev is not None and g_now < thr and g_prev < thr,
        "revisar y, si se confirma, vender", "falla la palanca de crecimiento del escenario base")
    m_now = last.get("margin")
    add("margen", "Margen (EBITDA o neto, según el método)", f"< {pct(bear['margin_target'])}",
        pct(m_now), m_now is not None and m_now < bear["margin_target"], "revisar el foso",
        "pérdida de poder de precio o de eficiencia por debajo del peor de los tres últimos ejercicios")
    c_now = last.get("conversion")
    add("conversion", "Conversión de caja (flujo libre / EBITDA)", f"< {pct(bear['cash_conversion'])}",
        pct(c_now), c_now is not None and c_now < bear["cash_conversion"], "revisar capex y circulante",
        "menos caja para dividendo, recompras y deuda")
    lev = (sp["net_debt"] / sp["ebitda"]) if sp.get("ebitda") else None
    lim = max(2.5, (lev or 0) + 1.0)
    add("apalancamiento", "Deuda neta / EBITDA", f"> {times(lim)}", times(lev), lev is not None and lev > lim,
        "reducir", "el balance deja de ser una palanca y pasa a ser un riesgo")
    sh_now, sh_prev = last.get("shares"), prev.get("shares")
    growth_sh = (sh_now / sh_prev - 1) if sh_now and sh_prev else None
    add("dilucion", "Variación anual de acciones diluidas", "> +2 % en un ejercicio", pct(growth_sh, signed=True),
        growth_sh is not None and growth_sh > 0.02, "revisar", "la remuneración en acciones se come la recompra")
    values = val.get("value_per_share") or {}
    price = sp["price"]
    if values.get("base"):
        add("precio_alto", "Precio frente al valor base a la tasa exigida",
            f"≥ {money(values['base'], ccy)}", money(price, ccy), price >= values["base"],
            "recortar o vender", "a ese precio la TIR esperada del escenario base ya no supera el coste del capital")
    if values.get("bear"):
        add("precio_bajo", "Precio frente al valor del escenario bajista",
            f"≤ {money(values['bear'], ccy)}", money(price, ccy), price <= values["bear"], "ampliar",
            "a ese precio incluso el escenario bajista rinde el coste del capital")
    if base.get("exit_multiple"):
        add("multiplo", "Múltiplo de la propia empresa", f"> {times(val['scenarios']['bull']['drivers']['exit_multiple'])}",
            times(sp.get("multiple")), (sp.get("multiple") or 0) > val["scenarios"]["bull"]["drivers"]["exit_multiple"],
            "recortar", "el mercado ya paga el múltiplo del escenario alcista")
    return out


def history_rows(cites: Mapping[str, Any], basis: str, points: Mapping[str, Mapping[int, float]]) -> list[dict]:
    annual = cites.get("annual") or {}

    def v(metric: str, year: int) -> float | None:
        c = (annual.get(metric) or {}).get(str(year))
        return None if not c or c.get("value") is None else float(c["value"]) / 1e6

    years = sorted(int(y) for y in (annual.get("revenue") or {}))
    rows: list[dict] = []
    prev_rev = None
    for y in years:
        rev = v("revenue", y)
        oi, da = v("operating_income", y), v("depreciation_amortization", y)
        ebitda = (oi + abs(da)) if oi is not None and da is not None else v("ebitda", y)
        ni = v("net_income_attributable", y)
        ni = ni if ni is not None else v("net_income", y)
        ocf, capex = v("operating_cash_flow", y), v("capital_expenditure", y)
        fcf = (ocf - abs(capex or 0.0)) if ocf is not None else None
        sh_raw = v("shares_diluted", y)
        earnings = ni if basis == "pe" else ebitda
        eq = (points.get("total_equity") or {}).get(y)
        debt = (points.get("total_debt") or {}).get(y)
        cash = (points.get("cash_and_equivalents") or {}).get(y)
        tax = 0.25
        invested = (eq + (debt or 0.0) - (cash or 0.0)) if eq is not None else None
        roic = (oi * (1 - tax) / invested) if (oi is not None and invested and invested > 0) else None
        rows.append({
            "year": y, "revenue": rev, "growth": (rev / prev_rev - 1) if rev and prev_rev else None,
            "ebitda": ebitda, "net_income": ni,
            "margin": (earnings / rev) if earnings is not None and rev else None,
            "fcf": fcf, "conversion": (fcf / ebitda) if fcf is not None and ebitda else None,
            "shares": sh_raw, "fcf_per_share": (fcf / sh_raw) if fcf is not None and sh_raw else None,
            "dividends": abs(v("dividends_paid", y) or 0.0) or None,
            "buybacks": abs(v("common_stock_repurchased", y) or 0.0) or None,
            "acquisitions": abs(v("acquisitions", y) or 0.0) or None, "roic": roic,
        })
        prev_rev = rev
    return rows


def evidence_passages(db: Session, company: Company, tenant_id: int | None) -> list[dict[str, Any]]:
    """Pasajes de los documentos ingeridos (informe anual, 10-K/10-Q, notas de resultados), con su documento."""
    from app.models.entities import Document, DocumentChunk

    groups = {
        "negocio": ("segment", "segmento", "customers", "clientes", "business", "negocio", "strategy", "estrategia"),
        "ventaja": ("competit", "market share", "cuota", "network", "red ", "scale", "escala", "brand", "marca"),
        "directivos": ("chief executive", "consejero delegado", "founder", "fundador", "repurchase", "recompra",
                       "dividend", "acquisition", "adquisici", "capital allocation"),
        "riesgos": ("risk", "riesgo", "litigation", "regulat", "uncertain"),
        "guia": ("outlook", "guidance", "expects", "perspectivas", "objetivo", "target"),
    }
    query = select(Document).where(Document.company_id == company.id, Document.retention_tombstoned_at.is_(None))
    if tenant_id is not None:
        query = query.where(Document.tenant_id == tenant_id)
    docs = db.scalars(query.order_by(Document.published_at.desc().nullslast(), Document.id.desc()).limit(8)).all()
    chunks: list[tuple[Any, str]] = []
    for doc in docs:
        if (doc.title or "").startswith("SEC XBRL facts"):
            continue  # las cifras ya llegan como marcadores
        for ch in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
                             .order_by(DocumentChunk.chunk_index).limit(MAX_CHUNKS_PER_DOC)).all():
            text = " ".join((ch.text or "").split())
            if len(text) >= 200 and text.count(".") >= 3:  # prosa, no índices ni tablas
                chunks.append((doc, text))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group, words in groups.items():
        scored = []
        for i, (doc, text) in enumerate(chunks):
            low = text.casefold()
            score = sum(low.count(w) for w in words)
            if score:
                scored.append((-score, i, doc, text))
        for _s, _i, doc, text in sorted(scored)[:PASSAGES_PER_GROUP]:
            key = text[:200]
            if key in seen:
                continue
            seen.add(key)
            out.append({"group": group, "document": doc.title, "url": doc.source_url,
                        "date": doc.published_at.date().isoformat() if doc.published_at else None,
                        "text": text[:1200]})
    return out


def peer_rows(db: Session, company: Company, val: Mapping[str, Any], today: date) -> list[dict[str, Any]]:
    from app.services.shareholder_irr_service import starting_point

    rows = []
    for p in val.get("peers") or []:
        peer = db.scalars(select(Company).where(Company.ticker == p["ticker"])).first()
        row = {"ticker": p["ticker"], "name": p.get("name"), "multiple": p.get("multiple"), "margin": None,
               "growth": None, "leverage": None, "note": None}
        if peer is not None:
            try:
                sp, hist, _w, _c = starting_point(db, peer, today=today, basis=val["starting_point"]["basis"])
                row["margin"] = sp.margin
                revs = [r for r in hist.revenue if r]
                if len(revs) >= 4:
                    row["growth"] = (revs[-1] / revs[-4]) ** (1 / 3) - 1
                row["leverage"] = (sp.net_debt / sp.ebitda) if sp.ebitda else None
            except ValueError as exc:
                row["note"] = f"sin datos suficientes: {exc}"
        rows.append(row)
    return rows


@dataclass
class ThesisContext:
    ticker: str
    company: str
    valuation: dict[str, Any]
    history: list[dict[str, Any]]
    peers: list[dict[str, Any]]
    switches: list[dict[str, Any]]
    implied_growth: float | None
    passages: list[dict[str, Any]]
    optional: dict[str, str] = field(default_factory=dict)  # sección opcional → por qué entra
    guidance: list[dict[str, Any]] = field(default_factory=list)


def build_context(db: Session, company: Company, *, today: date, tenant_id: int | None = None) -> ThesisContext:
    from app.services.shareholder_irr_service import value_company

    val = value_company(db, company, today=today)
    val.setdefault("as_of", today.isoformat())
    name = display_name(company.name or company.ticker)
    if val.get("status") not in ("ok", "not_meaningful"):
        return ThesisContext(company.ticker, name, val, [], [], [], None, [])
    points = _point_by_year(db, company, ("total_equity", "total_debt", "cash_and_equivalents"))
    hist = history_rows(val["citations"], val["starting_point"]["basis"], points)
    peers = peer_rows(db, company, val, today)
    switches = kill_switches(val, hist)
    ig = None
    if val.get("discount_rate") and val.get("scenarios"):
        from app.valuation import shareholder_irr as engine

        sp = engine.StartingPoint(**{k: val["starting_point"][k] for k in engine.StartingPoint.__dataclass_fields__})
        d = engine.Drivers(**val["scenarios"]["base"]["drivers"])
        ig = implied_growth(sp, d, float(val["discount_rate"]))
    sp = val["starting_point"]
    optional = {}
    if sp.get("ebitda") and sp.get("net_debt", 0) > 0 and sp["net_debt"] / sp["ebitda"] > 1.0:
        optional["deuda_balance"] = "deuda neta superior a una vez el EBITDA"
    passages = evidence_passages(db, company, tenant_id)
    guidance = company_guidance_rows(db, company)
    if guidance:
        optional["consenso_guia"] = "la empresa da previsiones citadas en sus notas de resultados"
    return ThesisContext(company.ticker, name, val, hist, peers, switches, ig, passages, optional, guidance)


def display_name(name: str) -> str:
    """Nombre legible: sin el sufijo de estado de EDGAR («BROOKFIELD Corp /ON/» → «BROOKFIELD Corp»)."""
    return re.sub(r"\s*/[A-Z]{2,3}/\s*$", "", name or "").strip() or name


def company_guidance_rows(db: Session, company: Company) -> list[dict[str, Any]]:
    """La guía que la empresa da en sus notas de resultados (``company_guidance``), con su frase y su URL."""
    from app.models.declared_input_value import DeclaredInputValue

    rows = db.scalars(select(DeclaredInputValue).where(
        DeclaredInputValue.company_id == company.id, DeclaredInputValue.input_key.like("guidance.%"),
        DeclaredInputValue.superseded_at.is_(None)).order_by(DeclaredInputValue.input_key)).all()
    out = []
    for r in rows:
        meta = r.metadata_ or {}
        out.append({"key": r.input_key, "metric": meta.get("metric") or r.input_key.split(".")[1],
                    "period": meta.get("period") or r.input_key.split(".")[-1], "unit": r.unit,
                    "low": float(r.low) if r.low is not None else None, "base": float(r.base),
                    "high": float(r.high) if r.high is not None else None, "url": r.source_url,
                    "quote": (r.source_quote or "")[:400], "as_of": r.as_of.isoformat() if r.as_of else None,
                    "document": meta.get("document_title")})
    return out


def _guidance_value(g: Mapping[str, Any], value: float | None) -> str:
    if value is None:
        return "N/D"
    unit = str(g.get("unit") or "")
    if unit.endswith("/share"):
        return money(value, unit.split("/")[0])
    return millions(value / 1e6, unit or "USD")


# --------------------------------------------------------------------------------------------- marcadores

def thesis_markers(ctx: ThesisContext) -> dict[str, str]:
    val = ctx.valuation
    sp = val["starting_point"]
    ccy = sp["currency"]
    m: dict[str, str] = {
        "empresa": ctx.company, "ticker": ctx.ticker, "fecha": str(val.get("as_of") or ""),
        "punto.precio": money(sp["price"], ccy), "punto.acciones": shares(sp["shares_diluted"]),
        "punto.capitalizacion": millions(sp["market_cap"], ccy), "punto.deuda_neta": millions(sp["net_debt"], ccy),
        "punto.caja": millions(sp["cash"], ccy), "punto.deuda": millions(sp["debt"], ccy),
        "punto.arrendamientos": millions(sp["leases"], ccy), "punto.hibridos": millions(sp["hybrids"], ccy),
        "punto.minoritarios": millions(sp["minorities"], ccy), "punto.ev": millions(sp["enterprise_value"], ccy),
        "punto.multiplo": times(sp["multiple"]), "punto.ingresos": millions(sp["revenue"], ccy),
        "punto.ebitda": millions(sp["ebitda"], ccy), "punto.beneficio": millions(sp["net_income"], ccy),
        "punto.margen": pct(sp["margin"]),
        "tasa.coste_capital": pct(val.get("discount_rate")),
    }
    if val.get("status") == "not_meaningful":
        m["valoracion.motivo"] = str(val.get("reason") or "")
        _history_markers(m, ctx, ccy)
        return m
    m |= {
        "pond.tir5": pct(val["weighted"].get("5")), "pond.tir10": pct(val["weighted"].get("10")),
        "pond.valor": money(val.get("weighted_value_per_share"), ccy),
        "base.tir10_multiplo_congelado": pct(val.get("base_frozen_multiple_irr_10")),
        "descuenta.crecimiento": pct(ctx.implied_growth),
    }
    tr = val["trace"]
    mult = tr["multiplo"]
    m["comparables.mediana"] = times(mult.get("mediana_comparables"))
    m["comparables.n"] = str(mult.get("n_comparables"))
    if mult.get("mediana_comparables") and sp.get("multiple"):
        m["comparables.descuento"] = pct(sp["multiple"] / mult["mediana_comparables"] - 1, signed=True)
    cr = tr["crecimiento"]
    m["historico.crecimiento"] = pct(cr.get("historico_total"))
    m["historico.crecimiento_organico"] = pct(cr.get("historico_organico"))
    m["historico.crecimiento_comprado"] = pct(cr.get("comprado"))
    br = cr.get("tasa_base") or {}
    m["tasa_base.tramo"] = str(cr.get("tramo_tasa_base") or "N/D")
    for q in ("p25", "p50", "p75"):
        m[f"tasa_base.{q}"] = pct(br.get(q))
    m["tasa_base.n"] = str(br.get("n", "N/D"))
    rep = tr["reparto"]
    m["reparto.dividendo"] = pct(rep["dividendo"], 0)
    m["reparto.recompras"] = pct(rep["recompras"], 0)
    m["reparto.deuda"] = pct(rep["deuda"], 0)
    m["mna.gasto"] = pct(tr["mna"]["gasto_pct_ingresos"])
    for k, label in (("bear", "bajista"), ("base", "base"), ("bull", "alcista")):
        s = val["scenarios"][k]
        d = s["drivers"]
        p = f"esc.{k}"
        m[f"{p}.nombre"] = label
        m[f"{p}.probabilidad"] = pct(val["probabilities"]["values"][k], 0)
        m[f"{p}.crecimiento"] = pct(d["organic_growth"])
        m[f"{p}.crecimiento_tardio"] = pct(d["organic_growth_late"])
        m[f"{p}.margen"] = pct(d["margin_target"])
        m[f"{p}.conversion"] = pct(d["cash_conversion"], 0)
        m[f"{p}.mna"] = pct(d["mna_spend_pct_revenue"])
        m[f"{p}.multiplo"] = times(d["exit_multiple"])
        for n in ("5", "10"):
            h = s["horizons"][n]
            m[f"{p}.tir{n}"] = pct(h["irr"])
            m[f"{p}.precio{n}"] = money(h["exit_price"], ccy)
            for comp, v in h["components"].items():
                m[f"{p}.d{n}.{comp}"] = pp(v)
        m[f"{p}.valor"] = money((val.get("value_per_share") or {}).get(k), ccy)
    _history_markers(m, ctx, ccy)
    for i, p in enumerate(ctx.peers, start=1):
        m[f"peer.{i}.nombre"] = f"{p.get('name') or p['ticker']} ({p['ticker']})"
        m[f"peer.{i}.multiplo"] = times(p.get("multiple"))
        m[f"peer.{i}.margen"] = pct(p.get("margin"))
    for i, s in enumerate(ctx.switches, start=1):
        # En la prosa el operador sobra («por debajo del −1,7 %»); la tabla lo conserva.
        m[f"vigilar.{i}.umbral"] = re.sub(r"^[<>≤≥]=?\s*", "", s["threshold"])
        m[f"vigilar.{i}.actual"] = s["current"]
    for i, g in enumerate(ctx.guidance, start=1):
        m[f"guia.{i}.metrica"] = f"{g['metric']} {g['period']}"
        m[f"guia.{i}.base"] = _guidance_value(g, g["base"])
        m[f"guia.{i}.bajo"] = _guidance_value(g, g["low"])
        m[f"guia.{i}.alto"] = _guidance_value(g, g["high"])
    return m


def _history_markers(m: dict[str, str], ctx: ThesisContext, ccy: str) -> None:
    for i, row in enumerate(ctx.history[-10:]):
        y = row["year"]
        m[f"hist.{y}.ingresos"] = millions(row["revenue"], ccy)
        m[f"hist.{y}.crecimiento"] = pct(row["growth"], signed=True)
        m[f"hist.{y}.margen"] = pct(row["margin"])
        m[f"hist.{y}.fcf"] = millions(row["fcf"], ccy)
        m[f"hist.{y}.conversion"] = pct(row["conversion"], 0)
        m[f"hist.{y}.roic"] = pct(row["roic"])
        _ = i
    if ctx.history:
        first, last = ctx.history[0], ctx.history[-1]
        m["hist.primer_ano"], m["hist.ultimo_ano"] = str(first["year"]), str(last["year"])
        if first.get("revenue") and last.get("revenue") and last["year"] > first["year"]:
            m["hist.tcac_ingresos"] = pct((last["revenue"] / first["revenue"]) ** (1 / (last["year"] - first["year"])) - 1)
        if first.get("shares") and last.get("shares") and last["year"] > first["year"]:
            m["hist.tcac_acciones"] = pct((last["shares"] / first["shares"]) ** (1 / (last["year"] - first["year"])) - 1, signed=True)
        fps = [r for r in ctx.history if r.get("fcf_per_share")]
        if len(fps) >= 2 and fps[0]["fcf_per_share"] > 0 and fps[-1]["fcf_per_share"] > 0:
            m["hist.tcac_fcf_accion"] = pct((fps[-1]["fcf_per_share"] / fps[0]["fcf_per_share"]) ** (1 / (fps[-1]["year"] - fps[0]["year"])) - 1)
        tot = {k: sum(r.get(k) or 0.0 for r in ctx.history[-5:]) for k in ("dividends", "buybacks", "acquisitions", "fcf")}
        for k, name in (("dividends", "dividendos"), ("buybacks", "recompras"), ("acquisitions", "adquisiciones"), ("fcf", "fcf")):
            m[f"capital.5a.{name}"] = millions(tot[k], ccy)


def marker_catalog(ctx: ThesisContext) -> list[dict[str, str]]:
    return [{"marker": "{{" + k + "}}", "value": v} for k, v in thesis_markers(ctx).items()]


def tables(ctx: ThesisContext) -> dict[str, dict[str, Any]]:
    """Las tablas que pinta el código (cabecera + filas de texto ya formateado)."""
    val = ctx.valuation
    sp = val["starting_point"]
    ccy = sp["currency"]
    cites = val.get("citations") or {}
    pc = cites.get("price") or {}
    t: dict[str, dict[str, Any]] = {}
    t["partida"] = {"title": "Punto de partida normalizado", "head": ["Concepto", "Valor", "Fuente / fórmula"], "rows": [
        ["Precio", money(sp["price"], ccy), f"{pc.get('document', '')} {pc.get('as_of') or ''} {pc.get('fx') or ''}".strip()],
        ["Acciones diluidas", shares(sp["shares_diluted"]), _cite_text(cites.get("shares"))],
        ["Capitalización", millions(sp["market_cap"], ccy), "precio × acciones diluidas"],
        ["Caja e inversiones a corto", millions(sp["cash"], ccy), _cite_text(cites.get("cash_and_equivalents"))],
        ["Deuda financiera", millions(sp["debt"], ccy), _cite_text(cites.get("total_debt"))],
        ["Arrendamientos en deuda", millions(sp["leases"], ccy),
         "IFRS 16: el EBITDA ya excluye los alquileres" if cites.get("ifrs16_leases_in_debt") else "US GAAP: alquiler operativo en gastos"],
        ["Híbridos", millions(sp["hybrids"], ccy), "como deuda económica"],
        ["Minoritarios", millions(sp["minorities"], ccy), "por delante del accionista"],
        ["Valor de empresa (EV)", millions(sp["enterprise_value"], ccy), "capitalización + deuda neta + híbridos + minoritarios"],
        ["EBITDA de partida" if sp["basis"] != "pe" else "Beneficio de partida",
         millions(sp["ebitda"] if sp["basis"] != "pe" else sp["net_income"], ccy),
         "resultado operativo + amortizaciones del último ejercicio" if sp["basis"] != "pe" else "beneficio neto atribuible"],
        ["Múltiplo de partida", times(sp["multiple"]), "EV / EBITDA" if sp["basis"] != "pe" else "PER"],
        ["Mediana de comparables", times(((val.get("trace") or {}).get("multiplo") or {}).get("mediana_comparables")),
         f"{((val.get('trace') or {}).get('multiplo') or {}).get('n_comparables', 0)} comparables calculados con la misma fórmula"],
    ]}
    t["historial"] = {"title": "Historial (millones, ejercicio fiscal)", "head": [
        "Año", "Ingresos", "Crec.", "Margen", "FCF", "Conv.", "FCF/acción", "Acciones", "ROIC"], "rows": [
        [str(r["year"]), millions(r["revenue"], ccy), pct(r["growth"], signed=True), pct(r["margin"]),
         millions(r["fcf"], ccy), pct(r["conversion"], 0), money(r["fcf_per_share"], ccy), shares(r["shares"]),
         pct(r["roic"])] for r in ctx.history[-10:]]}
    t["capital"] = {"title": "Asignación de capital (millones)", "head": ["Año", "FCF", "Dividendos", "Recompras", "Adquisiciones"],
                    "rows": [[str(r["year"]), millions(r["fcf"], ccy), millions(r["dividends"], ccy),
                              millions(r["buybacks"], ccy), millions(r["acquisitions"], ccy)] for r in ctx.history[-6:]]}
    t["ajustes"] = {"title": "Ajustes y huecos de datos que señala el código", "head": ["Ajuste o hueco", "Efecto"], "rows": [
        [w.split(":", 1)[0].strip(), (w.split(":", 1)[1].strip() if ":" in w else "")] for w in val.get("warnings") or []]}
    t["comparables"] = {"title": "Comparables (calculados con la misma fórmula)", "head": [
        "Empresa", "Múltiplo", "Margen", "Crec. 3 años", "Deuda neta / EBITDA", "Nota"], "rows": [
        [f"{p.get('name') or p['ticker']} ({p['ticker']})", times(p.get("multiple")), pct(p.get("margin")),
         pct(p.get("growth")), times(p.get("leverage")), p.get("note") or ""] for p in ctx.peers]}
    t["guia"] = {"title": "Guía de la propia empresa (notas de resultados)", "head": [
        "Métrica", "Periodo", "Bajo", "Punto medio", "Alto", "Fuente"], "rows": [
        [g["metric"], g["period"], _guidance_value(g, g["low"]), _guidance_value(g, g["base"]), _guidance_value(g, g["high"]),
         f"{g.get('document') or ''} ({g.get('as_of') or ''}) {g.get('url') or ''}".strip()] for g in ctx.guidance]}
    meth = val.get("method") or {}
    labels = {"tir_ev_ebitda": "TIR para el accionista sobre EV/EBITDA", "tir_per": "TIR para el accionista sobre PER",
              "dcf": "DCF con WACC", "sotp": "Suma de partes"}
    chosen = str(meth.get("chosen") or "")
    rows = [[labels.get(chosen, chosen), "elegido", "cumple las condiciones de datos"]]
    rows += [[labels.get(k, k), "descartado", why] for k, why in (meth.get("discarded") or {}).items()]
    t["metodos"] = {"title": "Métodos y por qué", "head": ["Método", "Uso", "Razón (la da el código)"], "rows": rows}
    if not val.get("scenarios"):
        note = {"title": "Valoración por TIR no proyectable", "head": ["Motivo (lo da el código)"],
                "rows": [[str(val.get("reason") or "")]]}
        t["escenarios"] = note
        t["descomposicion"] = {"title": "", "head": [], "rows": []}
        t["sensibilidad"] = {"title": "", "head": [], "rows": []}
        t["vigilar"] = {"title": "Qué vigilar: kill switches", "head": ["Métrica", "Umbral", "Hoy", "Estado", "Acción", "Por qué"],
                        "rows": [[s["metric"], s["threshold"], s["current"], s["status"], s["action"], s["why"]] for s in ctx.switches]}
        return t
    t["escenarios"] = {"title": "Escenarios", "head": [
        "Escenario", "Prob.", "Crec. 1–5", "Margen año 5", "Conversión", "Múltiplo salida", "TIR 5 a", "TIR 10 a",
        "Valor a la tasa exigida"], "rows": [
        [val["scenarios"][k]["label"], pct(val["probabilities"]["values"][k], 0),
         pct(val["scenarios"][k]["drivers"]["organic_growth"]), pct(val["scenarios"][k]["drivers"]["margin_target"]),
         pct(val["scenarios"][k]["drivers"]["cash_conversion"], 0), times(val["scenarios"][k]["drivers"]["exit_multiple"]),
         pct(val["scenarios"][k]["horizons"]["5"]["irr"]), pct(val["scenarios"][k]["horizons"]["10"]["irr"]),
         money((val.get("value_per_share") or {}).get(k), ccy)] for k in ("bear", "base", "bull")]
        + [["Ponderada", "—", "", "", "", "", pct(val["weighted"]["5"]), pct(val["weighted"]["10"]),
            money(val.get("weighted_value_per_share"), ccy)]]}
    from app.valuation.shareholder_irr import COMPONENT_LABELS, COMPONENTS

    t["descomposicion"] = {"title": "De dónde sale la TIR (puntos porcentuales al año)", "head": [
        "Componente", "Bajista 10 a", "Base 5 a", "Base 10 a", "Alcista 10 a"], "rows": [
        [COMPONENT_LABELS[c], pp(val["scenarios"]["bear"]["horizons"]["10"]["components"][c]),
         pp(val["scenarios"]["base"]["horizons"]["5"]["components"][c]),
         pp(val["scenarios"]["base"]["horizons"]["10"]["components"][c]),
         pp(val["scenarios"]["bull"]["horizons"]["10"]["components"][c])] for c in COMPONENTS]
        + [["TIR total", pct(val["scenarios"]["bear"]["horizons"]["10"]["irr"]), pct(val["scenarios"]["base"]["horizons"]["5"]["irr"]),
            pct(val["scenarios"]["base"]["horizons"]["10"]["irr"]), pct(val["scenarios"]["bull"]["horizons"]["10"]["irr"])]]}
    sens = val["sensitivity"]
    t["sensibilidad"] = {"title": "TIR a 5 años: crecimiento orgánico (filas) × múltiplo de salida (columnas)",
                         "head": ["Crecimiento \\ Múltiplo"] + [times(x) for x in sens["multiples"]],
                         "rows": [[pct(g)] + [pct(c) for c in row] for g, row in zip(sens["growths"], sens["irr"], strict=True)]}
    t["vigilar"] = {"title": "Qué vigilar: kill switches", "head": ["Métrica", "Umbral", "Hoy", "Estado", "Acción", "Por qué"],
                    "rows": [[s["metric"], s["threshold"], s["current"], s["status"], s["action"], s["why"]] for s in ctx.switches]}
    return t


def _cite_text(c: Any) -> str:
    if not isinstance(c, Mapping):
        return ""
    if c.get("formula"):
        return str(c["formula"])
    bits = [str(c.get("document") or ""), str(c.get("period") or ""), f"presentado {c['filed']}" if c.get("filed") else ""]
    return " · ".join(b for b in bits if b)


# ---------------------------------------------------------------------------------------------- redacción

@dataclass
class ThesisResult:
    status: str  # ok | cached | stripped | rejected | error | insufficient
    sections: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    fingerprint: str | None = None
    probability_choice: str | None = None
    probability_reason: str | None = None


def thesis_fingerprint(ctx: ThesisContext) -> str:
    blob = json.dumps({"v": THESIS_V2_VERSION, "val": ctx.valuation.get("fingerprint"),
                       "markers": sorted(thesis_markers(ctx)), "optional": sorted(ctx.optional),
                       "passages": [hashlib.sha256((p["text"] or "").encode()).hexdigest()[:12] for p in ctx.passages]},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def active_sections(ctx: ThesisContext) -> list[tuple[str, str, str, tuple[str, ...]]]:
    return [s for s in SECTIONS if s[0] not in OPTIONAL or s[0] in ctx.optional]


# Nombres de normas y formularios: no son cifras («IFRS 16», «NIC 36», «ASC 842», «Form 20-F», «Pilar 2»).
_NAMES = re.compile(r"\b(?:IFRS|NIIF|IAS|NIC|ASC|ASU|US\s?GAAP\s?ASC|Pilar|Pillar|Basilea|Basel|Solvencia|Solvency|"
                    r"Form|formulario|Regla|Rule|Item|Nivel|Level|Tier)\s?\d+(?:[-–]\d+)?[A-Z]?\b"
                    r"|\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b"
                    r"|\b\d{1,2}-[KFQ]\b|\b(?:20|40|10|6|8)-[A-Z]\b|\bS&P\s?500\b|\bQ[1-4]\b|\bH[12]\b|\b[1-4]T\b", re.I)


def _masked(text: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def keep(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return "\x01" + chr(0xE100 + len(kept) - 1) + "\x01"

    return _NAMES.sub(keep, text or ""), kept


def _unmasked(text: str, kept: Sequence[str]) -> str:
    return re.sub("\x01(.)\x01", lambda m: kept[ord(m.group(1)) - 0xE100], text)


def loose_numbers(text: str) -> list[str]:
    """Números libres del texto, sin contar nombres de normas ni de formularios."""
    return free_numbers(_masked(text)[0].replace("\x01", " "))


def strip_loose(text: str) -> str:
    work, kept = _masked(text)
    return _unmasked(strip_free_numbers(work), kept)


def _parse(text: str, keys: Sequence[str]) -> tuple[dict[str, str] | None, dict[str, Any]]:
    from app.llm.json import parse_json_response

    parsed: Any = None
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if 0 <= start < end:
        try:  # saltos de línea literales dentro de las cadenas (párrafos): JSON no estricto
            parsed = json.loads(text[start:end + 1], strict=False)
        except ValueError:
            parsed = None
    if parsed is None:
        try:
            parsed = parse_json_response(text)
        except Exception:  # noqa: BLE001
            return None, {}
    raw = parsed.get("sections") if isinstance(parsed, dict) else None
    if not isinstance(raw, dict):
        return None, {}
    out = {k: str(raw.get(k) or "").strip() for k in keys}
    return (out if any(out.values()) else None), parsed


async def write_thesis(*, reasoner: Reasoner, ctx: ThesisContext, cached: Mapping[str, Any] | None = None,
                       max_tokens: int = 24000) -> ThesisResult:
    """Dos llamadas (secciones 1–8 y 9–15), validadas; nunca lanza."""
    from app.valuation.shareholder_irr_rules import PROBABILITY_SETS

    fp = thesis_fingerprint(ctx)
    if cached and cached.get("fingerprint") == fp and cached.get("sections"):
        return ThesisResult(status="cached", sections=dict(cached["sections"]), fingerprint=fp,
                            probability_choice=cached.get("probability_choice"),
                            probability_reason=cached.get("probability_reason"))
    markers = thesis_markers(ctx)
    out = ThesisResult(status="ok", fingerprint=fp)
    tabs = tables(ctx)
    if ctx.valuation.get("status") == "not_meaningful":
        system_note = ("La valoración por TIR NO se puede proyectar con los datos contables ({{valoracion.motivo}}): "
                       "en «Valoración» y «Qué descuenta el precio» explica por qué, qué dato falta para hacerla y qué "
                       "dice mientras tanto el punto de partida; no inventes escenarios ni rentabilidades.")
    else:
        system_note = ""
    base_payload = {
        "empresa": ctx.company, "ticker": ctx.ticker, "marcadores": marker_catalog(ctx),
        "avisos_de_datos": ctx.valuation.get("warnings") or [],
        "metodo": ctx.valuation.get("method"), "pasajes": ctx.passages,
        "kill_switches": ctx.switches, "secciones_opcionales": ctx.optional, "guia": ctx.guidance,
        "consenso_de_analistas": "no hay todavía rangos de analistas guardados para esta empresa: dilo así",
    }
    stripped = False
    for part in ("a", "b"):
        secs = [s for s in active_sections(ctx) if s[2] == part]
        keys = [s[0] for s in secs]
        payload = {**base_payload, "secciones": [{"clave": k, "titulo": title,
                                                    "tablas_debajo": {n: tabs[n] for n in tn}} for k, title, _, tn in secs]}
        extra = PROB_FIELD.format(choices=list(PROBABILITY_SETS)) if part == "b" else ""
        system = PROMPT + ("\n\n" + system_note if system_note else "") + "\n\n" + CONTRACT.format(keys=", ".join(f'"{k}": str' for k in keys), extra=extra)
        accepted: dict[str, str] = {}
        pending: dict[str, str] = {}  # texto con problemas: si no se arregla, se limpia al final
        todo = list(keys)
        for _ in range(MAX_ATTEMPTS):
            out.llm_calls += 1
            try:
                text = await reasoner(system, json.dumps(payload, ensure_ascii=False, default=str), max_tokens,
                                      f"expert_team.tesis_v2_{part}")
            except Exception as exc:  # noqa: BLE001
                out.status, out.problems = "error", [f"llm:{type(exc).__name__}"]
                return out
            sections, parsed = _parse(text, todo)
            if sections is None:
                payload["problemas_respuesta_anterior"] = ["la respuesta no trae las secciones en JSON"]
                continue
            if part == "b" and out.probability_choice is None:
                # El modelo a veces anida la elección dentro de «sections»: se acepta en los dos sitios.
                raw = parsed.get("sections") if isinstance(parsed.get("sections"), dict) else {}
                choice = parsed.get("probabilidades") or raw.get("probabilidades")
                reason = parsed.get("probabilidades_razon") or raw.get("probabilidades_razon")
                if choice in PROBABILITY_SETS:
                    out.probability_choice = str(choice)
                    out.probability_reason = strip_loose(str(reason or ""))[:400]
            problems = []
            for k, body in sections.items():
                if not body:
                    continue  # una sección vacía no sustituye a lo ya escrito
                issues = []
                loose = loose_numbers(body)
                if loose:
                    issues.append(f"{k}: números sin marcador: {', '.join(loose[:6])}")
                bad = unknown_markers(body, markers)
                if bad:
                    issues.append(f"{k}: marcadores que no existen: {', '.join(bad[:6])}")
                if issues:
                    pending[k] = body
                    problems.extend(issues)
                else:
                    accepted[k] = body
                    pending.pop(k, None)
            todo = [k for k in keys if k not in accepted]
            if not todo:
                break
            out.problems.extend(problems)
            # El reintento solo pide las secciones pendientes, con su texto anterior y sus problemas.
            payload["secciones"] = [s for s in payload["secciones"] if s["clave"] in todo]
            payload["problemas_respuesta_anterior"] = problems[:20] or ["faltan estas secciones"]
            payload["texto_anterior"] = {k: pending[k] for k in todo if k in pending}
            system = PROMPT + ("\n\n" + system_note if system_note else "") + "\n\n" + CONTRACT.format(
                keys=", ".join(f'"{k}": str' for k in todo), extra=extra)
        out.sections.update(accepted)
        if pending:
            stripped = True
            out.sections.update({k: MARKER.sub(lambda mm: mm.group(0) if mm.group(1) in markers else "",
                                               strip_loose(v)) for k, v in pending.items() if k not in accepted})
    if not out.sections:
        out.status = "rejected"
    elif stripped:
        out.status = "stripped"
    return out


_DOUBLE_TIMES = re.compile(r"(\d)x\s+veces\b")


def render(sections: Mapping[str, str], markers: Mapping[str, str]) -> dict[str, str]:
    """Sustituye los marcadores; «15,8x veces» (el marcador ya lleva la x) queda «15,8x»."""
    return {k: _DOUBLE_TIMES.sub(r"\1x", MARKER.sub(lambda m: markers.get(m.group(1), ""), v or ""))
            for k, v in sections.items()}


# --------------------------------------------------------------------------------------- guardar / leer

def _latest_row(db: Session, company: Company):
    from app.models.declared_input_value import DeclaredInputValue

    return db.scalars(select(DeclaredInputValue).where(
        DeclaredInputValue.company_id == company.id, DeclaredInputValue.input_key == INPUT_KEY,
        DeclaredInputValue.superseded_at.is_(None)).order_by(desc(DeclaredInputValue.id))).first()


def generate_thesis_v2(db: Session, company: Company, *, reasoner: Reasoner | None = None, today: date | None = None,
                       tenant_id: int | None = None, timeout: float = 900) -> dict[str, Any]:
    """Calcula, redacta (o reutiliza por huella) y guarda. Devuelve la tesis lista para mostrar."""
    from datetime import UTC, datetime

    from app.models.declared_input_value import DeclaredInputValue
    from app.services.async_bridge import run_from_any_context

    today = today or date.today()
    if tenant_id is None:
        tid = db.info.get("tenant_id")
        tenant_id = tid if type(tid) is int else None
    ctx = build_context(db, company, today=today, tenant_id=tenant_id)
    if reasoner is None:
        from app.services.expert_team.service import provider_reasoner

        reasoner = provider_reasoner(db=db, commit_usage=False, temperature=0.0)
    if ctx.valuation.get("status") not in ("ok", "not_meaningful"):
        return {"status": ctx.valuation.get("status"), "reason": ctx.valuation.get("reason"),
                "ticker": company.ticker, "valuation": ctx.valuation}
    row = _latest_row(db, company)
    cached = (row.metadata_ or {}).get("thesis") if row is not None else None
    res = run_from_any_context(write_thesis(reasoner=reasoner, ctx=ctx, cached=cached), timeout=timeout)
    if res.probability_choice and ctx.valuation.get("probabilities") and \
            res.probability_choice != ctx.valuation["probabilities"]["choice"]:
        from app.services.shareholder_irr_service import value_company

        ctx.valuation = value_company(db, company, today=today, probability_choice=res.probability_choice)
        ctx.switches = kill_switches(ctx.valuation, ctx.history)
    markers = thesis_markers(ctx)
    doc = {
        "status": res.status, "version": THESIS_V2_VERSION, "fingerprint": res.fingerprint,
        "sections": res.sections, "problems": res.problems[:20], "llm_calls": res.llm_calls,
        "probability_choice": res.probability_choice, "probability_reason": res.probability_reason,
    }
    if res.sections and not (res.status == "cached" and row is not None):
        if row is not None:
            row.superseded_at = datetime.now(UTC)
        weighted = (ctx.valuation.get("weighted") or {}).get("10")
        db.add(DeclaredInputValue(
            company_id=company.id, input_key=INPUT_KEY, segment_key="", base=Decimal(str(round(weighted or 0.0, 6))),
            unit="ratio", status="derivado", method="derive", as_of=today, model_family=THESIS_V2_VERSION,
            fingerprint=res.fingerprint, source_quote="Tesis v2 de los agentes expertos sobre la TIR determinista",
            metadata_={"thesis": doc, "markers": markers, "valuation_fingerprint": ctx.valuation.get("fingerprint")},
        ))
        db.commit()
    return present(ctx, doc, markers)


def present(ctx: ThesisContext, doc: Mapping[str, Any], markers: Mapping[str, str]) -> dict[str, Any]:
    rendered = render(doc.get("sections") or {}, markers)
    tabs = tables(ctx)
    return {
        "status": doc.get("status"), "ticker": ctx.ticker, "company": ctx.company, "version": THESIS_V2_VERSION,
        "as_of": ctx.valuation.get("as_of"), "fingerprint": doc.get("fingerprint"),
        "probability_choice": doc.get("probability_choice"), "probability_reason": doc.get("probability_reason"),
        "sections": [{"key": k, "title": _title(k, title, ctx), "text": rendered.get(k, ""), "tables": [tabs[n] for n in tn]}
                     for k, title, _, tn in active_sections(ctx)],
        "headline": {"price": markers.get("punto.precio"), "tir5": markers.get("pond.tir5"),
                     "tir10": markers.get("pond.tir10"), "base_tir10": markers.get("esc.base.tir10"),
                     "multiple": markers.get("punto.multiplo"), "peers_median": markers.get("comparables.mediana"),
                     "cost_of_equity": markers.get("tasa.coste_capital")},
        "warnings": ctx.valuation.get("warnings") or [],
        "sources": sorted({p["document"] for p in ctx.passages if p.get("document")}),
        "llm_calls": doc.get("llm_calls"),
    }


def _title(key: str, title: str, ctx: ThesisContext) -> str:
    """El título del historial dice cuántos ejercicios hay de verdad (ESEF trae cinco, no diez)."""
    if key == "historial" and ctx.history:
        n = min(len(ctx.history), 10)
        return title.replace("diez años", f"{n} ejercicios" if n != 10 else "diez años")
    return title


def read_thesis_v2(db: Session, company: Company, *, today: date | None = None) -> dict[str, Any] | None:
    """La última tesis guardada, con las cifras del cálculo de hoy si la huella de la valoración no cambió,
    y con las cifras guardadas junto al texto si cambió (el texto se escribió para esas)."""
    row = _latest_row(db, company)
    if row is None:
        return None
    meta = row.metadata_ or {}
    ctx = build_context(db, company, today=today or date.today())
    if ctx.valuation.get("status") not in ("ok", "not_meaningful"):
        return None
    same = meta.get("valuation_fingerprint") == ctx.valuation.get("fingerprint")
    markers = thesis_markers(ctx) if same else dict(meta.get("markers") or {})
    out = present(ctx, meta.get("thesis") or {}, markers)
    out["stale"] = not same
    return out


def attach_to_thesis_run(db: Session, run_id: int, ticker: str) -> dict[str, Any]:
    """Tras confirmar la tesis: genera (o reutiliza por huella) la tesis v2 y lo anota en el run. Nunca lanza."""
    from app.core.config import get_settings
    from app.models.entities import WorkflowRun
    from app.services.company_resolver import resolve_company

    if not getattr(get_settings(), "thesis_v2_enabled", True):
        return {"status": "disabled"}
    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return {"status": "no_tenant"}
    try:
        company = resolve_company(db, ticker)
        if company is None:
            outcome: dict[str, Any] = {"status": "no_company"}
        else:
            out = generate_thesis_v2(db, company, tenant_id=tenant_id)
            outcome = {"status": out.get("status"), "llm_calls": out.get("llm_calls"),
                       "fingerprint": out.get("fingerprint")}
    except Exception as exc:  # noqa: BLE001 - la tesis ya está publicada
        db.rollback()
        outcome = {"status": "error", "problems": [type(exc).__name__]}
    try:
        run = db.get(WorkflowRun, run_id)
        if run is not None:
            run.result_payload = {**(run.result_payload or {}), "thesis_v2": outcome}
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return outcome


__all__ = [
    "INPUT_KEY",
    "attach_to_thesis_run",
    "SECTIONS",
    "THESIS_V2_VERSION",
    "ThesisContext",
    "build_context",
    "generate_thesis_v2",
    "implied_growth",
    "kill_switches",
    "read_thesis_v2",
    "render",
    "tables",
    "thesis_markers",
    "write_thesis",
]
