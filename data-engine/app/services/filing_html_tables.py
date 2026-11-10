"""Lector determinista de tablas HTML de un filing: una fila con etiqueta conocida en columnas anuales.

Algunas cifras que las gestoras dan como total solo están en el HTML del informe anual, sin hecho XBRL: el
beneficio distribuible total de Brookfield (BN, 40-F 2025, ``bn-20251231_d2.htm``: «Distributable earnings
6,008 / 6,274» bajo «FOR THE YEARS ENDED DEC. 31 (MILLIONS)»; el XBRL solo lo etiqueta por segmento).

Reglas (generales, sin red, puras):

- la cabecera de la tabla declara un periodo anual («year(s) ended <mes> <día>», sin «three/six/nine months»
  ni «last twelve months» en la misma columna) y una fila de años de 4 cifras;
- la escala sale de la propia tabla («millions» / «thousands» / «billions»); sin escala la tabla solo sirve para
  confirmar, nunca da la cifra;
- la fila se reconoce por su etiqueta exacta (más un número de nota opcional), nunca por parecido;
- negativos entre paréntesis, «—» es un cero presentado;
- si dos tablas dan cifras distintas para el mismo año, N/D con motivo (no se elige una).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import html as lxml_html

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_YEAR = re.compile(r"^(19|20)\d{2}$")
_ANNUAL = re.compile(r"\byears?\s+ended\s+([a-z]{3})[a-z]*\.?\s+(\d{1,2})\b", re.I)
_INTERIM = re.compile(r"\b(three|six|nine|twelve)\s+months\b|\blast\s+twelve\b|\bquarter\b", re.I)
_SCALES = (("billion", Decimal(1_000_000_000)), ("million", Decimal(1_000_000)), ("thousand", Decimal(1_000)))
_FOOTNOTE = r"(?:\s*\(?\d{1,2}\)?(?:\s*,\s*\d{1,2})*)?"


@dataclass(frozen=True)
class RowRule:
    """Etiqueta exacta (sin mayúsculas ni nota) de la fila que da ``metric``."""

    metric: str
    labels: tuple[str, ...]

    def matches(self, label: str) -> bool:
        text = " ".join(label.replace("\xa0", " ").split()).lower()
        return any(re.fullmatch(re.escape(lab) + _FOOTNOTE, text) for lab in self.labels)


ROW_RULES: tuple[RowRule, ...] = (
    # «Distributable earnings» total: NO «before realizations» ni «per share» ni partes por segmento.
    RowRule("distributable_earnings", ("distributable earnings",)),
    RowRule("fee_related_earnings", ("fee related earnings", "fee-related earnings")),
)


@dataclass
class TableValue:
    metric: str
    start: str
    end: str
    value: Decimal
    table: int
    label: str
    scale: str


@dataclass
class Found:
    metric: str
    values: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    conflict: str | None = None


def _cells(tr: Any) -> list[str]:
    out: list[str] = []
    for cell in tr.xpath("./td|./th"):
        text = " ".join(cell.text_content().replace("\xa0", " ").split())
        if text in ("", "$", "US$", "C$", "€", "£"):
            continue
        if text == ")" and out:
            out[-1] = out[-1] + ")"
            continue
        out.append(text)
    return out


def _number(text: str) -> Decimal | None:
    t = text.replace("$", "").replace(",", "").replace(" ", "")
    if t in ("—", "–", "-"):
        return Decimal(0)
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    if not v.is_finite():
        return None
    return -v if neg else v


def _header(rows: list[list[str]]) -> tuple[tuple[int, int] | None, list[int] | None, str | None, int]:
    """(mes, día) del periodo anual, años por columna, escala y nº de filas de cabecera."""
    month_day: tuple[int, int] | None = None
    years: list[int] | None = None
    scale: str | None = None
    for i, cells in enumerate(rows[:6]):
        joined = " ".join(cells)
        low = joined.lower()
        for word, _mult in _SCALES:
            if word in low and scale is None:
                scale = word
        m = _ANNUAL.search(joined)
        if m and not _INTERIM.search(joined) and m.group(1).lower()[:3] in _MONTHS:
            month_day = (_MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        ys = [c for c in cells if _YEAR.match(c)]
        if ys and len(ys) == len([c for c in cells if _number(c) is not None]):
            years = [int(y) for y in ys]
            return month_day, years, scale, i + 1
    return month_day, years, scale, 0


def _period(year: int, month_day: tuple[int, int]) -> tuple[str, str] | None:
    try:
        end = date(year, *month_day)
        prev = date(year - 1, *month_day)
    except ValueError:
        return None
    return (prev + timedelta(days=1)).isoformat(), end.isoformat()


def read_annual_rows(document: bytes | str, rules: tuple[RowRule, ...] = ROW_RULES) -> list[TableValue]:
    """Todas las celdas anuales de las filas reconocidas, tabla a tabla (sin decidir aún entre tablas)."""
    root = lxml_html.fromstring(document)
    out: list[TableValue] = []
    for t_index, table in enumerate(root.iter("table")):
        rows = [c for c in (_cells(tr) for tr in table.iter("tr")) if c]
        month_day, years, scale, body_from = _header(rows)
        if not month_day or not years:
            continue
        for cells in rows[body_from:]:
            label, nums = cells[0], [_number(c) for c in cells[1:]]
            rule = next((r for r in rules if r.matches(label)), None)
            if rule is None or len(nums) != len(years) or any(n is None for n in nums):
                continue
            for year, num in zip(years, nums, strict=True):
                period = _period(year, month_day)
                if period is not None and num is not None:
                    out.append(TableValue(rule.metric, period[0], period[1], num, t_index, label, scale or ""))
    return out


def resolve(document: bytes | str, metrics: list[str], *, source: str) -> dict[str, Found]:
    """Cifras anuales por métrica: las tablas con escala dan la cifra; todas las tablas deben coincidir."""
    cells = [c for c in read_annual_rows(document) if c.metric in metrics]
    found: dict[str, Found] = {}
    for metric in metrics:
        mine = [c for c in cells if c.metric == metric]
        scaled = [c for c in mine if c.scale]
        if not scaled:
            continue
        mult = dict(_SCALES)
        f = Found(metric)
        for c in scaled:
            key, val = (c.start, c.end), c.value * mult[c.scale]
            if key in f.values and f.values[key] != val:
                f.conflict = f"«{c.label}» {c.end}: {f.values[key]} frente a {val} en otra tabla de {source}"
            f.values.setdefault(key, val)
        # Las tablas sin escala solo confirman: si su número no casa con la cifra en la misma unidad, conflicto.
        for c in mine:
            if not c.scale:
                ref = next((s for s in scaled if (s.start, s.end) == (c.start, c.end)), None)
                if ref is not None and ref.value != c.value:
                    f.conflict = f"«{c.label}» {c.end}: {ref.value} frente a {c.value} en otra tabla de {source}"
        f.evidence = sorted({f"tabla {c.table}: «{c.label}» ({c.scale or 'sin escala'})" for c in mine})
        found[metric] = f
    return found
