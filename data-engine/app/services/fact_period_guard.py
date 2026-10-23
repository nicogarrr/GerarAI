"""Guarda compartida del corte de periodo de un hecho (puente y reconcile).

fact.period es una cadena de ingesta; por si sola no prueba el corte. Aqui el corte solo vale si:
- el hecho esta anclado a un filing SEC (accession_number con formato valido; el ``end`` de
  companyfacts es el cierre del periodo en el XBRL de ese filing);
- el sufijo ':Qn'/':FY' coincide con el periodo fiscal explicito del hecho;
- el cierre reproduce ese trimestre con las MISMAS funciones de la ingesta y el mes de cierre
  fiscal de la propia compania (derivado de sus hechos FY anclados por accession);
- el ano del corte esta a +-1 del ano fiscal explicito.
Sin alguno de ellos -> falla cerrado (solo contexto). No se reverifica el ``end`` contra el filing
(sin red) ni se infiere calendario fiscal: sin mes de cierre anclado, no hay veredicto.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from datetime import date

_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")


def fiscal_end_month_from_anchored_fy(facts: Iterable) -> str | None:
    """Mes de cierre fiscal (moda) desde hechos FY SEC con accession y periodo 'YYYY-MM-DD:FY'."""
    from app.services.financial_ingestion_service import _normalized_fiscal_month

    months: Counter[str] = Counter()
    for f in facts:
        period = getattr(f, "period", None) or ""
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}):FY", period)
        if (not m or getattr(f, "fiscal_quarter", None) != "FY"
                or getattr(f, "source_type", None) != "SEC"
                or not _ACCESSION.fullmatch(getattr(f, "accession_number", None) or "")):
            continue
        month = _normalized_fiscal_month(m[1])
        if month:
            months[month] += 1
    top = months.most_common(2)
    if not top or (len(top) > 1 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def anchored_period_end(
    fact_period: str | None, quarter: str, year: int, *,
    accession: str | None, fiscal_end_month: str | None,
) -> date | None:
    """UNICO parser del corte: devuelve la fecha solo si pasa todas las condiciones del modulo;
    None = sin corte anclado (contexto, nunca veredicto)."""
    from app.services.financial_ingestion_service import (
        _fiscal_quarter_from_end,
        _normalized_fiscal_month,
    )

    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}):(Q[1-4]|FY)", fact_period or "")
    if (not m or m[4] != quarter or not fiscal_end_month
            or not _ACCESSION.fullmatch(accession or "")):
        return None
    try:
        end = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    if abs(end.year - year) > 1:
        return None
    if quarter == "FY":
        ok = _normalized_fiscal_month(end.isoformat()) == fiscal_end_month
    else:
        ok = _fiscal_quarter_from_end(end.isoformat(), fiscal_end_month) == quarter
    return end if ok else None
