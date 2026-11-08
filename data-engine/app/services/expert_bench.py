"""Benchmark determinista del equipo de expertos de la tesis (rigor, estabilidad, ablación, juez, coste, previsiones).

Solo métricas y utilidades puras: no llama al modelo ni escribe en la base. El script
``scripts/expert_bench.py`` las usa sobre las tesis guardadas y sobre corridas nuevas.

Límite de método, a propósito: NO se hace backtest de la prosa del modelo contra rentabilidades
pasadas. El modelo conoce lo que pasó después (look-ahead), así que un acierto «histórico» de su
texto no mide nada. La única prueba honesta de valor predictivo es el registro de previsiones con
fecha (``forecast_record``) puntuado a 1 y 3 años (``score_forecast``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

BENCH_VERSION = "expert-bench-1"

# ------------------------------------------------------------------------------------------- tipos y método

#: Tipos de empresa y lo que el método debe usar. ``engine`` = métodos del motor que valen para el tipo;
#: ``text`` = palabras que la tesis debe tratar (al menos una) cuando el motor no tiene el método propio.
TYPE_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "aseguradora": {
        "engine": ("tir_pb",),
        "partial": (),
        "kinds": ("insurer",),
        "text": ("valor contable", "p/vc", "roe", "float", "ratio combinado"),
    },
    "reit": {
        "engine": ("tir_ffo",),
        "partial": (),
        "kinds": ("real_estate",),
        "text": ("ffo", "affo", "nav", "valor de los activos"),
    },
    "gestora": {
        "engine": ("tir_fre", "tir_fre_de"),
        "partial": ("tir_pb",),
        "kinds": ("holding",),
        "text": ("comisiones", "fee-related", "fre", "beneficio distribuible", "distributable"),
    },
    "holding": {
        "engine": ("tir_pb", "tir_nav", "sotp"),
        "partial": (),
        "kinds": ("holding",),
        "text": ("nav", "suma de partes", "descuento"),
    },
    "quemadora": {
        "engine": ("caja_runway", "sotp"),
        "partial": (),
        "kinds": ("pre_revenue",),
        "text": ("caja", "meses", "runway", "tasa base", "dilución"),
    },
    "operativa": {
        "engine": ("tir_ev_ebitda", "tir_per"),
        "partial": (),
        "kinds": ("operating",),
        "text": ("tir",),
    },
}

#: Clasificación de referencia (la del encargo del 8-nov-2026) de la lista de Nico; es la etiqueta
#: del conjunto de prueba, no una regla de la app.
REFERENCE_TYPES: dict[str, str] = {
    "CB": "aseguradora",
    "FFH.TO": "aseguradora",
    "FFH": "aseguradora",
    "CPT": "reit",
    "KKR": "gestora",
    "BN": "gestora",
    "CGEO.L": "holding",
    "RXRX": "quemadora",
    "NAUT": "quemadora",
    "ABCL": "quemadora",
    "IBRX": "quemadora",
    "ASTS": "quemadora",
    "HIMS": "quemadora",
    "POOL": "operativa",
    "UNH": "operativa",
    "AAPL": "operativa",
    "ERF.PA": "operativa",
    "META": "operativa",
    "AMZN": "operativa",
    "TSLA": "operativa",
    "FRPH": "operativa",
    "CNQ": "operativa",
    "GOOGL": "operativa",
    "TSM": "operativa",
    "AIR.PA": "operativa",
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.casefold().split())


def method_fit(
    company_type: str | None, chosen: str | None, text: str = "", kind: str | None = None
) -> dict[str, Any]:
    """¿Clasifica la app bien el tipo, usa el motor el método del tipo y lo trata la tesis en el texto?

    ``ok`` = método del tipo; ``partial`` = un método vecino (p. ej. P/VC en una gestora que pide FRE + DE).
    """
    rules = TYPE_RULES.get(company_type or "")
    if rules is None:
        return {
            "type": company_type,
            "kind": kind,
            "chosen": chosen,
            "kind_ok": None,
            "engine_ok": None,
            "partial": None,
            "text_ok": None,
            "ok": None,
        }
    engine_ok = (chosen or "") in rules["engine"]
    partial = not engine_ok and (chosen or "") in rules["partial"]
    low = _fold(text)
    hits = [w for w in rules["text"] if _fold(w) in low]
    return {
        "type": company_type,
        "kind": kind,
        "chosen": chosen,
        "kind_ok": None if kind is None else kind in rules["kinds"],
        "engine_ok": engine_ok,
        "partial": partial,
        "text_ok": bool(hits),
        "text_hits": hits,
        "ok": engine_ok,
    }


# ------------------------------------------------------------------------------------------- cifras libres

def free_numbers_by_section(sections: Mapping[str, str]) -> dict[str, list[str]]:
    """Cifras sin marcador por sección, con el mismo detector que usa la tesis v2."""
    from app.services.expert_team.thesis_v2 import loose_numbers

    out: dict[str, list[str]] = {}
    for key, body in sections.items():
        found = loose_numbers(body or "")
        if found:
            out[key] = found
    return out


_PROBLEM = re.compile(
    r"^(?P<section>[a-z_]+): (?P<kind>números sin marcador|marcadores que no existen): (?P<items>.*)$"
)


def classify_problems(problems: Iterable[str]) -> dict[str, Any]:
    """Problemas que el guardián anotó en los intentos: cifras libres y marcadores inventados.

    Los nombres de norma o formulario (``plan 10b5-1``, ``Form 4``) ya no llegan aquí como cifras: el guardián de la
    tesis v2 los enmascara desde #4861, así que no hay falsos positivos que descontar.
    """
    free = unknown = 0
    sections: Counter[str] = Counter()
    for p in problems or ():
        m = _PROBLEM.match(str(p))
        if not m:
            continue
        items = [i.strip() for i in m.group("items").split(", ") if i.strip()]
        sections[m.group("section")] += 1
        if m.group("kind") == "marcadores que no existen":
            unknown += len(items)
            continue
        free += len(items)
    return {
        "free_numbers": free,
        "unknown_markers": unknown,
        "sections_flagged": dict(sections),
    }


# ------------------------------------------------------------------------------------------- citas

_QUOTE = re.compile(r"[«“\"]([^«»“”\"]{25,600})[»”\"]")


_ATTRIBUTION = re.compile(
    r"\b(?:seg[uú]n|dice|dicen|afirma|escribe|reconoce|describe|explica|advierte|se[nñ]ala|admite|declara|"
    r"palabras|textual|literalmente|cita|10-K|10-Q|20-F|40-F|informe|memoria|documento|la compa[nñ][ií]a|"
    r"la empresa|la direcci[oó]n|consejero|presidente|define|se define|denomina)\b",
    re.I,
)


def extract_quotes(text: str) -> list[str]:
    return [q.strip() for q in _QUOTE.findall(text or "")]


def extract_attributed_quotes(text: str, window: int = 90) -> list[str]:
    """Citas presentadas como palabras de una fuente («según el 10-K, …», «la empresa describe …»), no las
    comillas retóricas del propio redactor."""
    out = []
    for m in _QUOTE.finditer(text or ""):
        before = (text or "")[max(0, m.start() - window) : m.start()]
        if _ATTRIBUTION.search(before):
            out.append(m.group(1).strip())
    return out


def quote_in_evidence(quote: str, evidence: Iterable[str]) -> bool:
    """La cita aparece literal (salvo mayúsculas, acentos, comillas y espacios) en alguna evidencia."""
    q = _fold(quote).strip(" .…")
    if not q:
        return True
    q = q.replace("...", "…")
    pieces = [p.strip(" .") for p in q.split("…") if p.strip(" .")]  # una elipsis parte la cita
    hay = [_fold(e) for e in evidence]
    return all(any(piece in h for h in hay) for piece in pieces)


_ES_WORDS = (" de ", " la ", " que ", " los ", " las ", " del ", " nuestro", " nuestra", " para ", " una ")
_EN_WORDS = (" the ", " and ", " of ", " our ", " to ", " with ")


def looks_spanish(text: str) -> bool:
    low = f" {_fold(text)} "
    return sum(low.count(w) for w in _ES_WORDS) > sum(low.count(w) for w in _EN_WORDS)


def check_quotes(quotes: Iterable[str], evidence: Sequence[str]) -> dict[str, Any]:
    """Citas entre comillas que no están literales en la evidencia; ``translated`` = la cita está en español y
    la evidencia en inglés (una traducción presentada como cita textual)."""
    qs = [q for q in quotes if q]
    missing = [q for q in qs if not quote_in_evidence(q, evidence)]
    english_evidence = bool(evidence) and not looks_spanish(" ".join(e[:400] for e in evidence[:20]))
    translated = [q for q in missing if english_evidence and looks_spanish(q)]
    return {
        "quotes": len(qs),
        "not_literal": len(missing),
        "translated": len(translated),
        "examples": [m[:160] for m in missing[:3]],
    }


def quotes_in_json(value: Any, keys: tuple[str, ...] = ("quote", "anchor_quote", "cita")) -> list[str]:
    """Campos de cita de una respuesta JSON (valorador SOTP, mezcla de analistas)."""
    out: list[str] = []
    if isinstance(value, Mapping):
        for k, v in value.items():
            if k in keys and isinstance(v, str):
                out.append(v)
            else:
                out.extend(quotes_in_json(v, keys))
    elif isinstance(value, list):
        for v in value:
            out.extend(quotes_in_json(v, keys))
    return out


def evidence_strings(payload: Any) -> list[str]:
    """Todos los textos de una carga enviada al modelo (la evidencia contra la que se comprueba una cita)."""
    out: list[str] = []
    if isinstance(payload, Mapping):
        for v in payload.values():
            out.extend(evidence_strings(v))
    elif isinstance(payload, list):
        for v in payload:
            out.extend(evidence_strings(v))
    elif isinstance(payload, str) and len(payload) >= 20:
        out.append(payload)
    return out


# ------------------------------------------------------------------------------------------- fuente de las cifras


def _rel(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if b == 0:
        return 0.0 if a == 0 else math.inf
    return abs(a - b) / abs(b)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def source_check(valuation: Mapping[str, Any], tol: float = 0.005) -> dict[str, Any]:
    """Precio, acciones diluidas y deuda neta del punto de partida frente a la cifra de su cita.

    Las acciones del punto de partida van en millones y la cita en unidades; la deuda neta se rehace con
    las citas de deuda y caja (más arrendamientos, híbridos y minoritarios, que el motor suma aparte).
    """
    sp = valuation.get("starting_point") or {}
    cites = valuation.get("citations") or {}
    out: dict[str, Any] = {}
    price_c = _num((cites.get("price") or {}).get("value"))
    out["price"] = {
        "value": _num(sp.get("price")),
        "cited": price_c,
        "rel": _rel(_num(sp.get("price")), price_c),
        "document": (cites.get("price") or {}).get("document"),
    }
    sh_c = _num((cites.get("shares") or {}).get("value"))
    sh = _num(sp.get("shares_diluted"))
    out["shares"] = {
        "value": sh,
        "cited": sh_c,
        "rel": _rel(sh * 1e6 if sh is not None else None, sh_c),
        "metric": (cites.get("shares") or {}).get("metric"),
        "accession": (cites.get("shares") or {}).get("accession"),
    }
    debt_c = _num((cites.get("total_debt") or {}).get("value"))
    cash_c = _num((cites.get("cash_and_equivalents") or {}).get("value"))
    sti_c = _num((cites.get("short_term_investments") or {}).get("value")) or 0.0
    extra = sum(_num(sp.get(k)) or 0.0 for k in ("leases", "hybrids", "minorities"))
    # Solo se reconstruye con deuda Y caja citadas: con una sola, la otra sería un 0 inventado (N/D con motivo).
    rebuilt = None
    rebuilt_missing = [label for label, x in (("deuda", debt_c), ("caja", cash_c)) if x is None]
    if not rebuilt_missing and debt_c is not None and cash_c is not None:
        rebuilt = (debt_c - cash_c - sti_c) / 1e6 + extra
    nd = _num(sp.get("net_debt"))
    out["net_debt"] = {
        "value": nd,
        "rebuilt_from_citations": rebuilt,
        "rebuilt_missing": rebuilt_missing,
        "abs_diff_m": None if nd is None or rebuilt is None else abs(nd - rebuilt),
        "rel_to_mcap": None
        if nd is None or rebuilt is None or not _num(sp.get("market_cap"))
        else abs(nd - rebuilt) / abs(_num(sp.get("market_cap")) or 1.0),
    }
    ok = []
    for key in ("price", "shares"):
        r = out[key]["rel"]
        ok.append(r is not None and r <= tol)
    r = out["net_debt"]["rel_to_mcap"]
    ok.append(r is not None and r <= tol)
    out["ok"] = {"price": ok[0], "shares": ok[1], "net_debt": ok[2]}
    return out


# ------------------------------------------------------------------------------------------- secciones y kill switches


def sections_filled(sections: Mapping[str, str], keys: Sequence[str], min_chars: int = 400) -> dict[str, Any]:
    empty = [k for k in keys if len((sections.get(k) or "").strip()) < min_chars]
    return {"expected": len(keys), "filled": len(keys) - len(empty), "short_or_empty": empty}


_THRESHOLD = re.compile(r"[<>≤≥]=?\s*[-−+]?\d[\d.,]*\s*(?:%|x|veces|m|meses|años)?", re.I)


def kill_switch_is_threshold(switch: Mapping[str, Any]) -> bool:
    """Un kill switch vale si nombra una métrica y un umbral numérico con comparador («< 1,8 %»)."""
    metric = str(switch.get("metric") or "").strip()
    threshold = str(switch.get("threshold") or "")
    return bool(metric) and bool(_THRESHOLD.search(threshold))


def kill_switch_report(switches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    bad = [str(s.get("key") or s.get("metric")) for s in switches if not kill_switch_is_threshold(s)]
    return {"count": len(switches), "as_threshold": len(switches) - len(bad), "not_threshold": bad}


# ------------------------------------------------------------------------------------------- estabilidad


def agreement(values: Sequence[Any]) -> float | None:
    """Parte de las corridas que coincide con la moda (1,0 = todas iguales)."""
    vals = [json.dumps(v, sort_keys=True, default=str) for v in values]
    if not vals:
        return None
    return Counter(vals).most_common(1)[0][1] / len(vals)


def jaccard(a: Iterable[Any], b: Iterable[Any]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def mean_pairwise_jaccard(sets: Sequence[Iterable[Any]]) -> float | None:
    items = [set(s) for s in sets]
    pairs = [(i, j) for i in range(len(items)) for j in range(i + 1, len(items))]
    if not pairs:
        return None
    return sum(jaccard(items[i], items[j]) for i, j in pairs) / len(pairs)


def markers_used(text: str) -> set[str]:
    from app.services.expert_team.sotp_narrative import MARKER

    return {m.group(1) for m in MARKER.finditer(text or "")}


def relative_spread(values: Sequence[float | None]) -> float | None:
    """(máx − mín) / |mediana| de una cifra repetida; 0 = idéntica en todas las corridas."""
    xs = sorted(v for v in values if v is not None)
    if len(xs) < 2:
        return None
    med = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
    if med == 0:
        return 0.0 if xs[0] == xs[-1] else math.inf
    return (xs[-1] - xs[0]) / abs(med)


# ------------------------------------------------------------------------------------------- juez ciego

JUDGE_RUBRIC = (
    "Eres el comité de inversión de un inversor value a largo plazo. Compara dos informes (A y B) sobre la "
    "misma empresa. No sabes quién los escribió ni cómo; no lo adivines. Puntúa cada criterio de 0 a 5:\n"
    "1. rigor: cada cifra con su fuente; nada inventado; método de valoración adecuado al tipo de empresa.\n"
    "2. tesis: dice con claridad por qué la acción vale más o menos que el precio, y qué hay que creer.\n"
    "3. riesgos: riesgos concretos de esta empresa y kill switches medibles (métrica y umbral).\n"
    "4. utilidad: un inversor puede decidir con él (escenarios, qué vigilar, qué descuenta el precio).\n"
    "5. claridad: se lee bien, sin relleno ni repeticiones.\n"
    'La longitud no es un mérito. Responde SOLO con JSON: {"A": {"rigor": n, "tesis": n, "riesgos": n, '
    '"utilidad": n, "claridad": n}, "B": {...}, "preferido": "A" | "B" | "empate", "motivo": str}'
)
CRITERIA = ("rigor", "tesis", "riesgos", "utilidad", "claridad")


def judge_user_message(ticker: str, text_a: str, text_b: str, limit: int = 90000) -> str:
    return json.dumps({"empresa": ticker, "A": text_a[:limit], "B": text_b[:limit]}, ensure_ascii=False)


def parse_judge(text: str) -> dict[str, Any] | None:
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if not 0 <= start < end:
        return None
    try:
        data = json.loads(text[start : end + 1], strict=False)
    except ValueError:
        return None
    pref = str(data.get("preferido") or "").strip().upper()
    pref = {"A": "A", "B": "B"}.get(pref, "empate")
    scores = {}
    for side in ("A", "B"):
        s = data.get(side) or {}
        vals = [_num(s.get(c)) for c in CRITERIA]
        scores[side] = sum(v for v in vals if v is not None) / max(1, sum(v is not None for v in vals))
    return {
        "preferido": pref,
        "score_A": scores["A"],
        "score_B": scores["B"],
        "motivo": str(data.get("motivo") or "")[:300],
    }


def combine_orders(first: Mapping[str, Any] | None, swapped: Mapping[str, Any] | None) -> dict[str, Any]:
    """Une las dos pasadas (X como A, luego X como B) y cancela el sesgo de posición.

    Devuelve la preferencia por X: +1 si gana en las dos órdenes, −1 si pierde en las dos, 0 si empata o si
    el juez cambia de opinión al cambiar el orden (sesgo de posición), y la diferencia media de nota X − Y.
    """
    if not first or not swapped:
        return {"pref_x": None, "consistent": None, "score_diff": None}
    x_first = {"A": 1, "B": -1}.get(first["preferido"], 0)
    x_swapped = {"B": 1, "A": -1}.get(swapped["preferido"], 0)
    consistent = x_first == x_swapped
    pref = x_first if consistent else 0
    diff = ((first["score_A"] - first["score_B"]) + (swapped["score_B"] - swapped["score_A"])) / 2
    return {"pref_x": pref, "consistent": consistent, "score_diff": diff}


def sign_test_p(wins: int, losses: int) -> float | None:
    """p bilateral de la prueba de signos (empates fuera). Con N pequeña casi nunca baja de 0,05."""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


# ------------------------------------------------------------------------------------------- coste


@dataclass
class CallRecord:
    role: str
    seconds: float
    input_tokens: int
    output_tokens: int
    cost_eur: float
    ok: bool = True


def cost_by_role(calls: Iterable[CallRecord | Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for c in calls:
        d = c if isinstance(c, Mapping) else c.__dict__
        r = out.setdefault(
            str(d["role"]),
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "cost_eur": 0.0},
        )
        r["calls"] += 1
        r["input_tokens"] += int(d.get("input_tokens") or 0)
        r["output_tokens"] += int(d.get("output_tokens") or 0)
        r["seconds"] += float(d.get("seconds") or 0.0)
        # Una llamada sin coste registrado no cuesta 0: se cuenta aparte y el total queda como cota inferior.
        cost = d.get("cost_eur")
        if cost is None:
            r["cost_unknown_calls"] = r.get("cost_unknown_calls", 0) + 1
        else:
            r["cost_eur"] += float(cost)
    return out


# ------------------------------------------------------------------------------------------- previsiones

FORECAST_VERSION = "forecast-log-1"
HORIZONS = (1, 3)


def forecast_record(
    *,
    ticker: str,
    as_of: date,
    price: float,
    currency: str,
    scenarios: Mapping[str, Any],
    weighted: Mapping[str, Any] | None,
    method: str | None,
    probability_choice: str | None,
    kill_switches: Sequence[Mapping[str, Any]],
    claims: Sequence[str],
    thesis_fingerprint: str | None,
    commit: str | None,
) -> dict[str, Any]:
    """Una previsión con fecha. Lo que se puntúa después son las TIR y los kill switches, no la prosa."""

    def irr(key: str, horizon: str) -> float | None:
        return _num((((scenarios.get(key) or {}).get("horizons") or {}).get(horizon) or {}).get("irr"))

    rec = {
        "v": FORECAST_VERSION,
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "price": price,
        "currency": currency,
        "method": method,
        "probability_choice": probability_choice,
        "irr": {h: {k: irr(k, h) for k in ("bear", "base", "bull")} for h in ("5", "10")},
        "irr_weighted": {h: _num((weighted or {}).get(h)) for h in ("5", "10")},
        "kill_switches": [
            {k: s.get(k) for k in ("key", "metric", "threshold", "current", "status")} for s in kill_switches
        ],
        "claims": [c[:400] for c in claims][:5],
        "thesis_fingerprint": thesis_fingerprint,
        "commit": commit,
        "score_at": {
            f"{h}y": date(as_of.year + h, as_of.month, min(as_of.day, 28)).isoformat() for h in HORIZONS
        },
    }
    rec["id"] = hashlib.sha256(
        json.dumps({k: rec[k] for k in ("ticker", "as_of", "price", "irr")}, sort_keys=True).encode()
    ).hexdigest()[:16]
    return rec


def score_forecast(
    record: Mapping[str, Any], *, horizon_years: int, price_then: float, dividends_per_share: float = 0.0
) -> dict[str, Any]:
    """Rentabilidad real anualizada (con dividendos) frente a la TIR bajista/base/alcista prevista a 5 años.

    La TIR es a 5 y 10 años; a 1 y 3 años se compara con la de 5 años como ritmo anual, y se dice así.
    """
    p0 = float(record["price"])
    total = (price_then + dividends_per_share) / p0
    realized = total ** (1 / horizon_years) - 1 if total > 0 else -1.0
    irr5 = (record.get("irr") or {}).get("5") or {}
    bear, base, bull = irr5.get("bear"), irr5.get("base"), irr5.get("bull")
    inside = None if bear is None or bull is None else (min(bear, bull) <= realized <= max(bear, bull))
    return {
        "ticker": record["ticker"],
        "as_of": record["as_of"],
        "horizon_years": horizon_years,
        "realized_annual": realized,
        "base_irr5": base,
        "error_vs_base": None if base is None else realized - base,
        "inside_bear_bull": inside,
        "compared_with": "TIR a 5 años como ritmo anual",
    }


def summarize_scores(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    xs = [s for s in scores if s.get("base_irr5") is not None]
    if not xs:
        return {"n": 0}
    errs = [s["error_vs_base"] for s in xs]
    inside = [s["inside_bear_bull"] for s in xs if s["inside_bear_bull"] is not None]
    return {
        "n": len(xs),
        "mean_error_vs_base": sum(errs) / len(errs),
        "share_inside_bear_bull": (sum(inside) / len(inside)) if inside else None,
        "rank_ic": rank_ic([s["base_irr5"] for s in xs], [s["realized_annual"] for s in xs]),
    }


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def rank_ic(pred: Sequence[float], real: Sequence[float]) -> float | None:
    if len(pred) < 3:
        return None
    rp, rr = _ranks(pred), _ranks(real)
    mp, mr = sum(rp) / len(rp), sum(rr) / len(rr)
    cov = sum((a - mp) * (b - mr) for a, b in zip(rp, rr, strict=True))
    vp = math.sqrt(sum((a - mp) ** 2 for a in rp))
    vr = math.sqrt(sum((b - mr) ** 2 for b in rr))
    return None if vp == 0 or vr == 0 else cov / (vp * vr)


__all__ = [
    "BENCH_VERSION",
    "CRITERIA",
    "FORECAST_VERSION",
    "JUDGE_RUBRIC",
    "REFERENCE_TYPES",
    "TYPE_RULES",
    "CallRecord",
    "agreement",
    "check_quotes",
    "classify_problems",
    "combine_orders",
    "cost_by_role",
    "evidence_strings",
    "extract_attributed_quotes",
    "extract_quotes",
    "looks_spanish",
    "forecast_record",
    "free_numbers_by_section",
    "jaccard",
    "judge_user_message",
    "kill_switch_is_threshold",
    "kill_switch_report",
    "markers_used",
    "mean_pairwise_jaccard",
    "method_fit",
    "parse_judge",
    "quote_in_evidence",
    "quotes_in_json",
    "rank_ic",
    "relative_spread",
    "score_forecast",
    "sections_filled",
    "sign_test_p",
    "source_check",
    "summarize_scores",
]
