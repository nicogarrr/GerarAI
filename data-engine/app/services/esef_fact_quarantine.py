"""Read-only quarantine of reviewed ESEF EPS conflicts, never rescale by size.

The issuer's FY2024 PDF reports EPS EUR1.351/1.215, while its inline file
labels comma-decimal text as num-dot-decimal and canonical JSON says1351/1215.
The raw record is preserved. This is an exact reviewed conflict register, not
an EPS plausibility threshold. Period aliases cover the old exclusive-date
parser bug. Add entries only with primary evidence.
"""
from __future__ import annotations

from decimal import Decimal

LOG_LEI = "9598000ANNAL42UJ7X28"
LOG_PDF = "https://www.logista.com/content/dam/documents/logista-corporate/economic-financial-information/financial-reports/en/3.%20Consolidated%20Report%20-%20Logista%20%20FY25.pdf"
EBRO_LEI = "959800NW6DLQT89M3240"
EBRO_PDF = "https://www.ebrofoods.es/wp-content/uploads/informe_anual/informeanual2024/pdf/3-5-0-cuentas-anuales-consolidadas.pdf"
EPS_CONCEPTS = frozenset({
    "ifrs-full:BasicEarningsLossPerShare",
    "ifrs-full:DilutedEarningsLossPerShare",
    "ifrs-full:BasicEarningsLossPerShareFromContinuingOperations",
    "ifrs-full:DilutedEarningsLossPerShareFromContinuingOperations",
})
# LEI, inclusive or historically misparsed end, canonical source value.
CONFLICTS = frozenset({
    (EBRO_LEI, "2024-12-31", Decimal("1351")),
    (EBRO_LEI, "2025-01-01", Decimal("1351")),
    (EBRO_LEI, "2023-12-31", Decimal("1215")),
    (EBRO_LEI, "2024-01-01", Decimal("1215")),
    # Logista FY2025 package declares EPS scale=3, while its audited PDF
    # reports 2.13/2.34 euros per share, not 2130/2340.
    (LOG_LEI, "2025-09-30", Decimal("2130")),
    (LOG_LEI, "2025-10-01", Decimal("2130")),
    (LOG_LEI, "2024-09-30", Decimal("2340")),
    (LOG_LEI, "2024-10-01", Decimal("2340")),
})
REASON = "BPA ESEF en cuarentena: escala incompatible con el informe anual del emisor; no se calcula el PER."


def reviewed_eps_conflict(lei: str, period: str, concept: str, value: object) -> bool:
    if concept not in EPS_CONCEPTS:
        return False
    try:
        return (lei, str(period)[:10], Decimal(str(value))) in CONFLICTS
    except (ValueError, ArithmeticError):
        return False


def fact_quarantine_reason(fact) -> str | None:
    if fact.source_type != "ESEF":
        return None
    source = fact.source
    metadata = source.metadata_ if source is not None else {}
    metadata = metadata or {}
    lei = str(metadata.get("lei") or "")
    metric = fact.metric
    concept = {"eps_diluted": "ifrs-full:DilutedEarningsLossPerShare",
               "eps_basic": "ifrs-full:BasicEarningsLossPerShare"}.get(metric)
    if concept and reviewed_eps_conflict(lei, fact.period, concept, fact.value):
        return REASON
    # Previously persisted shares derived from precisely the same bad EPS
    # are not safe DCF inputs either. Match source lineage, period AND value.
    if metric in {"shares_diluted", "shares_basic_derived"} and not fact.is_reported:
        for entry in (metadata.get("esef_shares") or {}).get("derived", []):
            if str(entry.get("period"))[:10] != str(fact.period)[:10]:
                continue
            if str(entry.get("shares")) != str(int(fact.value)):
                continue
            if reviewed_eps_conflict(lei, fact.period, "ifrs-full:DilutedEarningsLossPerShare", entry.get("eps")):
                return REASON
    return None
