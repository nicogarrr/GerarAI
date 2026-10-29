"""Eligibility of four reviewed PDF transcriptions, not a general manual override."""

from decimal import Decimal

from app.services.esef_fact_quarantine import EBRO_LEI, EBRO_PDF, LOG_LEI, LOG_PDF

SOURCE_TYPE = "REVIEWED_PDF_ADJUSTMENT"
REVIEW_ID = "esef-eps-primary-pdf-20261029-v1"
REVIEWED = {
    (EBRO_LEI, "2024-12-31:FY", Decimal("1.351")): (
        EBRO_PDF,
        "60b4dd1bf9d894fb14bb496b4f16ed72add65470bd4fb03be84039e995784d58",
        12,
    ),
    (EBRO_LEI, "2023-12-31:FY", Decimal("1.215")): (
        EBRO_PDF,
        "60b4dd1bf9d894fb14bb496b4f16ed72add65470bd4fb03be84039e995784d58",
        12,
    ),
    (LOG_LEI, "2025-09-30:FY", Decimal("2.13")): (
        LOG_PDF,
        "058a7060f8946de98b6d3c6071639e35ba9656df039c3abbf30173cfc793ac2c",
        37,
    ),
    (LOG_LEI, "2024-09-30:FY", Decimal("2.34")): (
        LOG_PDF,
        "058a7060f8946de98b6d3c6071639e35ba9656df039c3abbf30173cfc793ac2c",
        37,
    ),
}
NOTE = "BPA ajustado: transcripción revisada del PDF anual del emisor; conserva la fila ESEF original en cuarentena."


def is_reviewed_eps_adjustment(fact) -> bool:
    if fact.source_type != SOURCE_TYPE or fact.metric != "eps_diluted":
        return False
    if fact.is_reported or not fact.is_adjusted or fact.unit != "EUR/share":
        return False
    source = fact.source
    if source is None or source.company_id != fact.company_id or source.tenant_id != fact.tenant_id:
        return False
    if source.source_type != SOURCE_TYPE:
        return False
    meta = source.metadata_ or {}
    if meta.get("review_id") != REVIEW_ID:
        return False
    try:
        expected = REVIEWED.get((str(meta.get("lei")), fact.period, Decimal(str(fact.value))))
    except (ValueError, ArithmeticError):
        return False
    if expected is None or fact.fiscal_year != int(fact.period[:4]) or fact.fiscal_quarter != "FY":
        return False
    url, checksum, page = expected
    return source.source_url == url and source.checksum == checksum and meta.get("pdf_page") == page


def eligible_fact(fact) -> bool:
    """Other sources retain their own policies; this source is closed by default."""
    return fact.source_type != SOURCE_TYPE or is_reviewed_eps_adjustment(fact)


def select_watchlist_eps(candidates):
    """Preserve newest-first contract except the exact quarantined issuer."""
    from app.services.esef_fact_quarantine import fact_quarantine_reason

    usable = [row for row in candidates if eligible_fact(row)]
    first = next(iter(usable), None)
    if first is None or not fact_quarantine_reason(first):
        return first
    lei = (first.source.metadata_ or {}).get("lei") if first.source else None
    reviewed = [
        row for row in usable if is_reviewed_eps_adjustment(row) and row.source.metadata_.get("lei") == lei
    ]
    return max(reviewed, key=lambda row: row.fiscal_year) if reviewed else first
