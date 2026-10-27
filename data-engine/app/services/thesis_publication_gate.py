"""Read-only publication gate for consumers of persisted thesis prose.

Match the research-page publication gate: a latest stored model must be
publishable (missing evidence fails closed). Do not fall back to an older publishable model or recalculate.
"""
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import FundamentalModelVersion, ThesisVersion
from app.schemas.api import VALUATION_WITHHELD_REASON, valuation_uses_inferred_inputs

MODEL_WITHHELD_REASON = "El modelo no es publicable; el texto y las cifras archivados no son análisis actual."


def thesis_withheld_reason(db: Session, thesis: ThesisVersion) -> str | None:
    model = db.scalar(
        select(FundamentalModelVersion)
        .where(FundamentalModelVersion.company_id == thesis.company_id,
               FundamentalModelVersion.tenant_id == thesis.tenant_id)
        .order_by(desc(FundamentalModelVersion.version)).limit(1)
    )
    if model is None:
        return "No hay un modelo publicable verificado; el texto y las cifras archivados no son análisis actual."
    if not model.publishable:
        return MODEL_WITHHELD_REASON
    if valuation_uses_inferred_inputs(thesis.valuation_basis):
        return VALUATION_WITHHELD_REASON
    return None


def archived_thesis_notice(thesis: ThesisVersion, reason: str) -> str:
    stamp = thesis.created_at.date().isoformat() if thesis.created_at else "fecha sin verificar"
    return f"Tesis archivada v{thesis.version} ({stamp}): {reason}"
