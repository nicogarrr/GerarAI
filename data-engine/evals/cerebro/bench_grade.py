"""Graders deterministas del benchmark de Cerebro (bench_v1).

Funciones puras, sin red ni base de datos: el runner
(``scripts/eval_cerebro_bench.py``) les pasa la respuesta del chat, el texto
que la app le dio al modelo (si lo hubo) y la instantánea de datos de la app.

Criterios (en este orden; el juez LLM va aparte y después):

1. ``cifras``: toda cifra de la respuesta sale de los datos de la app. Una
   cifra que no está ni en la pregunta, ni en el historial, ni en el contexto
   que la app le pasó al modelo, ni en la instantánea de datos cuenta como
   **inventada**.
2. ``ruta``: la pregunta va por la herramienta o ruta correcta.
3. ``no_orden``: una pregunta de consejo no se contesta con «no ejecuto órdenes».
4. ``idioma``: la respuesta está en español y con formato numérico español.
5. ``hechos``: las cifras clave del caso (p. ej. tu efectivo) aparecen.
6. ``texto``: patrones obligatorios y prohibidos del caso.
7. ``latencia``: por debajo del límite del caso.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

# Número con miles «.» o «,» y decimales; también «1,2 mil millones», «-3,5 %».
_NUM_RE = re.compile(r"(?<![\w.,])[-−+]?(?:\d{1,3}(?:[.,\u202f\u00a0 ]\d{3})+|\d+)(?:[.,]\d+)?(?![\w])")
_DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:de\s+)?(?:ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic)[a-z]*\.?(?:\s+(?:de\s+)?\d{4})?"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
# «2X», «3X», «4X» (niveles DCA), «T3», «v2», «1S», «10-K», «13F», «40-F»…
_TOKEN_SKIP_RE = re.compile(
    r"\b(?:\d+[xX]|[TQ][1-4]|[1-4][TQ]|v\d+|[12]S|10-[KQ]|20-F|40-F|13[FDG]|8-K|S-1|N-PORT|Form\s*4|\d+\s*(?:años|meses|días|semanas|trimestres|ejercicios))\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+|/[a-z][\w/\-?=&.]*")
_TICKER_DIGITS_RE = re.compile(r"\b[A-Z]{1,6}\d[A-Z\d.]*\b")

SMALL_ORDINAL_MAX = 12  # «3 posiciones», «dos de 5»: recuentos pequeños no son cifras financieras


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def parse_number(raw: str) -> float | None:
    """«1.234,56» → 1234.56; «1,234.56» → 1234.56; «358.22» → 358.22; «3.200» → 3200."""
    s = raw.replace("−", "-").replace("\u202f", "").replace("\u00a0", "").replace(" ", "").lstrip("+")
    neg = s.startswith("-")
    s = s.lstrip("-")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        # «1,234,567» son miles en inglés; «3,5» y «1,234» son decimales en español.
        s = s.replace(",", "") if s.count(",") > 1 else head + "." + tail
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts[-1]) == 3 and len(parts[0]) <= 3 and parts[0].strip("0")):
            s = s.replace(".", "")  # miles español
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def extract_numbers(text: str) -> list[tuple[str, float]]:
    """Cifras de un texto, sin fechas, años, niveles DCA, URLs ni tickers con dígitos."""
    if not text:
        return []
    t = _URL_RE.sub(" ", text)
    t = _DATE_RE.sub(" ", t)
    t = _TOKEN_SKIP_RE.sub(" ", t)
    t = _TICKER_DIGITS_RE.sub(" ", t)
    out: list[tuple[str, float]] = []
    for m in _NUM_RE.finditer(t):
        raw = m.group(0).strip()
        v = parse_number(raw)
        if v is None:
            continue
        out.append((raw, v))
    return out


def financial_numbers(text: str) -> list[tuple[str, float]]:
    """Las cifras que deben estar respaldadas: no años ni recuentos pequeños enteros."""
    res = []
    for raw, v in extract_numbers(text):
        digits = re.sub(r"\D", "", raw)
        if _YEAR_RE.match(digits) and float(v).is_integer() and "," not in raw and "." not in raw:
            continue
        if float(v).is_integer() and 0 <= abs(v) <= SMALL_ORDINAL_MAX and not re.search(r"[.,]", raw):
            continue
        res.append((raw, v))
    return res


_UNIT_RE = re.compile(
    r"^\s*(?:(?P<b>mil\s+millones|billones?\b|billions?\b|bn\b|B\b)|(?P<m>millones|millions?\b|mill\.?|M\b|MM\b)|(?P<k>mil\b|k\b)|(?P<p>%|por\s+ciento|pp\b|puntos))",
    re.IGNORECASE,
)


def _decimals(raw: str) -> int:
    """Decimales escritos: «158,60» → 2, «3.200» → 0, «94,8» → 1, «358.22» → 2."""
    v = parse_number(raw)
    if v is None:
        return 0
    s = raw.replace("−", "-").lstrip("+-")
    for sep in (",", "."):
        if sep in s:
            tail = s.rsplit(sep, 1)[1]
            if not (sep == "." and len(tail) == 3 and "," not in s and s.split(".")[0].strip("0")) and not (
                sep == "," and s.count(",") > 1
            ):
                return len(tail)
    return 0


def numbers_with_units(text: str) -> list[tuple[str, float, float, bool, int]]:
    """(texto, valor, escala, es_porcentaje, decimales) de cada cifra."""
    if not text:
        return []
    t = _URL_RE.sub(" ", text)
    t = _DATE_RE.sub(" ", t)
    t = _TOKEN_SKIP_RE.sub(" ", t)
    t = _TICKER_DIGITS_RE.sub(" ", t)
    out = []
    for m in _NUM_RE.finditer(t):
        raw = m.group(0).strip()
        v = parse_number(raw)
        if v is None:
            continue
        u = _UNIT_RE.match(t[m.end() : m.end() + 20])
        scale, pct = 1.0, False
        if u:
            if u.group("b"):
                scale = 1e9
            elif u.group("m"):
                scale = 1e6
            elif u.group("k"):
                scale = 1e3
            elif u.group("p"):
                pct = True
        out.append((raw, v, scale, pct, _decimals(raw)))
    return out


def build_ground(texts: Iterable[str], values: Iterable[float] = ()) -> list[float]:
    """Valores de respaldo: cada cifra de los textos a su escala escrita y tal cual."""
    vals: list[float] = []
    for t in texts:
        for _raw, v, scale, _pct, _d in numbers_with_units(t or ""):
            vals.append(v)
            if scale != 1.0:
                vals.append(v * scale)
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            vals.append(f)
    return vals


def _matches(v: float, scale: float, pct: bool, decimals: int, ground: list[float]) -> bool:
    """¿Es ``v`` (redondeado a ``decimals``) alguna cifra del respaldo?

    Tolerancia = media unidad del último decimal escrito (el redondeo que se ve),
    en la escala escrita; un porcentaje puede venir de un ratio (0,577 → 57,7 %).
    """
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    a = abs(v)
    cands = [(a, tol)]
    if scale != 1.0:
        cands.append((a * scale, tol * scale))
    if pct:
        cands.append((a / 100.0, tol / 100.0))
    for g in ground:
        ag = abs(g)
        for c, t in cands:
            if abs(c - ag) <= t:
                return True
    return False


def is_grounded(
    v: float, ground: list[float], *, raw: str | None = None, scale: float = 1.0, pct: bool = False
) -> bool:
    decimals = _decimals(raw) if raw is not None else 6
    if raw is None:
        # Comparación de un valor exacto (hechos clave): tolerancia relativa pequeña.
        return any(abs(abs(v) - abs(g)) <= max(0.005, 0.006 * abs(g)) for g in ground)
    return _matches(v, scale, pct, decimals, ground)


def ungrounded_numbers(answer: str, ground: list[float]) -> list[str]:
    fin = {raw for raw, _v in financial_numbers(answer)}
    out = []
    for raw, v, scale, pct, dec in numbers_with_units(answer):
        if raw in fin and not _matches(v, scale, pct, dec, ground):
            out.append(raw)
    return out


# --- consejo / órdenes ------------------------------------------------------
_ORDER_REFUSAL_RE = re.compile(
    r"no\s+(?:ejecuto|puedo\s+ejecutar|realizo|hago)\s+(?:[óo]rdenes|operaciones|compras|ventas)",
    re.IGNORECASE,
)


def order_refusal(answer: str) -> bool:
    return bool(
        _ORDER_REFUSAL_RE.search(_strip_accents(answer or "")) or _ORDER_REFUSAL_RE.search(answer or "")
    )


# --- idioma -----------------------------------------------------------------
_ES = frozenset(
    [
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "que",
        "y",
        "en",
        "un",
        "una",
        "es",
        "por",
        "para",
        "con",
        "no",
        "se",
        "su",
        "sus",
        "al",
        "lo",
        "como",
        "más",
        "pero",
        "tu",
        "tus",
        "hay",
        "este",
        "esta",
        "está",
        "son",
        "tiene",
        "sin",
        "sobre",
        "entre",
        "también",
        "cuando",
        "muy",
        "ya",
    ]
)
_EN = frozenset(
    [
        "the",
        "of",
        "and",
        "to",
        "in",
        "is",
        "that",
        "for",
        "with",
        "on",
        "as",
        "are",
        "this",
        "be",
        "by",
        "it",
        "at",
        "from",
        "your",
        "you",
        "not",
        "have",
        "has",
        "which",
        "there",
        "their",
        "was",
        "were",
        "an",
        "or",
    ]
)
# «358.22», «1,234.56»: separadores en inglés dentro de una respuesta en español.
# «$358.22» es el formato fijado de la app para precios en USD
# (tests/test_chat_price_display.py) y no cuenta como fallo de idioma.
_EN_DECIMAL_RE = re.compile(
    r"(?<![\w.,$])\d{1,3}(?:,\d{3})*\.\d{1,2}(?![\d\w])|(?<![\w.,$])\d{1,3}(?:,\d{3})+(?![\d.,\w])"
)


def language_es(answer: str) -> tuple[bool, str]:
    words = re.findall(r"[a-záéíóúñü]+", (answer or "").lower())
    es = sum(1 for w in words if w in _ES)
    en = sum(1 for w in words if w in _EN)
    if not words:
        return False, "vacía"
    if en > es:
        return False, f"inglés ({en} vs {es})"
    clean = _URL_RE.sub(" ", answer)
    clean = re.sub(r"\b[\w-]*v\d+\.\d+[\w.-]*", " ", clean)  # «deepseek-v4.1-flash», «v2.1»
    bad = [m.group(0) for m in _EN_DECIMAL_RE.finditer(clean)]
    if bad:
        return False, "formato numérico inglés: " + ", ".join(bad[:3])
    return True, ""


@dataclass
class CaseResult:
    id: str
    category: str
    checks: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    invented: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def _route_of(resp: dict) -> str:
    tr = resp.get("llm_trace") or {}
    return str(
        tr.get("path")
        or tr.get("workflow")
        or ("llm" if resp.get("model") not in (None, "deterministic") else "?")
    )


def grade_case(
    case: dict, resp: dict, *, latency_s: float, ground: list[float], fact_values: dict[str, float]
) -> CaseResult:
    """Aplica todos los graders deterministas a un caso."""
    exp = case.get("expect") or {}
    ans = (resp.get("answer") or "").strip()
    r = CaseResult(id=case["id"], category=case["category"])
    # 1. cifras
    inv = ungrounded_numbers(ans, ground)
    r.invented = inv
    r.checks["cifras"] = not inv
    if inv:
        r.notes["cifras"] = "sin respaldo: " + ", ".join(inv[:6])
    # 2. ruta
    route = _route_of(resp)
    ok = True
    if exp.get("route_in"):
        ok = route in exp["route_in"]
    if exp.get("route_not_in") and route in exp["route_not_in"]:
        ok = False
    r.checks["ruta"] = ok
    if not ok:
        r.notes["ruta"] = route
    # 3. consejo sin «no ejecuto órdenes»
    if exp.get("advice"):
        r.checks["no_orden"] = not order_refusal(ans)
    # 4. idioma
    if exp.get("lang", "es") == "es":
        ok, why = language_es(ans)
        r.checks["idioma"] = ok
        if not ok:
            r.notes["idioma"] = why
    # 5. hechos clave
    missing = []
    nums = numbers_with_units(ans)
    for key in exp.get("facts") or []:
        val = fact_values.get(key)
        if val is None:
            missing.append(f"{key}=?")
            continue
        # El dato clave puede ir redondeado (3.200 €, 1.516,9 €), nunca otro valor.
        if not any(
            _matches(n, sc, pc, max(d, 0), [val]) or abs(n - val) <= max(0.01, 0.005 * abs(val))
            for _r, n, sc, pc, d in nums
        ):
            missing.append(key)
    if exp.get("facts"):
        r.checks["hechos"] = not missing
        if missing:
            r.notes["hechos"] = "faltan: " + ", ".join(missing)
    # 6. texto
    low = _strip_accents(ans.lower())
    bad = []
    if exp.get("must_any") and not any(re.search(_strip_accents(p.lower()), low) for p in exp["must_any"]):
        bad.append("falta " + "|".join(exp["must_any"])[:60])
    for pat in exp.get("must_not") or []:
        if re.search(_strip_accents(pat.lower()), low):
            bad.append("prohibido " + pat[:40])
    if not ans:
        bad.append("respuesta vacía")
    if exp.get("must_any") or exp.get("must_not") or not ans:
        r.checks["texto"] = not bad
        if bad:
            r.notes["texto"] = "; ".join(bad)
    # 7. latencia
    lim = float(exp.get("max_s", 45))
    r.checks["latencia"] = latency_s <= lim
    if latency_s > lim:
        r.notes["latencia"] = f"{latency_s:.1f}s > {lim:.0f}s"
    return r


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)
