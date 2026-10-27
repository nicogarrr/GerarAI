"""Read-only publication gate for consumers of persisted thesis prose.

Match the research-page publication gate: a latest stored model must be
publishable (missing evidence fails closed). Do not fall back to an older publishable model or recalculate.
"""
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import FundamentalModelVersion, ThesisVersion
from app.schemas.api import VALUATION_WITHHELD_REASON, valuation_uses_inferred_inputs

MODEL_WITHHELD_REASON = "El modelo no es publicable; el texto y las cifras archivados no son análisis actual."


def thesis_withheld_reasons(db: Session, theses: list[ThesisVersion]) -> dict[int, str | None]:
    """Batch lookup keeps whole-vault export independent of company count."""
    if not theses:
        return {}
    pairs = {(thesis.tenant_id, thesis.company_id) for thesis in theses}
    rows = db.scalars(select(FundamentalModelVersion).where(
        FundamentalModelVersion.company_id.in_({company_id for _, company_id in pairs}),
        or_(FundamentalModelVersion.tenant_id.in_({tenant_id for tenant_id, _ in pairs if tenant_id is not None}),
            FundamentalModelVersion.tenant_id.is_(None) if any(tenant_id is None for tenant_id, _ in pairs) else False),
    ).order_by(desc(FundamentalModelVersion.version))).all()
    latest = {}
    for row in rows:
        latest.setdefault((row.tenant_id, row.company_id), row)
    reasons = {}
    for thesis in theses:
        model = latest.get((thesis.tenant_id, thesis.company_id))
        if model is None:
            reason = "No hay un modelo publicable verificado; el texto y las cifras archivados no son análisis actual."
        elif not model.publishable:
            reason = MODEL_WITHHELD_REASON
        elif valuation_uses_inferred_inputs(thesis.valuation_basis):
            reason = VALUATION_WITHHELD_REASON
        else:
            reason = None
        reasons[thesis.id] = reason
    return reasons


def thesis_withheld_reason(db: Session, thesis: ThesisVersion) -> str | None:
    return thesis_withheld_reasons(db, [thesis])[thesis.id]


def archived_thesis_notice(thesis: ThesisVersion, reason: str) -> str:
    stamp = thesis.created_at.date().isoformat() if thesis.created_at else "fecha sin verificar"
    return f"Tesis archivada v{thesis.version} ({stamp}): {reason}"
