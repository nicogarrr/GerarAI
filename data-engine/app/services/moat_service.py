"""Orquestacion del foso competitivo: evidencia viva -> puntuacion trazable.

Este servicio no inventa ventaja competitiva. Reune las afirmaciones vivas del
scope de tesis, filtra la evidencia por categoria de foso y delega el calculo
en ``app.valuation.moat_framework``, que decide si cada categoria es puntuable
o si debe declararse no evaluable. El contrato publico (claves que leen
``valuation_service``, el red team y el frontend) no cambia: ``moats`` sigue
siendo la lista de categorias con ``strength`` numerico, ahora solo cuando ese
numero existe; las categorias descartadas van aparte, con su estado, en
``unevaluated_moats``.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, MoatAssessment
from app.services.claim_scope import live_claims
from app.services.moat_checklist import moat_checklist
from app.services.moat_classification import classify_result
from app.services.moat_profile import moat_evidence_context
from app.services.source_hierarchy_service import SOURCE_TIERS
from app.valuation.moat_framework import (
    CONTRADICTING_RELATIONS,
    EVIDENCE_BACKED,
    LIMITED_EVIDENCE,
    SCORE_VERSION,
    STATUS_EVIDENCE_BACKED,
    STATUS_NOT_EVALUABLE,
    STATUS_PARTIAL,
    SUPPORTING_RELATIONS,
    CategoryScore,
    EvidenceRef,
    aggregate_strength,
    build_result,
    score_category,
)

#: Terminos que asocian una afirmacion con una categoria de foso.
#:
#: Las afirmaciones se escriben en castellano (``thesis_service`` las genera en
#: castellano y el usuario las escribe asi), asi que una lista solo en ingles
#: no encontraria nunca evidencia real y el foso se quedaria siempre sin
#: evaluar. Las dos familias conviven; la clave de la categoria es la misma de
#: siempre, que es la que mapea ``lib/glossary.ts``.
MOAT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "network_effects": (
        "network effect",
        "two-sided",
        "liquidity",
        "user network",
        "efecto de red",
        "efecto red",
        "doble efecto",
        "liquidez del mercado",
        "red de usuarios",
    ),
    "switching_costs": (
        "switching cost",
        "lock-in",
        "migration",
        "retention",
        "coste de cambio",
        "costos de cambio",
        "cambio de proveedor",
        "fidelizacion",
        "retencion",
        "churn",
        "migracion",
        "integracion profunda",
    ),
    "cost_advantage": (
        "cost advantage",
        "lowest cost",
        "unit cost",
        "procurement",
        "ventaja de costes",
        "ventaja en costes",
        "coste unitario",
        "costo unitario",
        "menor coste",
        "compras",
        "aprovisionamiento",
    ),
    "scale": (
        "scale economy",
        "scale advantage",
        "fixed cost",
        "density",
        "economia de escala",
        "economias de escala",
        "ventaja de escala",
        "coste fijo",
        "costos fijos",
        "densidad",
    ),
    "distribution": (
        "distribution",
        "dealer network",
        "channel",
        "installed base",
        "distribucion",
        "canal de distribucion",
        "red de distribuidores",
        "base instalada",
    ),
    "brand": (
        "brand",
        "pricing power",
        "premium",
        "trust",
        "marca",
        "poder de fijacion de precios",
        "capacidad de fijar precios",
        "premium",
        "confianza del cliente",
        "notoriedad",
    ),
    "regulation": (
        "license",
        "regulatory barrier",
        "spectrum",
        "approval",
        "licencia",
        "licencias",
        "barrera regulatoria",
        "espectro",
        "autorizacion del regulador",
        "aprobacion regulatoria",
    ),
    "data": (
        "data advantage",
        "proprietary data",
        "dataset",
        "ventaja de datos",
        "datos propios",
        "datos propietarios",
        "conjunto de datos",
    ),
    "ecosystem": (
        "ecosystem",
        "platform",
        "developer",
        "integration",
        "ecosistema",
        "plataforma",
        "desarrolladores",
        "integraciones",
    ),
    "capital_barrier": (
        "capital barrier",
        "capital intensive",
        "capex barrier",
        "barrera de capital",
        "intensivo en capital",
        "barrera de capex",
        "requiere enorme capital",
    ),
    "process_advantage": (
        "process advantage",
        "operational excellence",
        "know-how",
        "ventaja de proceso",
        "excelencia operativa",
        "saber hacer",
        "knowhow",
    ),
}

READ_METHODOLOGY = "Persisted source-weighted moat assessments."
ASSESS_METHODOLOGY = (
    "Strength, trend and persistence are derived only from linked claim "
    "evidence weighted by the centralized source hierarchy. A category is "
    "scored only when at least one supporting or contradicting claim carries "
    "primary-source evidence (regulator, company or transcript); evidence from "
    "media, data providers, bootstrap seeds, user input or unknown sources is "
    "reported but never scored."
)

#: Estados de fila persistida que siguen siendo puntuaciones vigentes.
PERSISTED_EVALUATED_STATUSES = frozenset({EVIDENCE_BACKED, LIMITED_EVIDENCE})


def _tier(evidence) -> tuple[str | None, float]:
    """Tier declarado y confianza de la jerarquia; nunca inventar confianza."""
    raw_tier = getattr(evidence, "source_tier", None)
    tier = SOURCE_TIERS.get(str(raw_tier), SOURCE_TIERS["tier_unknown"])
    return raw_tier, float(tier.trust_score)


class MoatService:
    def read(self, db: Session, company: Company) -> dict:
        """Return only persisted assessments; never derive or write on GET."""
        rows = list(
            db.scalars(
                select(MoatAssessment)
                .where(MoatAssessment.company_id == company.id)
                .order_by(MoatAssessment.moat_type)
            ).all()
        )
        moats: list[dict] = []
        evaluated: list[CategoryScore] = []
        excluded: list[dict] = []
        for row in rows:
            trace = dict(row.assessment_trace or {})
            comparable = trace.get("method") == SCORE_VERSION
            payload = {
                "type": row.moat_type,
                "strength": row.strength,
                "trend": row.trend,
                "persistence": row.persistence,
                "confidence": float(row.confidence),
                "status": row.status,
                "supporting_claim_ids": row.supporting_claim_ids,
                "contradicting_claim_ids": row.contradicting_claim_ids,
                "trace": row.assessment_trace,
                "evaluable": comparable and row.status in PERSISTED_EVALUATED_STATUSES,
                "policy": SCORE_VERSION if comparable else "superseded_policy",
            }
            moats.append(payload)
            if comparable and row.status in PERSISTED_EVALUATED_STATUSES:
                evaluated.append(
                    CategoryScore(
                        type=row.moat_type,
                        status=row.status,
                        strength=row.strength,
                        trend=row.trend,
                        persistence=row.persistence,
                        confidence=float(row.confidence),
                        supporting_claim_ids=list(row.supporting_claim_ids or []),
                        contradicting_claim_ids=list(
                            row.contradicting_claim_ids or []
                        ),
                        trace=trace,
                    )
                )
            else:
                # Fila que no es una puntuacion vigente: se muestra (es lo que
                # hay persistido) pero no se mezcla en el agregado actual.
                excluded.append(
                    {
                        "type": row.moat_type,
                        "status": row.status,
                        "reason": (
                            "persisted_under_previous_scoring_policy"
                            if not comparable
                            else "persisted_status_is_not_a_score"
                        ),
                    }
                )
        result = build_result(
            ticker=company.ticker,
            company_type=company.company_type,
            evaluated=evaluated,
            unevaluated=[],
            categories_total=len(moats),
            methodology=READ_METHODOLOGY,
            note=(
                "Puntuaciones persistidas de evaluaciones anteriores. "
                "Reevalua la evidencia para refrescarlas."
            ),
        )
        result["moats"] = moats
        result["categories_total"] = len(moats)
        result["categories_evaluated"] = len(evaluated)
        result["aggregate_strength"] = aggregate_strength(evaluated)
        result["aggregate"].update(
            {
                "strength": result["aggregate_strength"],
                "comparable": result["aggregate_strength"] is not None,
                "evaluated_categories": [
                    item["type"] for item in moats if item["evaluable"]
                ],
                "excluded_categories": excluded,
            }
        )
        result["qualitative_checklist"] = moat_checklist(db, company)
        return classify_result(result)

    def assess(
        self,
        db: Session,
        company: Company,
        *,
        persist: bool = True,
        commit: bool = True,
    ) -> dict:
        # Only the claims of the thesis being assessed. Reading every claim of
        # the company let each regeneration's orphans count towards the moat
        # evidence breadth.
        claims = live_claims(db, company)
        evaluated: list[CategoryScore] = []
        unevaluated: list[CategoryScore] = []
        for moat_type, keywords in MOAT_KEYWORDS.items():
            relevant = [
                claim
                for claim in claims
                if (claim.metadata_ or {}).get("moat_type") == moat_type
                or any(keyword in claim.statement.lower() for keyword in keywords)
            ]
            refs: list[EvidenceRef] = []
            for claim in relevant:
                for evidence in claim.evidence:
                    tier_key, trust_score = _tier(evidence)
                    refs.append(
                        EvidenceRef(
                            claim_id=claim.id,
                            evidence_id=evidence.id,
                            relation=evidence.evidence_type,
                            source_tier=tier_key,
                            trust_score=trust_score,
                            confidence=float(evidence.confidence),
                            document_id=evidence.document_id,
                            document_chunk_id=evidence.document_chunk_id,
                        )
                    )
            claim_trends = tuple(
                str((claim.metadata_ or {}).get("trend", "")) for claim in relevant
            )
            score = score_category(
                moat_type,
                refs,
                claim_trends=claim_trends,
                keywords=keywords,
            )
            if score.evaluable:
                evaluated.append(score)
                # F29: una corrida sin evidencia no es una puntuacion. No se
                # persiste ningun tipo sin evidencia de fuente primaria y nunca
                # se pisa una evaluacion real con ceros: la fila anterior se
                # conserva.
                if persist:
                    self._persist(db, company, score)
            else:
                # Sin score no hay fila: se reporta el estado, no un cero.
                unevaluated.append(score)
        if persist and commit:
            db.commit()
        result = build_result(
            ticker=company.ticker,
            company_type=company.company_type,
            evaluated=evaluated,
            unevaluated=unevaluated,
            categories_total=len(MOAT_KEYWORDS),
            methodology=ASSESS_METHODOLOGY,
            note=(
                "Cada puntuacion es trazable claim por claim en evidence_for, "
                "evidence_against y supporting_claim_ids. Las categorias sin "
                "evidencia de fuente primaria no se puntuan y quedan fuera del "
                "agregado."
            ),
            trace={
                "method": SCORE_VERSION,
                "claims_scanned": len(claims),
                "categories": len(MOAT_KEYWORDS),
                "relations": {
                    "supporting": sorted(SUPPORTING_RELATIONS),
                    "contradicting": sorted(CONTRADICTING_RELATIONS),
                },
                "statuses": {
                    "evidence_backed": STATUS_EVIDENCE_BACKED,
                    "partial_evidence": STATUS_PARTIAL,
                    "not_evaluable": STATUS_NOT_EVALUABLE,
                },
            },
        )
        # Contexto de perfil: informativo. No participa en el score.
        result["profile_context"] = moat_evidence_context(company)
        result["qualitative_checklist"] = moat_checklist(db, company)
        return classify_result(result)

    def _persist(
        self, db: Session, company: Company, payload: CategoryScore
    ) -> MoatAssessment:
        assessment = db.scalar(
            select(MoatAssessment).where(
                MoatAssessment.company_id == company.id,
                MoatAssessment.moat_type == payload.type,
            )
        )
        if assessment is None:
            assessment = MoatAssessment(
                company_id=company.id,
                moat_type=payload.type,
            )
            db.add(assessment)
        # Solo se persisten categorias con score: `strength` no puede ser None
        # aqui porque el servicio no llama a _persist sin evaluabilidad.
        assessment.strength = int(payload.strength or 0)
        assessment.trend = payload.trend
        assessment.persistence = payload.persistence
        assessment.confidence = Decimal(str(payload.confidence))
        assessment.status = payload.status
        assessment.supporting_claim_ids = payload.supporting_claim_ids
        assessment.contradicting_claim_ids = payload.contradicting_claim_ids
        assessment.assessment_trace = payload.trace
        return assessment