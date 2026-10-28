from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    ThesisEdge,
    ThesisNode,
    ThesisSection,
    ThesisVersion,
)
from app.services.claim_intelligence_service import ClaimIntelligenceService, _similarity
from app.services.claim_scope import latest_thesis_version, live_claims

NODE_RULES: dict[str, tuple[str, ...]] = {
    "technology": ("technology", "technical", "product works", "launch", "performance"),
    "funding": ("funding", "financed", "cash runway", "capital", "dilution", "debt"),
    "commercialization": (
        "monetization",
        "commercial",
        "customer",
        "contract",
        "revenue",
        "pricing",
    ),
    "execution": ("execution", "cadence", "delivery", "capacity", "manufacturing"),
    "regulatory": ("regulatory", "approval", "license", "fcc", "fda"),
    "economics": ("margin", "cash flow", "returns", "roic", "unit economics"),
    "moat": ("moat", "switching", "network effect", "brand", "scale", "advantage"),
}


@dataclass(frozen=True)
class ThesisImpact:
    affected_claim_ids: list[int]
    affected_node_ids: list[int]
    impact_score: int
    impact_direction: str
    summary: str
    trace: dict



def impact_summary_text(affected_claim_count: int, labels: list[str]) -> str:
    """Texto del impacto semántico para los resúmenes de cambio.

    Honestidad con cero coincidencias: la forma antigua «Afecta a 0
    afirmaciones y nodos de la tesis: …» se leía como si nada estuviera
    afectado pese a listar apartados. Con 0 afirmaciones y apartados
    afectados se dice explícitamente que no hay afirmación concreta y se
    nombran los apartados. La forma con afirmaciones usa «…y a estos
    apartados de la tesis: », la cadena que el frontend (change-copy.ts)
    reconoce para traducir las etiquetas de los apartados al español.
    """
    if not labels:
        return "Ningún nodo estructural de la tesis coincide con confianza suficiente."
    if affected_claim_count:
        return (
            f"Afecta a {affected_claim_count} afirmaciones y a estos apartados de la tesis: "
            f"{', '.join(labels)}."
        )
    return (
        "No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: "
        f"{', '.join(labels)}."
    )

class ThesisGraphService:
    def latest_thesis(self, db: Session, company: Company) -> ThesisVersion | None:
        return latest_thesis_version(db, company)

    def read(
        self, db: Session, company: Company, thesis: ThesisVersion | None = None
    ) -> tuple[ThesisVersion, list[ThesisNode], list[ThesisEdge]]:
        thesis = thesis or self.latest_thesis(db, company)
        if thesis is None:
            raise ValueError(f"No thesis exists for {company.ticker}")
        nodes = list(
            db.scalars(
                select(ThesisNode)
                .where(ThesisNode.thesis_version_id == thesis.id)
                .order_by(ThesisNode.id)
            ).all()
        )
        node_ids = [node.id for node in nodes]
        edges = (
            list(
                db.scalars(
                    select(ThesisEdge)
                    .where(
                        ThesisEdge.from_node_id.in_(node_ids),
                        ThesisEdge.to_node_id.in_(node_ids),
                    )
                    .order_by(ThesisEdge.id)
                ).all()
            )
            if node_ids
            else []
        )
        return thesis, nodes, edges

    def build(
        self,
        db: Session,
        company: Company,
        thesis: ThesisVersion | None = None,
        *,
        commit: bool = True,
    ) -> tuple[ThesisVersion, list[ThesisNode], list[ThesisEdge]]:
        thesis = thesis or self.latest_thesis(db, company)
        if thesis is None:
            raise ValueError(f"No thesis exists for {company.ticker}")

        root = self._upsert_node(
            db,
            company_id=company.id,
            thesis_id=thesis.id,
            node_key="thesis:root",
            node_type="thesis",
            label=f"{company.ticker} investment thesis",
            description=thesis.executive_summary,
            confidence=Decimal(str(max(0, min(1, thesis.data_confidence_score / 100)))),
            materiality_score=10,
            claim_ids=[],
            invalidation_conditions=[],
        )

        sections = db.scalars(
            select(ThesisSection)
            .where(ThesisSection.thesis_version_id == thesis.id)
            .order_by(ThesisSection.order_index)
        ).all()
        # Only this version's claims. Reading every claim of the company put a
        # node per superseded claim into the CURRENT graph, so regenerating the
        # thesis accumulated dead nodes instead of replacing them.
        claims = live_claims(db, company, thesis=thesis)

        structural_nodes: dict[str, ThesisNode] = {}
        corpus = " ".join(
            [
                thesis.executive_summary,
                *(section.body for section in sections),
                *(claim.statement for claim in claims),
            ]
        ).lower()
        for key, markers in NODE_RULES.items():
            if not any(marker in corpus for marker in markers):
                continue
            linked_claims = [
                claim.id
                for claim in claims
                if any(marker in claim.statement.lower() for marker in markers)
            ]
            node = self._upsert_node(
                db,
                company_id=company.id,
                thesis_id=thesis.id,
                node_key=f"dependency:{key}",
                node_type="dependency",
                label=key.replace("_", " ").title(),
                description=f"Structural thesis dependency: {key.replace('_', ' ')}.",
                confidence=Decimal("0.65") if linked_claims else Decimal("0.35"),
                materiality_score=max(
                    [claims_by_id.materiality_score for claims_by_id in claims if claims_by_id.id in linked_claims]
                    or [6]
                ),
                claim_ids=linked_claims,
                invalidation_conditions=[
                    condition
                    for claim in claims
                    if claim.id in linked_claims
                    for condition in (claim.metadata_ or {}).get(
                        "invalidation_conditions", []
                    )
                ],
            )
            structural_nodes[key] = node
            self._upsert_edge(db, root.id, node.id, "depends_on", Decimal("1.0"))

        for section in sections:
            node = self._upsert_node(
                db,
                company_id=company.id,
                thesis_id=thesis.id,
                node_key=f"section:{section.section_key}",
                node_type="section",
                label=section.title,
                description=section.body[:1000],
                confidence=section.confidence,
                materiality_score=5,
                claim_ids=[],
                invalidation_conditions=[],
            )
            self._upsert_edge(db, root.id, node.id, "supported_by", Decimal("0.7"))

        for claim in claims:
            claim_node = self._upsert_node(
                db,
                company_id=company.id,
                thesis_id=thesis.id,
                node_key=f"claim:{claim.id}",
                node_type="claim",
                label=claim.statement[:300],
                description=claim.statement,
                confidence=claim.confidence,
                materiality_score=claim.materiality_score,
                claim_ids=[claim.id],
                invalidation_conditions=(claim.metadata_ or {}).get(
                    "invalidation_conditions", []
                ),
                status=claim.status,
            )
            matched_dependency = False
            for key, node in structural_nodes.items():
                if any(
                    marker in claim.statement.lower() for marker in NODE_RULES[key]
                ):
                    self._upsert_edge(
                        db, node.id, claim_node.id, "supported_by", Decimal("0.8")
                    )
                    matched_dependency = True
            if not matched_dependency:
                self._upsert_edge(
                    db, root.id, claim_node.id, "supported_by", Decimal("0.5")
                )

        db.flush()
        _, nodes, edges = self.read(db, company, thesis)
        if commit:
            db.commit()
        return thesis, nodes, edges

    def assess_impact(
        self,
        db: Session,
        company: Company,
        text: str,
        *,
        base_materiality: int = 5,
        impact_direction: str = "neutral",
    ) -> ThesisImpact:
        thesis = self.latest_thesis(db, company)
        if thesis is None:
            return ThesisImpact(
                affected_claim_ids=[],
                affected_node_ids=[],
                impact_score=base_materiality,
                impact_direction=impact_direction,
                summary="No stored thesis is available for semantic impact mapping.",
                trace={"status": "missing_thesis"},
            )
        _, nodes, _ = self.build(db, company, thesis)
        matches = ClaimIntelligenceService().match_claims(
            db, company_id=company.id, statement=text, limit=8, minimum_similarity=0.16
        )
        affected_claim_ids = [
            match.claim.id for match in matches if match.similarity >= 0.24
        ]
        scored_nodes = [
            (node, _similarity(f"{node.label} {node.description}", text))
            for node in nodes
        ]
        affected_nodes = [
            node for node, score in scored_nodes if score >= 0.16
        ]
        semantic_boost = min(
            2,
            int(
                max(
                    [match.similarity for match in matches]
                    + [score for _, score in scored_nodes]
                    + [0]
                )
                * 3
            ),
        )
        impact_score = min(10, base_materiality + semantic_boost)
        labels = [node.label for node in affected_nodes[:4]]
        summary = impact_summary_text(len(affected_claim_ids), labels)
        return ThesisImpact(
            affected_claim_ids=affected_claim_ids,
            affected_node_ids=[node.id for node in affected_nodes],
            impact_score=impact_score,
            impact_direction=impact_direction,
            summary=summary,
            trace={
                "method": "lexical_semantic_v1",
                "claim_matches": [
                    {"claim_id": match.claim.id, "similarity": round(match.similarity, 4)}
                    for match in matches
                ],
                "node_matches": [
                    {"node_id": node.id, "similarity": round(score, 4)}
                    for node, score in scored_nodes
                    if score >= 0.10
                ],
            },
        )

    def _upsert_node(
        self,
        db: Session,
        *,
        company_id: int,
        thesis_id: int,
        node_key: str,
        node_type: str,
        label: str,
        description: str,
        confidence: Decimal,
        materiality_score: int,
        claim_ids: list[int],
        invalidation_conditions: list[str],
        status: str = "active",
    ) -> ThesisNode:
        node = db.scalar(
            select(ThesisNode).where(
                ThesisNode.thesis_version_id == thesis_id,
                ThesisNode.node_key == node_key,
            )
        )
        if node is None:
            node = ThesisNode(
                company_id=company_id,
                thesis_version_id=thesis_id,
                node_key=node_key,
            )
            db.add(node)
        node.node_type = node_type
        node.label = label
        node.description = description
        node.status = status
        node.confidence = confidence
        node.materiality_score = materiality_score
        node.claim_ids = list(dict.fromkeys(claim_ids))
        node.invalidation_conditions = list(dict.fromkeys(invalidation_conditions))
        db.flush()
        return node

    def _upsert_edge(
        self,
        db: Session,
        from_node_id: int,
        to_node_id: int,
        edge_type: str,
        strength: Decimal,
    ) -> ThesisEdge:
        edge = db.scalar(
            select(ThesisEdge).where(
                ThesisEdge.from_node_id == from_node_id,
                ThesisEdge.to_node_id == to_node_id,
                ThesisEdge.edge_type == edge_type,
            )
        )
        if edge is None:
            edge = ThesisEdge(
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                edge_type=edge_type,
            )
            db.add(edge)
        edge.strength = strength
        db.flush()
        return edge
