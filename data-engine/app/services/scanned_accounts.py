"""Cifras citadas de las cuentas escaneadas (PDF sin texto) que se depositan en Companies House.

Las cuentas grandes britanicas (Brit Group Holdings, Georgia Capital PLC…) se depositan como
imagen: sin iXBRL y sin capa de texto, asi que hasta ahora salian citadas por su enlace pero
con 0 cifras. Este modulo es GENERAL (nunca por empresa):

1. Indice de titulos: renderiza cada pagina (una a una, ``pypdfium2``, que ya trae Docling) y
   pasa por ``tesseract`` (ya en la imagen Docker) solo la franja superior, a baja resolucion.
2. Estados primarios por su titulo: cuenta de resultados (``income statement``, ``statement of
   profit or loss``, ``profit and loss account``…) y balance (``statement of financial
   position``, ``balance sheet``). Si hay consolidados, solo cuentan los consolidados.
3. OCR completo (300 ppp) de esas paginas, lectura de las columnas de cifras: la columna del
   ejercicio es la del año mayor de la cabecera; parentesis = negativo; guion = cero; las
   referencias a notas (a la izquierda de las cifras) se descartan. Unidades por el banner
   (``$m``, ``£000``, ``Thousands of Georgian Lari``…).
4. Validacion: el balance tiene que cuadrar (activo = pasivo + patrimonio, o patrimonio neto =
   fondos propios) o sus cifras NO se usan y se dice por que. La cuenta de resultados se
   comprueba con beneficio antes de impuestos + impuesto = beneficio del ejercicio. Ademas,
   cada linea que suma exactamente en su subtotal queda marcada como comprobada.

Cada cifra lleva su pagina, la linea literal del OCR, las unidades y el periodo. Sin LLM.
"""
from __future__ import annotations

import difflib
import io
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

#: Una sola pagina en OCR a la vez por proceso (la maquina va justa de memoria).
_OCR_SLOT = threading.BoundedSemaphore(1)

HEAD_DPI = 144
FULL_DPI = 300
HEAD_FRACTION = 0.22
MAX_PAGES = 400
OCR_TIMEOUT_S = 120
EXTRACTOR_VERSION = 1

INCOME = "income"
BALANCE = "balance"

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}

_INCOME_TITLE = re.compile(
    r"^(?:(?:consolidated|group)\s+)?(?:income\s+statement|statement\s+of\s+(?:consolidated\s+)?"
    r"(?:comprehensive\s+income|profit\s+(?:or|and)\s+loss|income|operations)|profit\s+and\s+loss\s+account)\b")
_BALANCE_TITLE = re.compile(
    r"^(?:(?:consolidated|group)\s+)?(?:statement\s+of\s+(?:consolidated\s+)?financial\s+position|balance\s+sheet)\b")
_PERIOD = re.compile(
    r"(?:year|period|months?|weeks?)\s+ended\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})"
    r"|\b(?:as\s+)?at\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})", re.I)
_YEAR = re.compile(r"(?<![\d,.])(19[89]\d|20[0-4]\d)(?![\d,.])")

_CURRENCY_WORDS = (
    ("georgian lari", "GEL"), ("pounds sterling", "GBP"), ("sterling", "GBP"), ("us dollars", "USD"),
    ("u.s. dollars", "USD"), ("united states dollars", "USD"), ("euros", "EUR"), ("euro", "EUR"),
    ("canadian dollars", "CAD"), ("dollars", "USD"), ("lari", "GEL"),
)
_SYMBOLS = {"us$": "USD", "$": "USD", "£": "GBP", "€": "EUR", "gel": "GEL", "eur": "EUR", "gbp": "GBP", "usd": "USD"}
_UNIT_TOKEN = re.compile(r"(us\$|\$|£|€|\bgel|\beur|\bgbp|\busd)\s?(['’`]?000|['’`]?m\b|mn\b|million|bn\b|k\b)", re.I)
_SCALE_WORDS = (("thousands", 1_000), ("millions", 1_000_000), ("billions", 1_000_000_000))


@dataclass
class Row:
    label: str
    values: list[Decimal | None]
    line: str
    index: int
    page: int
    checked_in: str | None = None


@dataclass
class Statement:
    kind: str
    pages: list[int]
    title: str
    consolidated: bool
    currency: str | None
    scale: int | None
    unit: str | None
    years: list[int]
    current_col: int | None
    period_end: str | None
    rows: list[Row] = field(default_factory=list)
    decimals: bool = False
    unit_note: str | None = None


# --------------------------------------------------------------------------------- texto
def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9'()/&\- ]+", " ", text)
    text = re.sub(r"\s*/\s*", "/", text)  # «(Loss) / profit» = «(loss)/profit»
    return re.sub(r"\s+", " ", text).strip()


def _strip_noise(line: str) -> str:
    return re.sub(r"^[^A-Za-z(]+", "", line).strip()


def classify_heading(text: str) -> tuple[str, bool, str] | None:
    """(tipo, consolidado, titulo) de una pagina por las lineas de su cabecera, o None.

    Exige el titulo al principio de una linea (no «Strong balance sheet…» en el informe de
    gestion) y una fecha de periodo o un banner de unidades en la cabecera."""
    lines = [_norm(_strip_noise(ln)) for ln in text.splitlines() if ln.strip()]
    head = " ".join(lines[:12])
    if re.search(r"changes\s+in\s+equity|cash\s+flows?|notes\s+to\s+the|^contents", head):
        # Los titulos de otros estados en la misma cabecera mandan sobre la coincidencia
        has_other = True
    else:
        has_other = False
    for ln in lines[:12]:
        bare = re.sub(r"^(?:financial\s+statements?\s*)", "", ln).strip()
        for kind, pattern in ((INCOME, _INCOME_TITLE), (BALANCE, _BALANCE_TITLE)):
            match = pattern.match(bare)
            if not match:
                continue
            if has_other and not re.search(r"(year|period|months?)\s+ended|\bat\s+\d", head):
                continue
            rest = bare[match.end():]
            if re.search(r"\b(continued|events?|date)\b", rest):
                continue
            if not (_PERIOD.search(head) or _UNIT_TOKEN.search(head) or re.search(r"thousands|millions", head)):
                continue
            company_only = bool(re.search(r"\b(company|parent)\b", bare[:match.start() + 1] + rest)) and not \
                bare.startswith(("consolidated", "group"))
            consolidated = bare.startswith(("consolidated", "group")) or "consolidated" in bare
            return kind, consolidated and not company_only, ln
    return None


def parse_units(text: str) -> tuple[str | None, int | None, str | None]:
    """(moneda ISO, escala, unidad tal cual) del banner o de la cabecera de columnas."""
    low = text.lower().replace("’", "'")
    for word, scale in _SCALE_WORDS:
        match = re.search(rf"{word}\s+of\s+([a-z. ]+)", low)
        if match:
            tail = match.group(1)
            for name, iso in _CURRENCY_WORDS:
                if tail.startswith(name):
                    return iso, scale, match.group(0).strip()
            return None, scale, match.group(0).strip()
    match = _UNIT_TOKEN.search(low)
    if match:
        sym, mag = match.group(1).lower(), match.group(2).lower().strip("'`’")
        scale = 1_000 if mag in ("000", "k") else 1_000_000_000 if mag == "bn" else 1_000_000
        return _SYMBOLS.get(sym), scale, match.group(0).strip()
    return None, None, None


def parse_period(text: str) -> str | None:
    match = _PERIOD.search(text)
    if not match:
        return None
    g = [x for x in match.groups() if x]
    day, month, year = g[0], g[1].lower(), g[2]
    month_n = _MONTHS.get(month) or next((v for k, v in _MONTHS.items()
                                          if difflib.SequenceMatcher(None, k, month).ratio() > 0.75), None)
    if not month_n:
        return None
    try:
        return date(int(year), month_n, int(day)).isoformat()
    except ValueError:
        return None


_NUM = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?$|^\(?-?\d+(?:\.\d+)?\)?$")
_DASHES = {"-", "—", "–", "--", "_", "nil"}


def _clean_token(tok: str) -> str:
    tok = tok.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    tok = tok.strip(".,;:|'‘’\"~=°*")
    tok = re.sub(r"^[=~]+", "", tok)
    return tok


def _value(tok: str) -> Decimal | None:
    if tok in _DASHES:
        return Decimal(0)
    neg = tok.startswith("(") or tok.startswith("-")
    raw = tok.strip("()-").replace(",", "")
    try:
        val = Decimal(raw)
    except InvalidOperation:
        return None
    return -val if neg else val


def parse_line(line: str, ncols: int, decimals: bool) -> tuple[str, list[Decimal | None]] | None:
    """(etiqueta, valores por columna) de una linea de estado financiero, o None si no lleva cifras.

    Lee desde la derecha: las ``ncols`` ultimas cifras son las columnas; lo que queda a la
    izquierda (``5,18``, ``13°``) son notas. En un estado con decimales (``2,950.3``) un entero
    suelto es una nota, nunca una cifra. Si falta alguna columna no se adivina cual: todas None."""
    tokens = line.split()
    found: list[str] = []
    stop = len(tokens)
    for i in range(len(tokens) - 1, -1, -1):
        tok = _clean_token(tokens[i])
        if not re.search(r"[A-Za-z0-9]", tok) and tok not in _DASHES:
            continue  # puntuacion y ruido del escaneo entre cifras
        if tok in _DASHES or _NUM.match(tok):
            found.append(tok)
            stop = i
            continue
        break
    if not found:
        return None
    found.reverse()
    if decimals:
        tail: list[str] = []
        for tok in reversed(found):
            if tok in _DASHES or "." in tok:
                tail.append(tok)
            else:
                break
        cols = list(reversed(tail))
    else:
        cols = found
    cols = cols[-ncols:]
    vals: list[Decimal | None] = [_value(t) for t in cols]
    if len(vals) < ncols or any(v is None for v in vals):
        vals = [None] * ncols
    label = _strip_noise(" ".join(tokens[:stop]))
    words = label.split()
    while words and (not re.search(r"[A-Za-z0-9]", words[-1]) or re.fullmatch(r"[a-z]{1,2}|\d{1,2}(?:,\d{1,2})*\W*", words[-1])
                     or (len(words[-1].strip("()")) <= 2 and not words[-1].strip("()").isalpha())):
        words.pop()  # «Borrowings . i», «Share premium Lo» -> sin el ruido final
    label = re.sub(r"[\s.,;:|~'‘’/*]+$", "", " ".join(words)).strip()
    if label and re.fullmatch(r"[A-Z][a-z]", label.split()[-1]) and len(label.split()) > 2:
        label = " ".join(label.split()[:-1])
    if not re.search(r"[A-Za-z]{3}", label):
        return None
    return label, vals


_COL_UNIT = re.compile(r"^(?P<sym>[£$€]|us\$|[a-z]{1,2})?(?P<mag>['’]?m|mn|million|'?000|’000)$", re.I)


def document_currency(texts: list[str]) -> str | None:
    """Moneda que mas aparece en el documento (simbolos y palabras), para un simbolo mal leido."""
    blob = " ".join(texts).lower()
    counts = {"GBP": blob.count("£") + 3 * blob.count("sterling"), "USD": blob.count("$") + 3 * blob.count("us dollar"),
              "EUR": blob.count("€") + 3 * blob.count(" euro")}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] >= 3 else None


def _column_units(head_lines: list[str], hint: str | None) -> tuple[str | None, int | None, str | None, str | None]:
    """Unidades de la cabecera de columnas cuando el simbolo sale mal en el OCR («Note im im»)."""
    symbols = {"GBP": "£", "USD": "$", "EUR": "€"}
    for ln in head_lines:
        toks = [t.strip(".,;:|") for t in ln.split()]
        hits = [m for m in (_COL_UNIT.match(t) for t in toks if t) if m]
        if len(hits) < 2:
            continue
        mag = hits[-1].group("mag").lower().strip("'’")
        if mag == "m":
            mag = "m"
        scale = 1_000 if mag == "000" else 1_000_000
        sym = (hits[-1].group("sym") or "").lower()
        if sym in _SYMBOLS:
            return _SYMBOLS[sym], scale, hits[-1].group(0), None
        word = "m" if scale == 1_000_000 else "000"
        if hint:
            return hint, scale, f"{symbols.get(hint, '')}{word}", (
                f"simbolo de moneda leido como «{hits[-1].group(0)}»; moneda deducida del documento ({hint})")
        return None, scale, word, f"simbolo de moneda ilegible («{hits[-1].group(0)}»)"
    return None, None, None, None


def parse_statement(kind: str, pages: list[tuple[int, str]], title: str = "", consolidated: bool = False,
                    currency_hint: str | None = None) -> Statement:
    """Estado financiero desde el texto OCR de su(s) pagina(s)."""
    full = "\n".join(t for _p, t in pages)
    head_lines = [ln for ln in full.splitlines() if ln.strip()][:14]
    head = "\n".join(head_lines)
    currency, scale, unit = parse_units(head)
    unit_note = None
    if scale is None:
        currency, scale, unit, unit_note = _column_units(head_lines, currency_hint)
    elif currency is None and currency_hint:
        currency, unit_note = currency_hint, f"moneda deducida del documento ({currency_hint})"
    years: list[int] = []
    for ln in head_lines:
        ys = [int(y) for y in _YEAR.findall(ln)]
        if len(ys) >= 2 and len(set(ys)) >= 2:
            years = ys
            break
    if not years:
        for ln in full.splitlines()[:30]:
            ys = [int(y) for y in _YEAR.findall(ln)]
            if len(ys) >= 2 and len(set(ys)) >= 2:
                years = ys
                break
    current_col = years.index(max(years)) if years else None
    period = parse_period(head)
    if period and years and int(period[:4]) != max(years):
        period = None
    if not period and years:
        period = str(max(years))
    ncols = len(years) if years else 2
    numeric = re.findall(r"\d{1,3}(?:,\d{3})*\.\d\b", full)
    integers = re.findall(r"\d{1,3},\d{3}(?![.\d])", full)
    decimals = len(numeric) > len(integers)
    st = Statement(kind=kind, pages=[p for p, _t in pages], title=title, consolidated=consolidated,
                   currency=currency, scale=scale, unit=unit, years=years, current_col=current_col,
                   period_end=period, decimals=decimals, unit_note=unit_note)
    idx = 0
    for page, text in pages:
        prev_text = ""
        for raw in text.splitlines():
            if not raw.strip():
                continue
            parsed = parse_line(raw, ncols, decimals)
            if parsed is None and prev_text and not re.search(r"[A-Za-z]{3}", raw) and re.search(r"\d", raw):
                # etiqueta partida en dos lineas: «(Loss) / profit … for the» + «: : (4.7) 11.0»
                parsed = parse_line(f"{prev_text} {raw}", ncols, decimals)
                raw = f"{prev_text} {raw.strip()}"
            if parsed is None:
                prev_text = raw.strip() if re.search(r"[A-Za-z]{3}", raw) and not re.search(r"\d[\d,.]*\)?\s*$", raw) else ""
                continue
            prev_text = ""
            label, vals = parsed
            if years and [int(v) for v in vals if v is not None] == years[:len(vals)]:
                continue  # la cabecera de columnas («Note 2025 2024»)
            if kind == INCOME and re.match(r"^loss(?!\s*/|\s*\(?profit)", _norm(label)):
                # «Loss for the year 34.7»: la etiqueta ya dice perdida aunque el OCR pierda el parentesis
                vals = [-abs(v) if v is not None else None for v in vals]
            st.rows.append(Row(label=label, values=vals, line=raw.strip(), index=idx, page=page))
            idx += 1
    _mark_sums(st)
    return st


def _tol(st: Statement, ref: Decimal | None = None) -> Decimal:
    unit = Decimal("0.1") if st.decimals else Decimal(1)
    base = unit * 3
    if ref is not None:
        base = max(base, abs(ref) * Decimal("0.00005"))
    return base


def _cur(st: Statement, row: Row) -> Decimal | None:
    if st.current_col is None or st.current_col >= len(row.values):
        return None
    return row.values[st.current_col]


def _mark_sums(st: Statement) -> None:
    """Marca cada linea que suma exactamente en un subtotal posterior (pila de partidas abiertas)."""
    open_rows: list[Row] = []
    for row in st.rows:
        val = _cur(st, row)
        if val is None:
            open_rows = []
            continue
        matched = False
        for k in range(len(open_rows) - 2, -1, -1):
            block = open_rows[k:]
            vals = [_cur(st, r) for r in block]
            if any(v is None for v in vals):
                continue
            total = sum((v for v in vals if v is not None), Decimal(0))
            if abs(total - val) <= _tol(st, val) and any(v != 0 for v in vals):
                for r in block:
                    r.checked_in = r.checked_in or row.label
                open_rows = open_rows[:k] + [row]
                matched = True
                break
        if not matched:
            open_rows.append(row)


# ------------------------------------------------------------------------------- metricas
def _similar(label: str, options: tuple[str, ...], cutoff: float = 0.86) -> bool:
    low = _norm(label)
    return any(low == o or difflib.SequenceMatcher(None, low, o).ratio() >= cutoff for o in options)


_TOTAL_ASSETS = ("total assets",)
_TOTAL_LIABS = ("total liabilities",)
_TOTAL_EQUITY = ("total equity", "total shareholders' equity", "total shareholders equity", "total shareholders' funds",
                 "total shareholders funds", "shareholders' funds", "total capital and reserves", "capital and reserves")
_TOTAL_LE = ("total liabilities and equity", "total equity and liabilities", "total liabilities and shareholders' equity")
_NET_ASSETS = ("net assets", "total net assets", "net assets attributable to shareholders")
_NCI = ("non-controlling interests", "non-controlling interest", "minority interests", "minority interest",
        "non controlling interests")

_REVENUE_ORDER = (
    ("gross written premiums", "gross premiums written", "gross written premium"),
    ("total revenue", "revenue", "turnover", "group turnover", "total income", "total operating income",
     "insurance revenue", "net revenue", "revenues"),
    ("gross investment profit", "total investment income", "net investment income"),
)


def _find(st: Statement | None, pred: Callable[[str], bool], *, last: bool = False) -> Row | None:
    if st is None:
        return None
    rows = [r for r in st.rows if pred(_norm(r.label)) and _cur(st, r) is not None]
    if not rows:
        return None
    return rows[-1] if last else rows[0]


def _is_pbt(low: str) -> bool:
    return bool(re.match(r"^(?:\(?loss\)?/?\(?profit\)?|\(?profit\)?/?\(?loss\)?|profit|loss|result)"
                         r"(?: on ordinary activities)? before (?:income )?tax(?:es|ation)?\b", low))


def _is_profit_year(low: str) -> bool:
    return bool(re.match(r"^(?:\(?loss\)?/?\(?profit\)?|\(?profit\)?/?\(?loss\)?|profit|loss)"
                         r"(?: and total comprehensive (?:income|loss|income/\(?expense\)?))?(?: after tax(?:ation)?)?"
                         r" for the(?: (?:financial )?(?:year|period))?(?:\b|$)", low)
                or re.match(r"^(?:profit|loss) after tax(?:ation)?$", low) or low in ("net income", "net profit"))


def _is_tax(low: str) -> bool:
    return bool(re.match(r"^(?:income )?tax(?:ation)?(?: (?:charge|expense|credit|on profit))?\b", low)
                and "before" not in low and "deferred" not in low and "assets" not in low
                and "liabilities" not in low)


def _is_attrib_owner(low: str) -> bool:
    return bool(re.search(r"(?:owners|equity holders|shareholders|members) of the (?:parent|company)", low)
                or re.search(r"attributable to (?:the )?(?:owners|equity holders|shareholders|members)", low))


def _is_cash(low: str) -> bool:
    return bool(re.match(r"^(?:cash and cash equivalents|cash at bank(?: and in hand)?|cash and (?:short.term )?deposits|cash)\b",
                         low)) and "restricted" not in low and "flow" not in low


def _is_borrowing(low: str) -> bool:
    return bool(re.search(r"\bborrowings?\b|loans and borrowings|bank loans?\b|debt securities in issue|senior notes"
                          r"|subordinated (?:debt|notes|liabilities)|loan notes|notes payable|bonds? (?:issued|payable)",
                          low)) and not low.startswith("total") and "lease" not in low and "interest" not in low[:9]


def _fig(st: Statement, row: Row, metric: str, *, basis: str | None = None, value: Decimal | None = None,
         check: str | None = None) -> dict[str, Any]:
    val = value if value is not None else _cur(st, row)
    comp = None
    if st.current_col is not None and len(row.values) == 2:
        comp = row.values[1 - st.current_col]
    millions = None
    if val is not None and st.scale:
        millions = float(val * st.scale / Decimal(1_000_000))
    if st.kind == INCOME and re.match(r"^loss(?!\s*/|\s*\(?profit)", _norm(row.label)) and "(" not in row.line:
        basis = ((basis + "; ") if basis else "") + "la etiqueta dice pérdida: se toma en negativo"
    return {
        "metric": metric, "label": row.label, "value": float(val) if val is not None else None,
        "comparative": float(comp) if comp is not None else None,
        "value_millions": round(millions, 6) if millions is not None else None,
        "currency": st.currency, "unit": st.unit, "scale": st.scale, "period_end": st.period_end,
        "column": str(max(st.years)) if st.years else None, "page": row.page, "line": row.line,
        "statement": st.kind, "consolidated": st.consolidated, "basis": basis, "unit_note": st.unit_note,
        "check": check or (f"suma en «{row.checked_in}»" if row.checked_in else None),
    }


def balance_check(st: Statement) -> tuple[bool, str]:
    """(cuadra, explicacion). Sin cuadre las cifras del balance no se usan."""
    ta = _find(st, lambda s: _similar(s, _TOTAL_ASSETS, 0.9))
    tl = _find(st, lambda s: _similar(s, _TOTAL_LIABS, 0.85), last=True)
    te = _find(st, lambda s: _similar(s, _TOTAL_EQUITY, 0.88), last=True)
    tle = _find(st, lambda s: _similar(s, _TOTAL_LE, 0.88))
    na = _find(st, lambda s: _similar(s, _NET_ASSETS, 0.9))
    if st.current_col is None:
        return False, "no se identifican las columnas del ejercicio y el comparativo"
    cur = lambda r: _cur(st, r)  # noqa: E731
    if ta and tl and te:
        a, liab, eq = cur(ta), cur(tl), cur(te)
        assert a is not None and liab is not None and eq is not None
        liab = abs(liab)  # muchos balances britanicos presentan el pasivo entre parentesis
        diff = a - (liab + eq)
        ok = abs(diff) <= _tol(st, a)
        return ok, (f"activo {a} = pasivo {liab} + patrimonio {eq}" if ok else
                    f"no cuadra: activo {a} ≠ pasivo {liab} + patrimonio {eq} (diferencia {diff})")
    if na and te:
        n, eq = cur(na), cur(te)
        assert n is not None and eq is not None
        ok = abs(n - eq) <= _tol(st, n)
        return ok, (f"patrimonio neto {n} = fondos propios {eq}" if ok else
                    f"no cuadra: patrimonio neto {n} ≠ fondos propios {eq}")
    if ta and tle:
        a, b = cur(ta), cur(tle)
        assert a is not None and b is not None
        ok = abs(a - b) <= _tol(st, a) and te is not None
        return ok, (f"activo {a} = pasivo y patrimonio {b}" if ok else
                    f"no cuadra o falta el patrimonio: activo {a}, pasivo y patrimonio {b}")
    return False, "no se leen los totales del balance (activo, pasivo, patrimonio)"


def income_check(st: Statement) -> tuple[bool, str]:
    pbt = _find(st, _is_pbt)
    pfy = _find(st, _is_profit_year) or _find(
        st, lambda s: _is_attrib_owner(s) and bool(re.match(r"^\(?(?:profit|loss)", s)))
    if pbt is None or pfy is None:
        return False, "no se leen el beneficio antes de impuestos y el del ejercicio"
    tax = next((r for r in st.rows if pbt.index < r.index < pfy.index and _is_tax(_norm(r.label))
                and _cur(st, r) is not None), None)
    p, f = _cur(st, pbt), _cur(st, pfy)
    assert p is not None and f is not None
    t = _cur(st, tax) if tax else Decimal(0)
    assert t is not None
    if abs(p + t - f) <= _tol(st, f):
        return True, f"antes de impuestos {p} + impuesto {t} = beneficio del ejercicio {f}"
    if tax is not None and abs(p - t - f) <= _tol(st, f):
        return True, f"antes de impuestos {p} − impuesto {t} = beneficio del ejercicio {f}"
    return False, f"no cuadra: antes de impuestos {p}, impuesto {t}, beneficio del ejercicio {f}"


def figures_from_statements(income: Statement | None, balance: Statement | None) -> dict[str, Any]:
    """Cifras validadas de los estados primarios, con su motivo cuando no se usan."""
    figures: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    nci_bs = bool(balance and _find(balance, lambda s: _similar(s, _NCI, 0.85)))
    if income is not None:
        ok, why = income_check(income)
        checks["income"] = {"ok": ok, "why": why, "pages": income.pages}
        rows: list[tuple[str, Row | None, str | None]] = []
        rev = None
        for group in _REVENUE_ORDER:
            rev = _find(income, lambda s, g=group: _similar(s, g, 0.9))
            if rev:
                break
        rows.append(("revenue", rev, None))
        rows.append(("profit_before_tax", _find(income, _is_pbt), None))
        pfy = _find(income, _is_profit_year)
        if pfy is None:
            # «Loss attributable to equity holders of parent» sin linea «for the year»
            pfy = _find(income, lambda s: _is_attrib_owner(s) and bool(re.match(r"^\(?(?:profit|loss)", s)))
        rows.append(("profit_for_year", pfy, None))
        attrib = _find(income, _is_attrib_owner)
        if attrib is not None and pfy is not None and attrib.index > pfy.index:
            rows.append(("profit_attributable", attrib, None))
        elif pfy is not None and not nci_bs and not _find(income, lambda s: _similar(s, _NCI, 0.85)):
            rows.append(("profit_attributable", pfy,
                         "sin minoritarios en las cuentas: atribuible = beneficio del ejercicio"))
        for metric, row, basis in rows:
            if row is None:
                continue
            fig = _fig(income, row, metric, basis=basis)
            (figures if ok else rejected).append(fig if ok else {**fig, "reason": why})
    if balance is not None:
        ok, why = balance_check(balance)
        checks["balance"] = {"ok": ok, "why": why, "pages": balance.pages}
        out: list[dict[str, Any]] = []
        te = _find(balance, lambda s: _similar(s, _TOTAL_EQUITY, 0.88), last=True)
        if te:
            out.append(_fig(balance, te, "total_equity", check="cuadre del balance"))
        attrib = _find(balance, lambda s: bool(re.search(r"attributable to (?:the )?(?:owners|equity holders|shareholders)", s)))
        if attrib:
            out.append(_fig(balance, attrib, "equity_attributable"))
        elif te and not nci_bs:
            out.append(_fig(balance, te, "equity_attributable",
                            basis="sin minoritarios en el balance: atribuible = patrimonio total",
                            check="cuadre del balance"))
        na = _find(balance, lambda s: _similar(s, _NET_ASSETS, 0.9))
        ta = _find(balance, lambda s: _similar(s, _TOTAL_ASSETS, 0.9))
        tl = _find(balance, lambda s: _similar(s, _TOTAL_LIABS, 0.85), last=True)
        if na:
            out.append(_fig(balance, na, "net_assets", check="cuadre del balance"))
        elif ta and tl:
            a, liab = _cur(balance, ta), _cur(balance, tl)
            if a is not None and liab is not None:
                liab = abs(liab)
                fig = _fig(balance, ta, "net_assets", value=a - liab,
                           basis="activo total − pasivo total", check="cuadre del balance")
                fig.update(label=f"{ta.label} − {tl.label}", line=f"{ta.line} | {tl.line}")
                out.append(fig)
        cash = _find(balance, _is_cash)
        if cash:
            out.append(_fig(balance, cash, "cash"))
        borrow = [r for r in balance.rows if _is_borrowing(_norm(r.label)) and _cur(balance, r) is not None]
        if borrow:
            total = sum((abs(_cur(balance, r) or Decimal(0)) for r in borrow), Decimal(0))
            fig = _fig(balance, borrow[0], "borrowings", value=total,
                       basis=None if len(borrow) == 1 else "suma de: " + "; ".join(r.label for r in borrow))
            if any((_cur(balance, r) or 0) < 0 for r in borrow):
                fig["basis"] = ((fig["basis"] + "; ") if fig["basis"] else "") + "en el balance va entre paréntesis (pasivo)"
            if len(borrow) > 1:
                fig["line"] = " | ".join(r.line for r in borrow)
            out.append(fig)
        if ok:
            figures.extend(out)
        else:
            rejected.extend({**f, "reason": why} for f in out)
    return {"figures": figures, "rejected": rejected, "checks": checks}


# ----------------------------------------------------------------------------------- OCR
def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_png(png: bytes, *, psm: str = "6") -> str:
    """Texto de una imagen con tesseract (solo datos: nunca se interpreta como ordenes)."""
    with _OCR_SLOT:
        result = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", psm],
                                input=png, capture_output=True, timeout=OCR_TIMEOUT_S, check=False)
    return result.stdout.decode("utf-8", "replace")


class PdfPages:
    """Paginas de un PDF renderizadas de una en una (pypdfium2, perezoso)."""

    def __init__(self, data: bytes) -> None:
        import pypdfium2 as pdfium  # perezoso: lo trae Docling

        self._pdf = pdfium.PdfDocument(data)

    def __len__(self) -> int:
        return len(self._pdf)

    def png(self, index: int, dpi: int, top_fraction: float | None = None) -> bytes:
        page = self._pdf[index]
        try:
            image = page.render(scale=dpi / 72, grayscale=True).to_pil()
        finally:
            page.close()
        if top_fraction:
            w, h = image.size
            image = image.crop((0, 0, w, int(h * top_fraction)))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def close(self) -> None:
        self._pdf.close()


def locate_statements(headings: dict[int, str]) -> dict[str, list[tuple[int, bool, str]]]:
    """{tipo: [(pagina, consolidado, titulo)]} desde el indice de cabeceras."""
    found: dict[str, list[tuple[int, bool, str]]] = {INCOME: [], BALANCE: []}
    for page in sorted(headings):
        hit = classify_heading(headings[page])
        if hit:
            found[hit[0]].append((page, hit[1], hit[2]))
    for kind, hits in found.items():
        if any(c for _p, c, _t in hits):
            found[kind] = [h for h in hits if h[1]]
    return found


def _pick(st_list: list[Statement], kind: str) -> Statement | None:
    if not st_list:
        return None
    if kind == INCOME:
        with_pbt = [s for s in st_list if _find(s, _is_pbt)]
        return (with_pbt or st_list)[0]
    with_totals = [s for s in st_list if balance_check(s)[0]]
    return (with_totals or st_list)[0]


#: Pasadas de OCR por pagina de estado: la normal y, si sus cifras no cuadran, otras dos
#: (otra segmentacion y otra resolucion). Se queda la primera lectura que cuadra.
OCR_PASSES: tuple[tuple[int, str], ...] = ((FULL_DPI, "6"), (FULL_DPI, "4"), (200, "6"))


def _check(st: Statement) -> bool:
    return (income_check(st) if st.kind == INCOME else balance_check(st))[0]


def extract_from_pages(texts: Callable[..., str], candidates: dict[str, list[tuple[int, bool, str]]],
                       page_count: int, *, headings: dict[int, str] | None = None,
                       passes: int = len(OCR_PASSES)) -> dict[str, Any]:
    """Lee los estados candidatos (OCR completo bajo demanda, ``texts(pagina, pasada)``) y valida sus cifras."""
    picked: dict[str, Statement | None] = {}
    used_pass: dict[str, int] = {}
    pages_read = [texts(p, 0) for k in (INCOME, BALANCE) for p, _c, _t in candidates.get(k, [])[:3]]
    hint = document_currency([*(headings or {}).values(), *pages_read])
    for kind in (INCOME, BALANCE):
        statements: list[tuple[Statement, int]] = []
        for page, consolidated, title in candidates.get(kind, [])[:3]:
            first: Statement | None = None
            for n in range(max(1, passes)):
                pages = [(page, texts(page, n))]
                st = parse_statement(kind, pages, title, consolidated, currency_hint=hint)
                if kind == BALANCE and not _check(st) and page < page_count:
                    # balance en dos paginas (activo en una, pasivo y patrimonio en la siguiente)
                    st2 = parse_statement(kind, [*pages, (page + 1, texts(page + 1, n))], title, consolidated,
                                          currency_hint=hint)
                    if _check(st2):
                        st = st2
                first = first or st
                if _check(st):
                    statements.append((st, n))
                    break
                if kind == INCOME and not _find(st, _is_pbt) and n == 0:
                    break  # no es la cuenta de resultados (p. ej. el estado de resultado global)
            else:
                statements.append((first, 0)) if first else None
                continue
            if first is not None and not any(s is st for s, _n in statements):
                statements.append((first, 0))
        best = _pick([s for s, _n in statements], kind)
        picked[kind] = best
        used_pass[kind] = next((n for s, n in statements if s is best), 0)
    result = figures_from_statements(picked[INCOME], picked[BALANCE])
    result["statements"] = {k: ({"pages": s.pages, "title": s.title, "consolidated": s.consolidated,
                                 "currency": s.currency, "unit": s.unit, "unit_note": s.unit_note,
                                 "period_end": s.period_end, "years": s.years,
                                 "ocr_pass": "{} ppp, psm {}".format(*OCR_PASSES[min(used_pass[k], len(OCR_PASSES) - 1)])}
                                if s else None) for k, s in picked.items()}
    return result


def extract_from_pdf(data: bytes, *, ocr: Callable[..., str] | None = None,
                     max_pages: int = MAX_PAGES) -> dict[str, Any]:
    """Cifras citadas de un PDF escaneado. ``status``: ok | partial | not_found | unavailable."""
    if ocr is None:
        if not tesseract_available():
            return {"status": "unavailable", "reason": "sin tesseract en este servidor", "figures": []}
        ocr = ocr_png
    try:
        pdf = PdfPages(data)
    except Exception as exc:  # noqa: BLE001 - PDF ilegible o sin pypdfium2
        return {"status": "unavailable", "reason": f"PDF ilegible: {type(exc).__name__}", "figures": []}
    try:
        count = len(pdf)
        if count > max_pages:
            return {"status": "unavailable", "reason": f"{count} paginas (> {max_pages})", "figures": []}
        headings = {i + 1: ocr(pdf.png(i, HEAD_DPI, HEAD_FRACTION)) for i in range(count)}
        candidates = locate_statements(headings)
        cache: dict[tuple[int, int], str] = {}

        def full(page: int, n: int = 0) -> str:
            if (page, n) not in cache:
                dpi, psm = OCR_PASSES[n]
                cache[(page, n)] = ocr(pdf.png(page - 1, dpi), psm=psm) if 1 <= page <= count else ""
            return cache[(page, n)]

        result = extract_from_pages(full, candidates, count, headings=headings)
    finally:
        pdf.close()
    result.update(page_count=count, extractor_version=EXTRACTOR_VERSION,
                  extracted_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    if not any(candidates.values()):
        result.update(status="not_found", reason="no se encuentran la cuenta de resultados ni el balance por su titulo")
    elif result["figures"] and not result["rejected"]:
        result["status"] = "ok"
    else:
        result["status"] = "partial"
        result["reason"] = "; ".join(f"{k}: {v['why']}" for k, v in result.get("checks", {}).items() if not v["ok"]) or None
    return result


# ------------------------------------------------------------------ cache y descarga
#: Lo leido de unas cuentas no cambia (el deposito es inmutable): cache larga en Redis, sin
#: migraciones. Si Redis se vacia, se vuelve a encolar la lectura la proxima vez.
CACHE_PREFIX = f"ch:scanned:v{EXTRACTOR_VERSION}"
CACHE_TTL_S = 180 * 24 * 3600
PENDING_TTL_S = 2 * 3600
MAX_PDF_BYTES = 60_000_000
_DOC_HOSTS = ("find-and-update.company-information.service.gov.uk", "document-api.company-information.service.gov.uk")
_S3_HOST_SUFFIX = ".amazonaws.com"


def _redis() -> Any:
    from app.core import cache

    return cache._redis_client()  # noqa: SLF001 - mismo cliente con timeouts cortos


def cache_key(company_number: str, made_up_to: str | None) -> str:
    return f"{CACHE_PREFIX}:{company_number}:{made_up_to or 'sf'}"


def load_cached(company_number: str, made_up_to: str | None) -> dict[str, Any] | None:
    import json

    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(cache_key(company_number, made_up_to))
    except Exception:  # noqa: BLE001 - sin cache = pendiente
        return None
    return json.loads(raw) if raw else None


def store_cached(company_number: str, made_up_to: str | None, result: dict[str, Any], *,
                 ticker: str | None = None, company_name: str | None = None,
                 document_url: str | None = None) -> None:
    import json

    client = _redis()
    if client is None:
        return
    payload = {**result, "company_number": company_number, "company_name": company_name,
               "made_up_to": made_up_to, "document_url": document_url}
    key = cache_key(company_number, made_up_to)
    try:
        client.set(key, json.dumps(payload, ensure_ascii=False, default=str), ex=CACHE_TTL_S)
        client.delete(key + ":pending")
        if ticker:
            index = f"{CACHE_PREFIX}:ticker:{ticker.upper()}"
            client.hset(index, company_number, key)
            client.expire(index, CACHE_TTL_S)
    except Exception:  # noqa: BLE001
        return


def claim_pending(company_number: str, made_up_to: str | None) -> bool:
    """True si nadie esta leyendo ya estas cuentas (evita encolar dos OCR iguales)."""
    client = _redis()
    if client is None:
        return False
    try:
        return bool(client.set(cache_key(company_number, made_up_to) + ":pending", "1", nx=True, ex=PENDING_TTL_S))
    except Exception:  # noqa: BLE001
        return False


def for_ticker(ticker: str) -> list[dict[str, Any]]:
    """Lecturas ya hechas de las cuentas britanicas ligadas a un ticker (solo cache, sin red)."""
    import json

    client = _redis()
    if client is None or not ticker:
        return []
    try:
        keys = client.hvals(f"{CACHE_PREFIX}:ticker:{ticker.upper()}") or []
        raws = client.mget([k.decode() if isinstance(k, bytes) else k for k in keys]) if keys else []
    except Exception:  # noqa: BLE001
        return []
    out = [json.loads(r) for r in raws if r]
    out.sort(key=lambda r: (str(r.get("company_name") or ""), str(r.get("made_up_to") or "")))
    return out


def page_url(document_url: str | None, page: int | None) -> str | None:
    """Enlace a la pagina citada (el visor de PDF del navegador abre ``#page=N``)."""
    if not document_url:
        return None
    return f"{document_url.split('#', 1)[0]}#page={page}" if page else document_url


def _allowed(url: str) -> bool:
    import httpx

    host = httpx.URL(url).host
    return host in _DOC_HOSTS or (host.endswith(_S3_HOST_SUFFIX) and "document-api-images" in url)


def download_public_pdf(url: str, *, client: Any = None, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    """PDF de un deposito por su URL publica de Companies House (302 a un enlace firmado)."""
    import httpx

    if not _allowed(url):
        raise ValueError("la URL no es un documento de Companies House")
    own = client is None
    http = client or httpx.Client(timeout=60.0, follow_redirects=False,
                                  headers={"User-Agent": "GerarAI/1.0 (tab@tab.bot)", "Accept": "application/pdf"})
    try:
        resp = http.get(url)
        for _ in range(3):
            if resp.status_code not in (301, 302, 303, 307):
                break
            target = resp.headers.get("location") or ""
            if not _allowed(target):
                raise ValueError("redireccion fuera de Companies House")
            resp = http.get(target)
        if resp.status_code != 200:
            raise ValueError(f"documento {resp.status_code}")
        if len(resp.content) > max_bytes:
            raise ValueError("documento demasiado grande")
        return resp.content
    finally:
        if own:
            http.close()


def read_and_cache(company_number: str, made_up_to: str | None, document_url: str, *,
                   ticker: str | None = None, company_name: str | None = None,
                   fetch: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    """Descarga, lee y guarda en cache unas cuentas escaneadas (trabajo del worker)."""
    data = (fetch or download_public_pdf)(document_url)
    result = extract_from_pdf(data)
    if result.get("status") != "unavailable":
        store_cached(company_number, made_up_to, result, ticker=ticker, company_name=company_name,
                     document_url=document_url)
    return result


__all__ = [
    "BALANCE", "INCOME", "PdfPages", "Statement", "balance_check", "classify_heading", "extract_from_pages",
    "extract_from_pdf", "figures_from_statements", "income_check", "locate_statements", "ocr_png", "parse_line",
    "parse_period", "parse_statement", "parse_units", "tesseract_available", "cache_key", "load_cached",
    "store_cached", "claim_pending", "for_ticker", "page_url", "download_public_pdf", "read_and_cache",
]
