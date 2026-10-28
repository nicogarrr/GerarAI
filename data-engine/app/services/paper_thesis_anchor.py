"""Tesis vigente que ancla una propuesta del paper book (solo lectura).

Una propuesta simulada evalúa una hipótesis sobre la empresa, así que se guarda
con la última ThesisVersion del tenant para ese ticker (la misma que muestran la
ficha y el Cerebro) en vez de flotar como texto suelto. Al modelo solo le llega
lo que la puerta de publicación deja mostrar: una tesis retenida viaja sin
cifras ni criterios, solo con versión, fecha y motivo.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Company, ThesisVersion
from app.models.paper_trading import PaperTrade
from app.services.claim_scope import latest_thesis_version
from app.services.thesis_publication_gate import thesis_withheld_reason

SUMMARY_LIMIT = 1200
MAX_INVALIDATION = 5


def current_thesis(db: Session, ticker: str) -> ThesisVersion | None:
    company = db.scalar(select(Company).where(Company.ticker == ticker.strip().upper()))
    return latest_thesis_version(db, company) if company is not None else None


def thesis_anchors(db: Session, trades: Sequence[PaperTrade]) -> dict[int, dict]:
    """Versión anclada de cada trade y si la tesis ha cambiado desde entonces.

    Dos lecturas por página, no una por trade. ``superseded`` compara con la
    última versión del tenant para la misma empresa: la simulación sigue
    evaluando la tesis antigua y la UI debe decirlo.
    """
    ids = {trade.thesis_version_id for trade in trades if trade.thesis_version_id is not None}
    if not ids:
        return {}
    anchored = {row.id: row for row in db.scalars(select(ThesisVersion).where(ThesisVersion.id.in_(ids)))}
    company_ids = {row.company_id for row in anchored.values()}
    latest = {
        company_id: version
        for company_id, version in db.execute(
            select(ThesisVersion.company_id, func.max(ThesisVersion.version))
            .where(ThesisVersion.company_id.in_(company_ids), *tenant_filters(db, ThesisVersion))
            .group_by(ThesisVersion.company_id)
        ).all()
    }
    return {
        thesis_id: {
            "id": row.id,
            "version": row.version,
            "created_at": row.created_at,
            "latest_version": latest.get(row.company_id, row.version),
            "superseded": latest.get(row.company_id, row.version) > row.version,
        }
        for thesis_id, row in anchored.items()
    }


def thesis_evidence_id(thesis_id: int) -> str:
    return f"thesis:{thesis_id}"


def _decimal(value) -> str | None:
    return str(value) if value is not None else None


def prompt_context(db: Session, thesis: ThesisVersion) -> dict:
    """Copia escalar de lo publicable: la sesión se libera antes de la red."""
    context: dict = {
        "id": thesis_evidence_id(thesis.id),
        "version": thesis.version,
        "fecha": thesis.created_at.date().isoformat() if thesis.created_at else None,
    }
    reason = thesis_withheld_reason(db, thesis)
    if reason:
        return {**context, "publicable": False, "motivo": reason}
    criteria = [c.strip() for c in (thesis.invalidation_criteria or []) if isinstance(c, str) and c.strip()]
    return {
        **context,
        "publicable": True,
        "rating": thesis.rating,
        "resumen": (thesis.executive_summary or "").strip()[:SUMMARY_LIMIT],
        "precio_en_tesis": _decimal(thesis.current_price),
        "valor_bajista": _decimal(thesis.bear_value),
        "valor_base": _decimal(thesis.base_value),
        "valor_alcista": _decimal(thesis.bull_value),
        "valor_esperado": _decimal(thesis.expected_value),
        "margen_sobre_valor_esperado": _decimal(thesis.margin_of_safety),
        "invalidacion": criteria[:MAX_INVALIDATION],
    }
