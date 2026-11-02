"""Read-only publication gate for consumers of persisted thesis prose.

Match the research-page publication gate: a latest stored model must be
publishable (missing evidence fails closed). Do not fall back to an older publishable model or recalculate.
"""
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import FundamentalModelVersion, ThesisVersion
from app.schemas.api import VALUATION_WITHHELD_REASON, valuation_uses_inferred_inputs

MODEL_WITHHELD_REASON = "El modelo no es publicable; el texto y las cifras archivados no son análisis actual."
NO_MODEL_WITHHELD_REASON = "No hay un modelo publicable verificado; el texto y las cifras archivados no son análisis actual."

# Mismos motivos en inglés, para quien eligió inglés en Ajustes (el valor
# guardado/comparado sigue siendo el castellano de arriba).
_WITHHELD_REASONS_EN = {
    MODEL_WITHHELD_REASON: "The model is not publishable; the archived text and figures are not current analysis.",
    NO_MODEL_WITHHELD_REASON: (
        "There is no verified publishable model; the archived text and figures are not current analysis."
    ),
    VALUATION_WITHHELD_REASON: (
        "Valuation not available: sourced modelled revenue is missing. The model could only be "
        "calculated with an unverified assumption, so no per-share value is published."
    ),
}


def withheld_reason_en(reason: str) -> str:
    """Motivo de retención en inglés; uno desconocido se devuelve tal cual (nunca inventado)."""
    return _WITHHELD_REASONS_EN.get(reason, reason)


# Estados con los que la propia tesis declara una valoración publicable o
# publicada. Solo esas cifras necesitan el respaldo de un modelo publicable.
VALUATION_CLAIM_STATUSES = frozenset({"published", "final"})


def _is_current_unpublished_analysis(thesis: ThesisVersion, model: FundamentalModelVersion | None) -> bool:
    """Borrador vigente: no es un archivo y ya se etiqueta solo.

    Una tesis en borrador, parcial o con datos insuficientes no afirma una
    valoración publicable (su propio texto dice «indicativa» o «no publicable»).
    Es vigente si no hay ningún modelo posterior (``model is None``) o si se
    generó con el último modelo (misma huella de entradas). Una tesis que
    afirma valoración publicable, o un borrador superado por un modelo nuevo,
    siguen la puerta estricta.
    """
    if (thesis.status or "draft") in VALUATION_CLAIM_STATUSES:
        return False
    if model is None:
        return True
    linked = (thesis.valuation_basis or {}).get("model_input_fingerprint")
    return bool(linked) and linked == model.input_fingerprint


def model_withheld_reason(thesis: ThesisVersion, model: FundamentalModelVersion | None) -> str | None:
    if _is_current_unpublished_analysis(thesis, model):
        if valuation_uses_inferred_inputs(thesis.valuation_basis):
            return VALUATION_WITHHELD_REASON
        return None
    if model is None:
        return NO_MODEL_WITHHELD_REASON
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


def archived_thesis_notice(thesis: ThesisVersion, reason: str, language: str = "es") -> str:
    """Aviso de tesis archivada; ``language="en"`` (Ajustes) lo da en inglés."""
    if language == "en":
        stamp = thesis.created_at.date().isoformat() if thesis.created_at else "unverified date"
        return f"Archived thesis v{thesis.version} ({stamp}): {withheld_reason_en(reason)}"
    stamp = thesis.created_at.date().isoformat() if thesis.created_at else "fecha sin verificar"
    return f"Tesis archivada v{thesis.version} ({stamp}): {reason}"
