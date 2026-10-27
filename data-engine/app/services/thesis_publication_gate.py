"""Read-only publication gate for consumers of persisted thesis prose.

Match the research-page publication gate: a latest stored model must be
publishable (missing evidence fails closed). Do not fall back to an older publishable model or recalculate.
"""
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import FundamentalModelVersion, ThesisVersion
from app.schemas.api import VALUATION_WITHHELD_REASON, valuation_uses_inferred_inputs

MODEL_WITHHELD_REASON = "El modelo no es publicable; el texto y las cifras archivados no son análisis actual."


def model_withheld_reason(thesis: ThesisVersion, model: FundamentalModelVersion | None) -> str | None:
    if model is None:
        return "No hay un modelo publicable verificado; el texto y las cifras archivados no son análisis actual."
    if not model.publishable:
        return MODEL_WITHHELD_REASON
    if valuation_uses_inferred_inputs(thesis.valuation_basis):
        return VALUATION_WITHHELD_REASON
    return None


def withhold_thesis_payload(payload: dict, thesis: ThesisVersion, reason: str | None) -> dict:
    """Sanitize a detached response, never an ORM row or persisted archive."""
    if not reason:
        return payload
    payload = dict(payload)
    for key in ("bear_value", "base_value", "bull_value", "expected_value", "margin_of_safety",
                "archived_margin_of_safety", "margin_of_safety_convention", "hypothesis", "catalysts",
                "invalidation_criteria", "invalidation_rules", "scenario_probabilities", "narrative_sections"):
        if key in payload:
            payload[key] = None
    payload["rating"] = "insufficient_data"
    payload["margin_of_safety_status"] = "withheld"
    payload["executive_summary"] = archived_thesis_notice(thesis, reason)
    if "thesis_markdown" in payload:
        payload["thesis_markdown"] = payload["executive_summary"]
    if "valuation_withheld_reason" in payload:
        payload["valuation_withheld_reason"] = reason
    return payload


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
        reason = model_withheld_reason(thesis, model)
        reasons[thesis.id] = reason
    return reasons


def thesis_withheld_reason(db: Session, thesis: ThesisVersion) -> str | None:
    return thesis_withheld_reasons(db, [thesis])[thesis.id]


def archived_thesis_notice(thesis: ThesisVersion, reason: str) -> str:
    stamp = thesis.created_at.date().isoformat() if thesis.created_at else "fecha sin verificar"
    return f"Tesis archivada v{thesis.version} ({stamp}): {reason}"
