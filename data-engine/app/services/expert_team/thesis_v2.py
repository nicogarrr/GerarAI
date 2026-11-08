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
import statistics
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
#: Plazo por petición y total de cada llamada al modelo de la tesis v2 (respuesta de hasta 24.000 tokens).
CALL_TIMEOUT_SECONDS = 600.0
CALL_TOTAL_TIMEOUT_SECONDS = 900.0
PASSAGES_PER_GROUP = 6
MAX_CHUNKS_PER_DOC = 1500

#: (clave, título, parte de la llamada, tablas que pinta el código debajo del texto)
SECTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("introduccion", "1. Introducción: qué estamos comprando realmente", "a", ("partida",)),
    ("sector_estrategia", "2. Sector y estrategia", "a", ()),
    ("ventaja_competitiva", "3. Ventaja competitiva: por qué podría perdurar", "a", ()),
    ("directivos_capital", "4. Directivos, cultura y asignación de capital", "a", ("capital", "insiders")),
    ("contabilidad", "5. Cómo leer la contabilidad", "a", ("ajustes",)),
    ("historial", "6. Historial: diez años en cifras", "a", ("historial",)),
    ("comparables", "7. Comparables calculados", "a", ("comparables",)),
    ("deuda_balance", "8. Balance y deuda", "a", ()),
    ("consenso_guia", "8 bis. Guía de la empresa y consenso", "a", ("guia", "analistas")),
    ("metodo", "9. Por qué este método", "b", ("metodos",)),
    ("valoracion", "10. Valoración: qué rentabilidad esperamos y de dónde sale", "b",
     ("escenarios", "supuestos", "descomposicion", "sensibilidad")),
    ("que_descuenta", "11. Qué descuenta el precio", "b", ("descuenta",)),
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
    "informe anual»). Los marcadores de múltiplo ya llevan la «x»: no añadas «veces» detrás. CITAS: lo que "
    "pongas entre comillas como palabras de un documento se copia TAL CUAL del pasaje, en su idioma original "
    "(normalmente inglés), y la traducción va al lado así: «original» (traducción: «…»). Nunca pongas entre "
    "comillas una traducción ni un resumen tuyo; si no copias literal, escríbelo en estilo indirecto."
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

KIND_LABELS = {"operating": "empresa operativa", "insurer": "aseguradora", "bank": "banco",
               "holding": "holding o gestora", "real_estate": "inmobiliaria (REIT)",
               "pre_revenue": "empresa sin beneficio (preingresos o quema caja)"}


def basis_labels(sp: Mapping[str, Any]) -> dict[str, str]:
    """Cómo se llama cada pieza según la base de la valoración (lo usan tablas, umbrales y marcadores)."""
    basis = sp.get("basis")
    if basis == "pb":
        return {"earnings": "Valor contable atribuible", "earnings_formula": "patrimonio de la matriz − preferentes",
                "multiple": "P/VC", "margin": "ROE", "conversion": "Reparto (dividendos + recompras) / beneficio",
                "growth": "Crecimiento del valor contable"}
    if basis == "pe" and sp.get("earnings_label") == "FFO":
        return {"earnings": "FFO de partida", "earnings_formula": "beneficio neto + amortizaciones − plusvalías por ventas",
                "multiple": "P/FFO", "margin": "Margen FFO", "conversion": "Conversión de caja (flujo libre / FFO)",
                "growth": "Crecimiento de ingresos"}
    if basis == "pe":
        return {"earnings": "Beneficio de partida", "earnings_formula": "beneficio neto atribuible", "multiple": "PER",
                "margin": "Margen neto", "conversion": "Conversión de caja (flujo libre / beneficio)",
                "growth": "Crecimiento de ingresos"}
    return {"earnings": "EBITDA de partida", "earnings_formula": "resultado operativo + amortizaciones del último ejercicio",
            "multiple": "EV / EBITDA", "margin": "Margen EBITDA", "conversion": "Conversión de caja (flujo libre / EBITDA)",
            "growth": "Crecimiento de ingresos"}


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

    labels = basis_labels(sp)
    pb = sp.get("basis") == "pb"
    g_now = last.get("growth")
    g_prev = prev.get("growth")
    if pb:  # el «crecimiento» del escenario es el del valor contable por acción
        bv = [r.get("book_per_share") for r in hist_rows[-3:]]
        g_now = (bv[-1] / bv[-2] - 1) if len(bv) >= 2 and bv[-1] and bv[-2] else None
        g_prev = (bv[-2] / bv[-3] - 1) if len(bv) >= 3 and bv[-2] and bv[-3] else None
    thr = bear.get("organic_growth")
    rw = val.get("runway") or {}
    if rw:
        months = rw.get("months")
        add("runway", "Meses de caja al consumo del último ejercicio", "< 12 meses", _es(months, 0) + " meses" if months else "sin consumo",
            months is not None and months < 12, "revisar: ampliación de capital o deuda a la vista",
            "sin caja para llegar a los hitos, la financiación la pone el precio de la acción")
        dil = rw.get("dilution_cagr")
        add("dilucion_anual", "Dilución anual (TCAC de acciones diluidas, 3 años)", "> +10 % al año", pct(dil, signed=True),
            dil is not None and dil > 0.10, "revisar", "cada ampliación reparte el valor futuro entre más acciones")
        ev_cash = rw.get("ev_to_cash")
        add("ev_caja", "Valor de empresa / caja", "≤ 1,0x (el mercado no paga nada por el negocio)", times(ev_cash),
            ev_cash is not None and ev_cash <= 1.0, "ampliar", "a ese precio se compra la caja y el resto sale gratis")
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
    add("crecimiento", f"{labels['growth']} anual" + (" por acción" if pb else ""), f"< {pct(thr)} dos ejercicios seguidos",
        pct(g_now), g_now is not None and g_prev is not None and g_now < thr and g_prev < thr,
        "revisar y, si se confirma, vender", "falla la palanca de crecimiento del escenario base")
    m_now = last.get("margin")
    add("margen", labels["margin"], f"< {pct(bear['margin_target'])}",
        pct(m_now), m_now is not None and m_now < bear["margin_target"], "revisar el foso",
        "pérdida de poder de precio o de eficiencia por debajo del peor de los tres últimos ejercicios")
    c_now = last.get("conversion")
    if pb:
        d_now = ((last.get("dividends") or 0.0) + (last.get("buybacks") or 0.0)) / last["net_income"] \
            if last.get("net_income") and last["net_income"] > 0 else None
        add("reparto", labels["conversion"], f"> {pct(1.0, 0)}", pct(d_now, 0), d_now is not None and d_now > 1.0,
            "revisar", "repartir más de lo que se gana consume el valor contable que compone")
        add("valor_contable", "Valor contable por acción", "cae en un ejercicio", pct(g_now, signed=True),
            g_now is not None and g_now < 0, "revisar y, si se repite, vender",
            "la tesis es que el valor contable compone; si encoge, falla la suscripción o la inversión")
    else:
        add("conversion", labels["conversion"], f"< {pct(bear['cash_conversion'])}",
            pct(c_now), c_now is not None and c_now < bear["cash_conversion"], "revisar capex y circulante",
            "menos caja para dividendo, recompras y deuda")
    lev = (sp["net_debt"] / sp["ebitda"]) if (sp.get("ebitda") and sp.get("basis") == "ev_ebitda") else None
    lim = max(2.5, (lev or 0) + 1.0)
    if lev is not None:
        add("apalancamiento", "Deuda neta / EBITDA", f"> {times(lim)}", times(lev), lev > lim,
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
        add("multiplo", f"Múltiplo de la propia empresa ({labels['multiple']})", f"> {times(val['scenarios']['bull']['drivers']['exit_multiple'])}",
            times(sp.get("multiple")), (sp.get("multiple") or 0) > val["scenarios"]["bull"]["drivers"]["exit_multiple"],
            "recortar", "el mercado ya paga el múltiplo del escenario alcista")
    return out


def history_rows(cites: Mapping[str, Any], basis: str, points: Mapping[str, Mapping[int, float]],
                 earnings_label: str = "") -> list[dict]:
    """Historial por ejercicio. «margin» sigue la base: EBITDA, neto, FFO (REIT) o ROE (valor contable)."""
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
        if basis == "pe" and earnings_label == "FFO" and ni is not None:
            ni_ffo = ni + abs(da or 0.0) - (v("gain_on_sale_real_estate", y) or 0.0)
        else:
            ni_ffo = ni
        earnings = ni_ffo if basis == "pe" else ebitda
        eq = (points.get("total_equity") or {}).get(y)
        debt = (points.get("total_debt") or {}).get(y)
        cash = (points.get("cash_and_equivalents") or {}).get(y)
        tax = 0.25
        invested = (eq + (debt or 0.0) - (cash or 0.0)) if eq is not None else None
        roic = (oi * (1 - tax) / invested) if (oi is not None and invested and invested > 0) else None
        rows.append({
            "year": y, "revenue": rev, "growth": (rev / prev_rev - 1) if rev and prev_rev else None,
            "ebitda": ebitda, "net_income": ni,
            "margin": ((ni / eq) if (ni is not None and eq) else None) if basis == "pb" else
                      ((earnings / rev) if earnings is not None and rev else None),
            "book": eq, "book_per_share": (eq / sh_raw) if (eq and sh_raw) else None,
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
    cik: str | None = None
    insiders: dict[str, Any] | None = None  # insider_summary (#4751): Form 4 de la SEC, deterministas
    analysts: list[dict[str, Any]] = field(default_factory=list)  # estimaciones citadas de prensa (#4753)
    price_targets: list[dict[str, Any]] = field(default_factory=list)


def insider_block(db: Session, company: Company, today: date) -> dict[str, Any] | None:
    """Resumen determinista de insiders (Form 4/5 de la SEC, #4751), o None si no hay datos."""
    try:
        from app.services.insider_summary import insider_summary

        s = insider_summary(db, company.ticker, as_of=today)
    except Exception as exc:  # noqa: BLE001 - sin insiders la tesis sigue y lo dice
        logger.info("thesis v2 insiders: %s", type(exc).__name__)
        return None
    return s if s.get("status") != "sin_datos" and s.get("windows") else None


def analyst_estimates(db: Session, company: Company, today: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(estimaciones por firma, métrica y año; precios objetivo) citadas de la prensa gratuita (#4753).
    Solo las vigentes; los precios objetivo de los últimos 12 meses, el último de cada firma."""
    from datetime import timedelta

    from app.models.declared_input_value import DeclaredInputValue

    out: list[dict[str, Any]] = []
    try:
        rows = db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.company_id == company.id, DeclaredInputValue.method == "analyst",
            DeclaredInputValue.input_key.like("analyst.%"), DeclaredInputValue.superseded_at.is_(None))
            .order_by(DeclaredInputValue.input_key)).all()
    except Exception:  # noqa: BLE001
        rows = []
    for r in rows:
        meta = r.metadata_ or {}
        if r.base is None or meta.get("consensus"):
            continue
        out.append({"firm": r.analyst_firm or meta.get("firm") or "", "metric": meta.get("metric") or r.input_key.split(".")[1],
                    "year": meta.get("year"), "value": float(r.base) / 1e6, "as_of": r.as_of.isoformat() if r.as_of else "",
                    "url": r.source_url, "quote": r.source_quote})
    targets: dict[str, dict[str, Any]] = {}
    try:
        from app.models import AnalystNote

        notes = db.scalars(select(AnalystNote).where(
            AnalystNote.ticker == company.ticker, AnalystNote.pt_new.is_not(None),
            AnalystNote.note_date >= today - timedelta(days=365)).order_by(AnalystNote.note_date)).all()
    except Exception:  # noqa: BLE001
        notes = []
    for n in notes:
        targets[n.firm] = {"firm": n.firm, "target": float(n.pt_new), "currency": n.currency or "",
                           "date": n.note_date.isoformat(), "url": n.source_url}
    return out, sorted(targets.values(), key=lambda x: x["target"])


def build_context(db: Session, company: Company, *, today: date, tenant_id: int | None = None) -> ThesisContext:
    from app.services.shareholder_irr_service import value_company

    val = value_company(db, company, today=today)
    val.setdefault("as_of", today.isoformat())
    name = display_name(company.name or company.ticker)
    if val.get("status") not in ("ok", "not_meaningful"):
        return ThesisContext(company.ticker, name, val, [], [], [], None, [])
    points = _point_by_year(db, company, ("total_equity", "total_debt", "cash_and_equivalents"))
    hist = history_rows(val["citations"], val["starting_point"]["basis"], points,
                        val["starting_point"].get("earnings_label") or "")
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
    if sp.get("basis") == "ev_ebitda" and sp.get("ebitda") and sp.get("net_debt", 0) > 0 and sp["net_debt"] / sp["ebitda"] > 1.0:
        optional["deuda_balance"] = "deuda neta superior a una vez el EBITDA"
    passages = evidence_passages(db, company, tenant_id)
    guidance = company_guidance_rows(db, company)
    if guidance:
        optional["consenso_guia"] = "la empresa da previsiones citadas en sus notas de resultados"
    switches += estimate_switches(guidance, sp.get("currency") or "", (val.get("citations") or {}).get("annual"))
    insiders = insider_block(db, company, today)
    analysts, targets = analyst_estimates(db, company, today)
    if (analysts or targets) and "consenso_guia" not in optional:
        optional["consenso_guia"] = "hay estimaciones de analistas citadas de la prensa"
    return ThesisContext(company.ticker, name, val, hist, peers, switches, ig, passages, optional, guidance,
                         getattr(company, "cik", None), insiders, analysts, targets)


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
    meth = val.get("method") or {}
    lab = basis_labels(sp)
    m |= {"metodo.tipo": KIND_LABELS.get(str(meth.get("kind") or "operating"), "empresa operativa"),
          "metodo.regla": str(meth.get("kind_method") or ""), "metodo.motivo_tipo": str(meth.get("kind_reason") or ""),
          "metodo.multiplo": lab["multiple"]}
    if sp.get("basis") == "pb":
        m["punto.valor_contable"] = millions(sp["revenue"], ccy)
        m["punto.roe"] = pct(sp.get("margin"))
        m["punto.vc_accion"] = money(sp["revenue"] / sp["shares_diluted"] if sp.get("shares_diluted") else None, ccy)
    if sp.get("earnings_label") == "FFO":
        m["punto.ffo"] = millions(sp["net_income"], ccy)
        m["punto.ffo_accion"] = money(sp["net_income"] / sp["shares_diluted"] if sp.get("shares_diluted") else None, ccy)
    rw = val.get("runway") or {}
    if rw:
        m |= {"caja.caja": millions(rw.get("cash"), ccy), "caja.consumo": millions(rw.get("burn"), ccy),
              "caja.meses": (_es(rw["months"], 0) + " meses") if rw.get("months") else "sin consumo",
              "caja.dilucion": pct(rw.get("dilution_cagr"), signed=True), "caja.ev_caja": times(rw.get("ev_to_cash")),
              "caja.ev_ingresos": times(rw.get("ev_to_revenue")), "caja.ejercicio": str(rw.get("year") or "")}
    _insider_markers(m, ctx)
    if val.get("status") == "not_meaningful":
        m["valoracion.motivo"] = str(val.get("reason") or "")
        _history_markers(m, ctx, ccy)
        return m
    m |= {
        "pond.tir5": pct(val["weighted"].get("5")), "pond.tir10": pct(val["weighted"].get("10")),
        "pond.valor": money(val.get("weighted_value_per_share"), ccy),
        "base.tir10_multiplo_congelado": pct(val.get("base_frozen_multiple_irr_10")),
        "descuenta.crecimiento": pct(ctx.implied_growth),
        "descuenta.percentil": implied_percentile(
            ctx.implied_growth, ((val.get("trace") or {}).get("crecimiento") or {}).get("tasa_base")) or "N/D",
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


def _usd_millions(v: float | None) -> str:
    """Importe de insiders (dólares) en millones con un decimal: 2.700.000 → «2,7 M$»."""
    return "N/D" if v is None else f"{_es(v / 1e6, 1)} M$"


def _insider_markers(m: dict[str, str], ctx: ThesisContext) -> None:
    """Insiders (Form 4, #4751) y estimaciones citadas de analistas (#4753) como marcadores."""
    s = ctx.insiders or {}
    for w in s.get("windows") or []:
        n = {90: "3m", 180: "6m", 365: "12m"}.get(int(w.get("days") or 0))
        if not n:
            continue
        m[f"insiders.{n}.compras"] = str(w["buys"]["trades"])
        m[f"insiders.{n}.compras_valor"] = _usd_millions(w["buys"]["value"])
        m[f"insiders.{n}.ventas"] = str(w["sells"]["trades"])
        m[f"insiders.{n}.ventas_valor"] = _usd_millions(w["sells"]["value"])
        m[f"insiders.{n}.ventas_plan"] = str(w["sells"]["planned_10b5_1"])
        m[f"insiders.{n}.neto"] = _usd_millions(w["net_value"])
    if s:
        m["insiders.compras_grupo"] = str(len(s.get("clusters") or []))
        late = s.get("late") or {}
        m["insiders.form4"] = str(late.get("filings", 0))
        m["insiders.tarde"] = str(late.get("late", 0))
    if ctx.price_targets:
        vals = [p["target"] for p in ctx.price_targets]
        ccy = ctx.price_targets[0].get("currency") or "USD"
        m["analistas.firmas_precio"] = str(len(vals))
        m["analistas.precio_min"] = money(min(vals), ccy)
        m["analistas.precio_mediana"] = money(statistics.median(vals), ccy)
        m["analistas.precio_max"] = money(max(vals), ccy)
    by: dict[tuple[str, int], list[float]] = {}
    for a in ctx.analysts:
        if a.get("year"):
            by.setdefault((str(a["metric"]), int(a["year"])), []).append(float(a["value"]))
    for (metric, year), vals in sorted(by.items()):
        k = f"analistas.{metric}.{year}"
        m[f"{k}.n"] = str(len(vals))
        m[f"{k}.mediana"] = millions(statistics.median(vals), "USD")
        if len(vals) > 1:
            m[f"{k}.min"], m[f"{k}.max"] = millions(min(vals), "USD"), millions(max(vals), "USD")


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


def source_link(cite: Any, cik: str | None) -> str | None:
    """Enlace de un clic al documento de donde sale la cifra: el filing de EDGAR por su accession (el ancla
    al hecho etiquetado llegará con fuentes-1, P4) o la URL https que trae la cita (ESEF, NSM, web)."""
    if not isinstance(cite, Mapping):
        return None
    acc = str(cite.get("accession") or "")
    if cite.get("source_type") == "SEC" and acc and cik and str(cik).strip().isdigit():
        return f"https://www.sec.gov/Archives/edgar/data/{int(str(cik).strip())}/{acc.replace('-', '')}/"
    url = str(cite.get("url") or "")
    return url if url.startswith("https://") and "browse-edgar" not in url else None


def plausible_guidance(g: Mapping[str, Any], annual: Mapping[str, Any] | None) -> bool:
    """Guía anual frente al último dato anual de la misma métrica: entre la mitad y el doble."""
    if not str(g.get("period") or "").startswith("fy") or not annual:
        return True
    metric = "eps_diluted" if g.get("metric") == "eps" else str(g.get("metric"))
    years = annual.get(metric) or {}
    if not years:
        return True
    last = years[max(years, key=lambda y: int(y))]
    actual = last.get("value") if isinstance(last, Mapping) else None
    if not actual or not g.get("base"):
        return True
    ratio = float(g["base"]) / float(actual)
    return 0.5 <= ratio <= 2.0


def implied_percentile(value: float | None, rate: Mapping[str, Any] | None) -> str | None:
    """Dónde cae el crecimiento implícito dentro de la distribución medida de su tramo (p25/p50/p75)."""
    if value is None or not rate or any(rate.get(q) is None for q in ("p25", "p50", "p75")):
        return None
    p25, p50, p75 = float(rate["p25"]), float(rate["p50"]), float(rate["p75"])
    if value < p25:
        return "por debajo del percentil 25"
    if value <= p50:
        return "entre los percentiles 25 y 50"
    if value <= p75:
        return "entre los percentiles 50 y 75"
    return "por encima del percentil 75"


def assumption_rows(val: Mapping[str, Any]) -> list[list[str]]:
    """Cada supuesto con su fuente y su confianza (alta: dato de la empresa; media: regla con historia
    suficiente; baja: regla sin historia o sin comparables)."""
    tr = val.get("trace") or {}
    sc = val.get("scenarios") or {}
    cr, mult, mna = tr.get("crecimiento") or {}, tr.get("multiplo") or {}, tr.get("mna") or {}

    def vals(key: str, fmt) -> list[str]:
        return [fmt((sc.get(k) or {}).get("drivers", {}).get(key)) for k in ("bear", "base", "bull")]

    rate = cr.get("tasa_base") or {}
    guide = cr.get("guia")
    years = int(cr.get("anos_historico") or 0)
    if guide:
        g_src, g_conf = f"guía de ingresos de la empresa ({guide.get('as_of') or 's/f'}) el año 1; luego la regla", "alta"
    elif years >= 3:
        g_src = (f"½ crecimiento orgánico histórico ({pct(cr.get('historico_organico'))}, {years} años) + ½ mediana "
                 f"de la tasa base del tramo {cr.get('tramo_tasa_base')} (n = {rate.get('n', 'N/D')}); bajista = "
                 "percentil 25 de la tasa base")
        g_conf = "media"
    else:
        g_src, g_conf = f"tasa base del tramo {cr.get('tramo_tasa_base')} (historia insuficiente)", "baja"
    n_peers = int(mult.get("n_comparables") or 0)
    rows = [
        ["Crecimiento orgánico años 1–5", *vals("organic_growth", pct), g_src, g_conf],
        ["Crecimiento orgánico años 6–10", *vals("organic_growth_late", pct),
         "se desvanece hacia la tasa base del tramo", "media" if years >= 3 else "baja"],
        ["Margen objetivo", *vals("margin_target", pct), "mínimo / mediana / máximo de los 3 últimos ejercicios",
         "alta" if len((tr.get("margen") or {}).get("ultimos") or []) >= 3 else "baja"],
        ["Conversión de caja", *vals("cash_conversion", lambda x: pct(x, 0)),
         "mínimo / mediana / máximo de los 3 últimos ejercicios",
         "alta" if len((tr.get("conversion") or {}).get("ultimos") or []) >= 3 else "baja"],
        ["Gasto en M&A (% de ingresos)", *vals("mna_spend_pct_revenue", pct), "media histórica de adquisiciones",
         "media" if mna.get("gasto_pct_ingresos") else "baja"],
        ["Múltiplo de salida", *vals("exit_multiple", times),
         (f"media del propio y la mediana de {n_peers} comparables" if n_peers >= 3
          else f"propio × 0,8 / 1 / 1,2 ({mult.get('por_que') or 'menos de 3 comparables'})"),
         "media" if n_peers >= 3 else "baja"],
    ]
    return rows


def estimate_switches(guidance: Sequence[Mapping[str, Any]], ccy: str,
                      annual: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Kill switches sobre estimaciones: el dato real por debajo del bajo de la guía de la empresa (o un 5 %
    por debajo del punto medio si no da rango). Se comprueban cuando se publica el resultado del periodo.
    Una guía anual a más de la mitad o el doble del último dato anual de la misma métrica no se usa: lo más
    probable es que la frase hable de otra cosa (un segmento, un trimestre)."""
    out = []
    for g in guidance:
        if g.get("metric") in ("capex",):
            continue  # más capex no es una mala noticia por sí mismo
        if not plausible_guidance(g, annual):
            continue
        low = g.get("low") if g.get("low") is not None else (g["base"] * 0.95 if g.get("base") else None)
        if low is None:
            continue
        out.append({"key": f"guia.{g['metric']}.{g['period']}", "metric": f"{g['metric']} {g['period']} frente a la guía",
                    "threshold": f"< {_guidance_value(g, low)}", "current": "pendiente de publicar",
                    "status": "pendiente", "action": "revisar la credibilidad de la dirección",
                    "why": "la empresa no cumple lo que ella misma anunció" + ("" if g.get("low") is not None
                                                                              else " (sin rango: 5 % bajo el punto medio)")})
    return out


def tables(ctx: ThesisContext) -> dict[str, dict[str, Any]]:
    """Las tablas que pinta el código (cabecera + filas de texto ya formateado)."""
    val = ctx.valuation
    sp = val["starting_point"]
    ccy = sp["currency"]
    cites = val.get("citations") or {}
    pc = cites.get("price") or {}
    t: dict[str, dict[str, Any]] = {}
    lab = basis_labels(sp)
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
        [lab["earnings"],
         millions({"pe": sp["net_income"], "pb": sp["revenue"]}.get(sp["basis"], sp["ebitda"]), ccy),
         lab["earnings_formula"]],
        ["Múltiplo de partida", times(sp["multiple"]), lab["multiple"]],
        ["Mediana de comparables", times(((val.get("trace") or {}).get("multiplo") or {}).get("mediana_comparables")),
         f"{((val.get('trace') or {}).get('multiplo') or {}).get('n_comparables', 0)} comparables calculados con la misma fórmula"],
    ]}
    annual = cites.get("annual") or {}
    last_year = str(ctx.history[-1]["year"]) if ctx.history else ""

    def link(c: Any) -> str | None:
        return source_link(c, ctx.cik)

    t["partida"]["links"] = [
        None, link(cites.get("shares")), None, link(cites.get("cash_and_equivalents")), link(cites.get("total_debt")),
        None, None, None, None, link((annual.get("operating_income") or {}).get(last_year)
                                     or (annual.get("net_income") or {}).get(last_year)), None, None]
    t["historial"] = {"title": "Historial (millones, ejercicio fiscal)", "head": [
        "Año", "Ingresos", "Crec.", lab["margin"], "FCF", "Conv.", "FCF/acción", "Acciones", "ROIC"], "rows": [
        [str(r["year"]), millions(r["revenue"], ccy), pct(r["growth"], signed=True), pct(r["margin"]),
         millions(r["fcf"], ccy), pct(r["conversion"], 0), money(r["fcf_per_share"], ccy), shares(r["shares"]),
         pct(r["roic"])] for r in ctx.history[-10:]]}
    if sp["basis"] == "pb":
        t["historial"] = {"title": "Historial del valor contable (millones, ejercicio fiscal)", "head": [
            "Año", "Ingresos", "Beneficio", "ROE", "Valor contable", "VC/acción", "Crec. VC/acción", "Acciones", "Reparto"],
            "rows": []}
        prev_bv = None
        for r in ctx.history[-10:]:
            bvps = r.get("book_per_share")
            dist = ((r.get("dividends") or 0.0) + (r.get("buybacks") or 0.0))
            t["historial"]["rows"].append([
                str(r["year"]), millions(r["revenue"], ccy), millions(r.get("net_income"), ccy), pct(r["margin"]),
                millions(r.get("book"), ccy), money(bvps, ccy), pct((bvps / prev_bv - 1) if bvps and prev_bv else None, signed=True),
                shares(r["shares"]), pct(dist / r["net_income"], 0) if r.get("net_income") and r["net_income"] > 0 else "N/D"])
            prev_bv = bvps
    t["historial"]["links"] = [link((annual.get("revenue") or {}).get(str(r["year"]))) for r in ctx.history[-10:]]
    t["capital"] = {"title": "Asignación de capital (millones)", "head": ["Año", "FCF", "Dividendos", "Recompras", "Adquisiciones"],
                    "rows": [[str(r["year"]), millions(r["fcf"], ccy), millions(r["dividends"], ccy),
                              millions(r["buybacks"], ccy), millions(r["acquisitions"], ccy)] for r in ctx.history[-6:]]}
    t["ajustes"] = {"title": "Ajustes y huecos de datos que señala el código", "head": ["Ajuste o hueco", "Efecto"], "rows": [
        [w.split(":", 1)[0].strip(), (w.split(":", 1)[1].strip() if ":" in w else "")] for w in val.get("warnings") or []]}
    t["comparables"] = {"title": "Comparables (calculados con la misma fórmula)", "head": [
        "Empresa", "Múltiplo", "Margen", "Crec. 3 años", "Deuda neta / EBITDA", "Nota"], "rows": [
        [f"{p.get('name') or p['ticker']} ({p['ticker']})", times(p.get("multiple")), pct(p.get("margin")),
         pct(p.get("growth")), times(p.get("leverage")), p.get("note") or ""] for p in ctx.peers]}
    ins = ctx.insiders or {}
    t["insiders"] = {"title": "Insiders: Form 4 de la SEC (compras y ventas en mercado; sin ejercicios, concesiones, retenciones ni regalos)",
                     "head": ["Ventana", "Compras", "Importe compras", "Ventas", "Importe ventas", "Con plan 10b5-1", "Neto"],
                     "rows": [[f"{w['days']} días", str(w["buys"]["trades"]), _usd_millions(w["buys"]["value"]),
                               str(w["sells"]["trades"]), _usd_millions(w["sells"]["value"]), str(w["sells"]["planned_10b5_1"]),
                               _usd_millions(w["net_value"])] for w in ins.get("windows") or []]}
    if ins:
        late = ins.get("late") or {}
        t["insiders"]["rows"].append(["Compras en grupo (3 años)", str(len(ins.get("clusters") or [])), "", "Form 4 tarde",
                                      f"{late.get('late', 0)} de {late.get('filings', 0)}", "", ""])
    t["analistas"] = {"title": "Estimaciones de analistas citadas (prensa gratuita; cada fila con su artículo)",
                      "head": ["Firma", "Métrica", "Año", "Estimación", "Fecha"],
                      "rows": [[a["firm"], str(a["metric"]), str(a.get("year") or ""), millions(a["value"], "USD"), a["as_of"]]
                               for a in ctx.analysts]
                      + [[p["firm"], "precio objetivo", "", money(p["target"], p.get("currency") or "USD"), p["date"]]
                         for p in ctx.price_targets],
                      "links": [source_link({"url": a.get("url")}, None) for a in ctx.analysts]
                      + [source_link({"url": p.get("url")}, None) for p in ctx.price_targets]}
    t["guia"] = {"title": "Guía de la propia empresa (notas de resultados)", "head": [
        "Métrica", "Periodo", "Bajo", "Punto medio", "Alto", "Fuente"], "rows": [
        [g["metric"], g["period"], _guidance_value(g, g["low"]), _guidance_value(g, g["base"]), _guidance_value(g, g["high"]),
         (f"{g.get('document') or ''}" + ("" if (g.get("as_of") or "") in (g.get("document") or "")
                                             else f" ({g.get('as_of')})")
          + ("" if plausible_guidance(g, (val.get("citations") or {}).get("annual"))
             else " · no cuadra con el último dato anual: no se usa"))] for g in ctx.guidance],
        "links": [source_link({"url": g.get("url")}, None) for g in ctx.guidance]}
    meth = val.get("method") or {}
    labels = {"tir_ev_ebitda": "TIR para el accionista sobre EV/EBITDA", "tir_per": "TIR para el accionista sobre PER",
              "tir_pb": "TIR sobre el valor contable (ROE y P/VC)", "tir_ffo": "TIR sobre el FFO (P/FFO)",
              "caja_runway": "Caja, consumo y dilución (runway)", "dcf": "DCF con WACC", "sotp": "Suma de partes"}
    chosen = str(meth.get("chosen") or "")
    kind = str(meth.get("kind") or "")
    why_chosen = "cumple las condiciones de datos"
    if kind:
        why_chosen = f"{KIND_LABELS.get(kind, kind)}: {meth.get('kind_method') or ''}" + (
            f" ({meth['kind_reason']})" if meth.get("kind_reason") else "")
    rows = [[labels.get(chosen, chosen), "elegido", why_chosen]]
    rows += [[labels.get(k, k), "descartado", why] for k, why in (meth.get("discarded") or {}).items()]
    t["metodos"] = {"title": "Métodos y por qué", "head": ["Método", "Uso", "Razón (la da el código)"], "rows": rows}
    if not val.get("scenarios"):
        note = {"title": "Valoración por TIR no proyectable", "head": ["Motivo (lo da el código)"],
                "rows": [[str(val.get("reason") or "")]]}
        rw = val.get("runway") or {}
        if rw:
            f = rw.get("formulas") or {}
            note = {"title": f"Caja, consumo y dilución (ejercicio {rw.get('year') or ''})", "head": ["Concepto", "Valor", "Fórmula / fuente"], "rows": [
                ["Caja e inversiones a corto", millions(rw.get("cash"), ccy), _cite_text(cites.get("cash_and_equivalents"))],
                ["Deuda financiera", millions(rw.get("debt"), ccy), _cite_text(cites.get("total_debt"))],
                ["Flujo de caja operativo", millions(rw.get("operating_cash_flow"), ccy), _cite_text((rw.get("sources") or {}).get("ocf"))],
                ["Capex", millions(rw.get("capex"), ccy), _cite_text((rw.get("sources") or {}).get("capex"))],
                ["Consumo anual de caja", millions(rw.get("burn"), ccy), f.get("consumo", "")],
                ["Meses de margen (runway)", _es(rw["months"], 0) if rw.get("months") else "sin consumo", f.get("meses", "")],
                ["Dilución anual", pct(rw.get("dilution_cagr"), signed=True), f.get("dilucion", "")],
                ["Valor de empresa / caja", times(rw.get("ev_to_cash")), "EV / (caja + inversiones a corto)"],
                ["Valor de empresa / ingresos", times(rw.get("ev_to_revenue")), "EV / ingresos del último ejercicio"],
            ], "links": [link(cites.get("cash_and_equivalents")), link(cites.get("total_debt")),
                         link((rw.get("sources") or {}).get("ocf")), link((rw.get("sources") or {}).get("capex")),
                         None, None, None, None, None]}
        t["escenarios"] = note
        t["descomposicion"] = {"title": "", "head": [], "rows": []}
        t["sensibilidad"] = {"title": "", "head": [], "rows": []}
        t["supuestos"] = {"title": "", "head": [], "rows": []}
        t["descuenta"] = {"title": "", "head": [], "rows": []}
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
    t["supuestos"] = {"title": "De dónde sale cada supuesto (fuente y confianza)", "head": [
        "Supuesto", "Bajista", "Base", "Alcista", "Fuente (la regla del código)", "Confianza"], "rows": assumption_rows(val)}
    cr = (val.get("trace") or {}).get("crecimiento") or {}
    rate = cr.get("tasa_base") or {}
    t["descuenta"] = {"title": "Qué descuenta el precio frente a las referencias", "head": ["Referencia", "Crecimiento anual", "Nota"], "rows": [
        ["Implícito en el precio (TIR base a 10 años = coste del capital)", pct(ctx.implied_growth),
         implied_percentile(ctx.implied_growth, rate) and f"{implied_percentile(ctx.implied_growth, rate)} de su tramo" or ""],
        ["Escenario base (años 1–5)", pct(((val.get("scenarios") or {}).get("base") or {}).get("drivers", {}).get("organic_growth")), "regla pre-registrada"],
        ["Orgánico histórico", pct(cr.get("historico_organico")), f"{cr.get('anos_historico') or 0} años"],
        ["Tasa base del tramo: p25 / p50 / p75", f"{pct(rate.get('p25'))} / {pct(rate.get('p50'))} / {pct(rate.get('p75'))}",
         f"tramo {cr.get('tramo_tasa_base') or 'N/D'}, n = {rate.get('n', 'N/D')}, crecimiento a 5 años"],
    ] + [[f"Guía de la empresa: {g['metric']} {g['period']}", _guidance_value(g, g["base"]), g.get("document") or ""]
         for g in ctx.guidance if g.get("metric") == "revenue"]}
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
    figure_markers: dict[str, str] = field(default_factory=dict)  # fuente.N: cifra literal de un documento
    guard: dict[str, Any] = field(default_factory=dict)  # FigureGuard.as_dict() de las secciones finales


def thesis_fingerprint(ctx: ThesisContext) -> str:
    blob = json.dumps({"v": THESIS_V2_VERSION, "val": ctx.valuation.get("fingerprint"),
                       "markers": sorted(thesis_markers(ctx)), "optional": sorted(ctx.optional),
                       "passages": [hashlib.sha256((p["text"] or "").encode()).hexdigest()[:12] for p in ctx.passages]},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def active_sections(ctx: ThesisContext) -> list[tuple[str, str, str, tuple[str, ...]]]:
    return [s for s in SECTIONS if s[0] not in OPTIONAL or s[0] in ctx.optional]


# Nombres de normas, formularios y anexos SEC: no son cifras («IFRS 16», «NIC 36», «ASC 842», «Form 20-F», «Pilar 2», «EX-99.1»).
_NAMES = re.compile(r"\b(?:IFRS|NIIF|IAS|NIC|ASC|ASU|US\s?GAAP\s?ASC|Pilar|Pillar|Basilea|Basel|Solvencia|Solvency|"
                    r"Form|formulario|Regla|Rule|Item|Nivel|Level|Tier)\s?\d+(?:b\d?-\d+)?(?:[-–]\d+)?[A-Z]?\b"
                    r"|\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b"
                    r"|\b\d{1,2}-[KFQ]\b|\b(?:20|40|10|6|8)-[A-Z]\b|\bS&P\s?500\b|\bQ[1-4]\b|\bH[12]\b|\b[1-4]T\b"
                    # Reglas, anexos y apartados de la SEC: «plan 10b5-1», «Rule 10b-5», «EX-99.1», «Exhibit 10.2»,
                    # «Section 16», «Schedule 13D», «DEF 14A», «S-3», «Form 144»: son nombres, no cifras.
                    r"|\b10b5-1\b|\b10b-5\b|\bEX-\d+(?:\.\d+)?\b|\b13[DFG](?:/A)?\b|\bDEF\s?14A\b|\b[SF]-[1-4]\b"
                    r"|\b(?:Exhibit|Anexo|Section|Secci[oó]n|Schedule|Art[ií]culo|Article|Part|Parte)\s?\d+[A-Z]?(?:\.\d+)?\b", re.I)


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


# ------------------------------------------------------------------ que no se pierda ningún dato

_FIG = re.compile(r"[-−+]?[$€£]?\d[\d.,]*(?:\s*(?:%|pp\b|M\$|M€|M£|M\b|\$|€|£|x\b|veces\b))?")
_PROTECT = re.compile(r"\{\{\s*[a-z0-9_.]+\s*\}\}|\x01.\x01")


def _fig_key(text: str) -> str:
    """Forma comparable de una cifra tal como se escribe: «−12,7 %» y «-12,7%» son la misma."""
    t = (text or "").strip().replace("−", "-").replace("\u00a0", " ").replace(" ", "")
    return t.rstrip(".,;:")


def _fig_number(text: str) -> str:
    return re.sub(r"[^\d.,\-]", "", _fig_key(text)).strip(".,")


def _float_es(num: str) -> float | None:
    try:
        return float(num.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _float_en(num: str) -> float | None:
    try:
        return float(num.replace(",", ""))
    except ValueError:
        return None


def _evidence_figure(fig: str, passages: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """El pasaje que trae esa cifra tal cual (o el mismo valor en notación inglesa), si alguno la trae.

    Una cifra corta y sin unidad («5», «12») no basta: aparece en cualquier texto. Hace falta unidad
    (%, $, M, x) o al menos tres dígitos.
    """
    num = _fig_number(fig)
    digits = sum(ch.isdigit() for ch in num)
    unit = re.search(r"(%|pp|\$|€|£|M|x)$", _fig_key(fig))
    if not num or (digits < 3 and not unit):
        return None
    value = _float_es(num.lstrip("-"))
    for p in passages:
        text = str(p.get("text") or "")
        for m in re.finditer(r"(?<![\d.,])\d[\d.,]*\d|(?<![\d.,])\d", text):
            tok = m.group(0)
            if tok == num.lstrip("-"):
                return p
            if value is not None and digits >= 2 and value in (_float_en(tok), _float_es(tok)):
                return p
    return None


@dataclass
class FigureGuard:
    """Qué hizo la guardia con las cifras libres de una sección: enlazadas o quitadas (nunca en silencio)."""

    to_markers: list[dict[str, str]] = field(default_factory=list)  # cifra = valor de un marcador del código
    to_sources: list[dict[str, Any]] = field(default_factory=list)  # cifra literal de un documento citado
    removed: list[str] = field(default_factory=list)  # sin fuente: quitadas
    unquoted: list[str] = field(default_factory=list)  # citas no literales que dejan de ir entre comillas

    def as_dict(self) -> dict[str, Any]:
        return {"a_marcador": len(self.to_markers), "a_documento": len(self.to_sources),
                "quitadas": len(self.removed), "detalle_documento": self.to_sources[:20],
                "detalle_quitadas": self.removed[:40], "citas_no_literales": len(self.unquoted),
                "detalle_citas": [q[:160] for q in self.unquoted[:10]]}


def recover_figures(text: str, markers: Mapping[str, str], passages: Sequence[Mapping[str, Any]],
                    extra: dict[str, str], guard: FigureGuard) -> str:
    """Convierte en marcador cada cifra libre que ya tiene fuente, en vez de borrarla.

    - Si la cifra es exactamente el valor de un marcador del código, se escribe ese marcador.
    - Si aparece literal en un pasaje citado, se crea un marcador ``fuente.N`` con la cifra tal cual y su
      documento (``extra`` y ``guard.to_sources``).
    Lo demás no se toca aquí: lo verá la guardia como cifra sin marcador.
    """
    by_value: dict[str, str] = {}
    for key, value in markers.items():
        if value and any(ch.isdigit() for ch in str(value)) and _FIG.fullmatch(str(value).strip()):
            by_value.setdefault(_fig_key(str(value)), key)
    sourced = {v: k for k, v in extra.items()}
    work, kept = _masked(text)

    def swap(m: re.Match[str]) -> str:
        raw = m.group(0)
        if not any(ch.isdigit() for ch in raw):
            return raw
        trail = raw[len(raw.rstrip()):]
        fig = raw.strip()
        key = by_value.get(_fig_key(fig))
        if key is not None:
            guard.to_markers.append({"cifra": fig, "marcador": key})
            return "{{" + key + "}}" + trail
        if free_numbers(fig) == []:  # año, fecha o formulario: no es cifra
            return raw
        p = _evidence_figure(fig, passages)
        if p is None:
            return raw
        nkey = sourced.get(fig)
        if nkey is None:
            nkey = f"fuente.{len(extra) + 1}"
            extra[nkey] = fig
            sourced[fig] = nkey
            guard.to_sources.append({"cifra": fig, "marcador": nkey, "documento": p.get("document"),
                                     "url": p.get("url"), "fecha": p.get("date")})
        return "{{" + nkey + "}}" + trail

    pieces, last = [], 0
    for prot in _PROTECT.finditer(work):
        pieces.append(_FIG.sub(swap, work[last:prot.start()]))
        pieces.append(prot.group(0))
        last = prot.end()
    pieces.append(_FIG.sub(swap, work[last:]))
    return _unmasked("".join(pieces), kept)


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
    resume: dict[str, str] = {}
    if cached and cached.get("fingerprint") == fp and cached.get("sections") and cached.get("status") == "error":
        # Una tesis que se cortó a medias (fallo del modelo en la 2.ª llamada) NO se sirve como hecha:
        # se reanuda con lo ya aceptado y solo se piden las secciones que faltan.
        resume = {k: v for k, v in dict(cached["sections"]).items() if v}
    elif cached and cached.get("fingerprint") == fp and cached.get("sections") and not (
            cached.get("status") == "stripped" and "guard" not in cached):
        # Una tesis «stripped» de la guardia anterior (borraba cifras con fuente sin decirlo) se rehace.
        return ThesisResult(status="cached", sections=dict(cached["sections"]), fingerprint=fp,
                            probability_choice=cached.get("probability_choice"),
                            probability_reason=cached.get("probability_reason"),
                            figure_markers=dict(cached.get("figure_markers") or {}),
                            guard=dict(cached.get("guard") or {}))
    markers = thesis_markers(ctx)
    out = ThesisResult(status="ok", fingerprint=fp)
    guards: dict[str, FigureGuard] = {}
    if resume and cached:
        out.probability_choice = cached.get("probability_choice")
        out.probability_reason = cached.get("probability_reason")
        out.figure_markers.update(dict(cached.get("figure_markers") or {}))
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
        "consenso_de_analistas": ({"estimaciones_citadas": ctx.analysts, "precios_objetivo": ctx.price_targets,
                                   "nota": "cita cada cifra con su marcador analistas.*; no promedies tú"}
                                  if ctx.analysts or ctx.price_targets
                                  else "no hay todavía rangos de analistas guardados para esta empresa: dilo así"),
        "insiders": ctx.insiders and {"ventanas": ctx.insiders.get("windows"), "nota": "cita con los marcadores insiders.*"},
    }
    from app.services.expert_team.quote_check import evidence_texts, non_literal, unquote_non_literal

    evidence = evidence_texts(ctx.passages, ctx.guidance, ctx.analysts, ctx.price_targets, ctx.insiders)

    def rendered(text: str) -> str:
        return render({"x": text}, {**markers, **out.figure_markers})["x"]

    stripped = False
    for part in ("a", "b"):
        secs = [s for s in active_sections(ctx) if s[2] == part and s[0] not in resume]
        out.sections.update({s[0]: resume[s[0]] for s in active_sections(ctx) if s[2] == part and s[0] in resume})
        if not secs:
            continue
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
                # Antes de juzgar: cada cifra que ya tiene fuente (marcador del código o pasaje citado) se
                # convierte en marcador; solo cuenta como «sin marcador» lo que no tiene fuente.
                guards[k] = FigureGuard()
                body = recover_figures(body, markers, ctx.passages, out.figure_markers, guards[k])
                loose = loose_numbers(body)
                if loose:
                    issues.append(f"{k}: números sin marcador: {', '.join(loose[:6])}")
                not_literal = non_literal(body, evidence, rendered)
                if not_literal:
                    issues.append(f"{k}: citas que no están literales en los pasajes (cópialas tal cual, en su idioma "
                                  f"original, con la traducción al lado; o escríbelas sin comillas): "
                                  + "; ".join(f"«{q[:90]}»" for q in not_literal[:3]))
                bad = unknown_markers(body, {**markers, **out.figure_markers})
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
            known = {**markers, **out.figure_markers}
            for k, v in pending.items():
                if k in accepted:
                    continue
                gone = loose_numbers(v)
                g = guards.setdefault(k, FigureGuard())
                g.removed.extend(f"{k}: {n}" for n in gone)
                v, touched = unquote_non_literal(v, evidence, rendered)
                g.unquoted.extend(touched)
                out.sections[k] = MARKER.sub(lambda mm: mm.group(0) if mm.group(1) in known else "", strip_loose(v))
    _finish_guard(out, guards, ctx.ticker)
    if not out.sections:
        out.status = "rejected"
    elif stripped:
        out.status = "stripped"
    return out


def _finish_guard(out: ThesisResult, guards: Mapping[str, FigureGuard], ticker: str) -> None:
    """Resumen de la guardia de las secciones finales; los marcadores fuente.N que no se usan, fuera."""
    used = {m.group(1) for v in out.sections.values() for m in MARKER.finditer(v or "")}
    out.figure_markers = {k: v for k, v in out.figure_markers.items() if k in used}
    total = FigureGuard()
    for k in out.sections:
        g = guards.get(k)
        if g is None:
            continue
        total.to_markers.extend(g.to_markers)
        total.to_sources.extend(s for s in g.to_sources if s["marcador"] in out.figure_markers)
        total.removed.extend(g.removed)
        total.unquoted.extend(g.unquoted)
    seen: set[str] = set()
    total.to_sources = [s for s in total.to_sources if not (s["marcador"] in seen or seen.add(s["marcador"]))]
    out.guard = total.as_dict()
    if total.unquoted:
        logger.info("tesis v2 %s: %d citas no literales sin comillas", ticker, len(total.unquoted))
    if total.removed:
        logger.info("tesis v2 %s: %d cifras sin fuente quitadas: %s", ticker, len(total.removed),
                    "; ".join(total.removed[:20]))


def guard_warning(guard: Mapping[str, Any] | None) -> str | None:
    """Línea visible de la guardia de cifras: cuántas se enlazaron a su fuente y cuáles se quitaron."""
    if not guard:
        return None
    linked = int(guard.get("a_marcador") or 0) + int(guard.get("a_documento") or 0)
    removed = list(guard.get("detalle_quitadas") or [])
    n_removed = int(guard.get("quitadas") or 0)
    n_quotes = int(guard.get("citas_no_literales") or 0)
    if not linked and not n_removed and not n_quotes:
        return None
    text = f"Guardia de cifras: {linked} cifras del texto enlazadas a su dato o documento"
    if n_removed:
        sample = ", ".join(r.split(": ", 1)[-1] for r in removed[:6])
        text += f"; {n_removed} quitadas por no tener fuente ({sample})"
    else:
        text += "; ninguna quitada"
    if n_quotes:
        text += f"; {n_quotes} citas que no estaban literales en el documento pasan a estilo indirecto"
    return text + "."


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
        from app.llm.factory import create_llm_provider
        from app.services.expert_team.service import provider_reasoner

        # Cada parte pide hasta 24.000 tokens: con el plazo general (120 s por petición) el proveedor la corta
        # a mitad y la tesis sale en error (POOL: 120,1 s y fuera). Plazo propio de esta llamada larga, y gasto
        # anotado con commit: sin él la sesión queda «idle in transaction» durante la llamada y Postgres la corta.
        reasoner = provider_reasoner(
            create_llm_provider(timeout_seconds=CALL_TIMEOUT_SECONDS, total_timeout_seconds=CALL_TOTAL_TIMEOUT_SECONDS),
            db=db, commit_usage=True, temperature=0.0,
        )
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
        "figure_markers": res.figure_markers, "guard": res.guard,
    }
    markers = {**res.figure_markers, **markers}
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
    markers = {**dict(doc.get("figure_markers") or {}), **markers}
    rendered = render(doc.get("sections") or {}, markers)
    warnings = list(ctx.valuation.get("warnings") or [])
    line = guard_warning(doc.get("guard"))
    if line:
        warnings.append(line)
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
        "warnings": warnings,
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
