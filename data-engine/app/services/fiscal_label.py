"""Etiqueta del ejercicio fiscal según el propio emisor (dei:DocumentFiscalYearFocus).

Los ejercicios de 52/53 semanas que cierran a finales de enero o principios de febrero se nombran de
dos maneras: unos por el año del cierre (Walmart, NVIDIA: el que cierra el 31-ene-2026 es «fiscal 2026»)
y otros por el año en que empiezan (Home Depot, Target, Lowe's: el que cierra el 30-ene-2026 es
«fiscal 2025»). La fecha de cierre no distingue los dos casos; el filing sí: cada 10-K declara su
``dei:DocumentFiscalYearFocus``, que companyfacts copia en el campo ``fy`` de todos los hechos del filing.

Regla (general, sin lista de emisores): en los informes anuales recientes, el desfase del emisor es
``año nominal del cierre del propio periodo del filing − DocumentFiscalYearFocus`` (el periodo propio es el
ejercicio que más tarde cierra ANTES de presentarse el filing). El 1 (año de inicio) exige que lo declaren
los dos últimos ejercicios distintos (sin contar enmiendas dos veces) y un cierre nominal entre enero y junio; en cualquier otro caso, 0 (la
etiqueta de siempre: el año nominal del cierre). Así manda la convención vigente: un emisor que corrigió su
etiqueta (CrowdStrike: FY2024 → FY2026 para cierres de enero de 2025 y 2026) o un filing suelto mal
etiquetado no mueven la historia.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

#: Un cierre en los primeros días de un mes pertenece al mes anterior (calendarios de 52/53 semanas).
WEEKLY_CALENDAR_DAYS = 7
ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A"})
ALLOWED_OFFSETS = (0, 1)
#: Últimos ejercicios distintos que tienen que declarar el año de inicio.
MIN_FILINGS_FOR_SHIFT = 2


def nominal_month(end: date) -> tuple[int, int]:
    """(año, mes) al que pertenece un cierre: el mismo mes, o el anterior si cae en sus primeros 7 días.

    Regla única del calendario 52/53 semanas; la usan también el consenso propio y la etiqueta dei."""
    if end.day <= WEEKLY_CALENDAR_DAYS:
        prev = end.replace(day=1) - timedelta(days=1)
        return prev.year, prev.month
    return end.year, end.month


def nominal_year(end: date) -> int:
    """Año del mes al que pertenece un cierre (el anterior si cae en sus primeros 7 días)."""
    return nominal_month(end)[0]


def _iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _majority(offsets: list[int]) -> int:
    if not offsets:
        return 0
    value, count = Counter(offsets).most_common(1)[0]
    return value if count * 2 > len(offsets) else 0


def filing_offsets(us_gaap: Mapping[str, Any]) -> list[tuple[date, int, str]]:
    """(cierre propio, desfase, nº de acceso) de cada informe anual de companyfacts.

    El periodo propio de un filing es el ejercicio (300–380 días) que más tarde cierra entre sus hechos
    de flujo; las comparativas de años anteriores heredan el ``fy`` del filing y por eso no votan."""
    own: dict[str, tuple[date, int]] = {}
    for concept in us_gaap.values():
        for entries in ((concept or {}).get("units") or {}).values():
            for e in entries or ():
                if e.get("fp") != "FY" or e.get("form") not in ANNUAL_FORMS or not e.get("accn"):
                    continue
                start, end, filed = _iso(e.get("start")), _iso(e.get("end")), _iso(e.get("filed"))
                if start is None or end is None or not 300 <= (end - start).days <= 380:
                    continue
                if filed is not None and end >= filed:
                    continue  # hechos con fecha futura (coberturas, compromisos): no son el periodo del filing
                try:
                    fy = int(e.get("fy"))
                except (TypeError, ValueError):
                    continue
                cur = own.get(e["accn"])
                if cur is None or end > cur[0]:
                    own[e["accn"]] = (end, fy)
    out = [(end, nominal_year(end) - fy, accn) for accn, (end, fy) in own.items()]
    return sorted(out, reverse=True)


def _admissible(end: date, offset: int) -> bool:
    """0 siempre; 1 solo si el ejercicio cierra en la primera mitad del año (nominal enero–junio): la mayor
    parte cae en el año anterior. Un cierre en diciembre «del año anterior» es un error de etiquetado."""
    if offset == 0:
        return True
    return offset == 1 and _nominal_month(end) <= 6


def _nominal_month(end: date) -> int:
    return nominal_month(end)[1]


def dei_label_offset(us_gaap: Mapping[str, Any]) -> int:
    """Desfase de la etiqueta del ejercicio del emisor (0: año del cierre; 1: año de inicio).

    Manda la convención vigente: 1 solo si los DOS últimos ejercicios distintos la declaran.
    Las enmiendas del mismo cierre no son confirmaciones independientes; si discrepan,
    ese cierre no confirma el desfase. Si no se confirma, 0."""
    by_end: dict[date, set[int]] = {}
    for end, offset, _accn in filing_offsets(us_gaap):
        by_end.setdefault(end, set()).add(offset)
    recent = sorted(by_end, reverse=True)[:MIN_FILINGS_FOR_SHIFT]
    if len(recent) == MIN_FILINGS_FOR_SHIFT and all(
        by_end[end] == {1} and _admissible(end, 1) for end in recent
    ):
        return 1
    return 0


def label_offset_from_facts(pairs: Iterable[tuple[date | str, int | None]]) -> int:
    """El mismo desfase leído de hechos anuales ya guardados: (cierre, fiscal_year)."""
    offsets: list[int] = []
    for end, fiscal_year in pairs:
        d = end if isinstance(end, date) else _iso(end)
        if d is None or fiscal_year is None:
            continue
        o = nominal_year(d) - int(fiscal_year)
        if o in ALLOWED_OFFSETS and _admissible(d, o):
            offsets.append(o)
    return _majority(offsets)
