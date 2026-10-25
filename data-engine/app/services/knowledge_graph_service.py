"""Deterministic, provenance-aware graph for investment knowledge."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    Company,
    CompanyKPI,
    DecisionJournalEntry,
    DecisionLesson,
    InvestmentCaseStudy,
    InvestmentPrinciple,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    RiskEvent,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")[:180]


class KnowledgeGraphService:
    def sync(self, db: Session) -> dict[str, Any]:
        if db.info.get("tenant_id") is None:
            raise ValueError("Tenant context is required for knowledge graph sync")
        existing_nodes = {
            row.node_key: row for row in db.scalars(select(KnowledgeGraphNode)).all()
        }
        for row in existing_nodes.values():
            row.status = "stale"
        nodes: dict[str, KnowledgeGraphNode] = {}

        for company in db.scalars(select(Company).order_by(Company.ticker)).all():
            nodes[f"company:{company.id}"] = self._node(
                db,
                existing_nodes,
                key=f"company:{company.id}",
                node_type="company",
                label=f"{company.ticker} · {company.name}",
                description=f"{company.sector} / {company.industry}",
                company_id=company.id,
                entity_type="company",
                entity_id=company.id,
                attributes={
                    "ticker": company.ticker,
                    "sector": company.sector,
                    "industry": company.industry,
                    "factor_tags": company.factor_tags,
                },
            )
        concept_labels = {
            "capital_intensity": "Capital intensity",
            "funding_risk": "Funding risk",
            "dilution": "Dilution",
            **{
                taxonomy: taxonomy.replace("_", " ").title()
                for taxonomy in (
                    "overestimating_TAM",
                    "underestimating_dilution",
                    "extrapolating_peak_margin",
                    "ignoring_balance_sheet",
                    "management_trust_error",
                    "valuation_anchoring",
                    "position_sizing_error",
                    "selling_too_early",
                    "ignoring_cyclicality",
                    "thesis_drift",
                )
            },
        }
        for key, label in concept_labels.items():
            nodes[f"concept:{key}"] = self._node(
                db,
                existing_nodes,
                key=f"concept:{key}",
                node_type="concept",
                label=label,
                description="Investment reasoning concept",
                attributes={"concept_key": key},
            )

        principles = list(
            db.scalars(
                select(InvestmentPrinciple).where(
                    InvestmentPrinciple.status == "approved"
                )
            ).all()
        )
        for principle in principles:
            nodes[f"principle:{principle.id}"] = self._node(
                db,
                existing_nodes,
                key=f"principle:{principle.id}",
                node_type="principle",
                label=principle.principle[:500],
                description=principle.exact_fragment,
                entity_type="investment_principle",
                entity_id=principle.id,
                confidence=principle.confidence,
                attributes={
                    "category": principle.category,
                    "author": principle.author,
                    "page_number": principle.page_number,
                },
            )
            if principle.author:
                author_key = f"author:{_slug(principle.author)}"
                nodes[author_key] = self._node(
                    db,
                    existing_nodes,
                    key=author_key,
                    node_type="author",
                    label=principle.author,
                    description="Investment author",
                    attributes={},
                )

        cases = list(db.scalars(select(InvestmentCaseStudy)).all())
        for case in cases:
            nodes[f"case:{case.id}"] = self._node(
                db,
                existing_nodes,
                key=f"case:{case.id}",
                node_type="case_study",
                label=case.title,
                description=case.summary,
                company_id=case.company_id,
                entity_type="investment_case",
                entity_id=case.id,
                attributes={"sector": case.sector, "period": case.period},
            )
        decisions = list(db.scalars(select(DecisionJournalEntry)).all())
        for decision in decisions:
            nodes[f"decision:{decision.id}"] = self._node(
                db,
                existing_nodes,
                key=f"decision:{decision.id}",
                node_type="decision",
                label=f"{decision.decision.upper()} · {decision.decision_date}",
                description=decision.rationale,
                company_id=decision.company_id,
                entity_type="decision",
                entity_id=decision.id,
                attributes={"price": str(decision.price) if decision.price else None},
            )
        lessons = list(
            db.scalars(
                select(DecisionLesson).where(DecisionLesson.status == "approved")
            ).all()
        )
        for lesson in lessons:
            nodes[f"lesson:{lesson.id}"] = self._node(
                db,
                existing_nodes,
                key=f"lesson:{lesson.id}",
                node_type="decision_lesson",
                label=lesson.lesson[:500],
                description=lesson.future_application,
                company_id=lesson.company_id,
                entity_type="decision_lesson",
                entity_id=lesson.id,
                attributes={"taxonomy": lesson.taxonomy, "error": lesson.error},
            )
        kpis = list(
            db.scalars(select(CompanyKPI).where(CompanyKPI.active.is_(True))).all()
        )
        for kpi in kpis:
            nodes[f"kpi:{kpi.company_id}:{kpi.metric_key}"] = self._node(
                db,
                existing_nodes,
                key=f"kpi:{kpi.company_id}:{kpi.metric_key}",
                node_type="kpi",
                label=kpi.display_name,
                description=f"Canonical unit: {kpi.canonical_unit}",
                company_id=kpi.company_id,
                entity_type="company_kpi",
                entity_id=kpi.id,
                attributes={"metric_key": kpi.metric_key, "required": kpi.required},
            )
        risks = list(db.scalars(select(RiskEvent)).all())
        for risk in risks:
            nodes[f"risk:{risk.id}"] = self._node(
                db,
                existing_nodes,
                key=f"risk:{risk.id}",
                node_type="risk",
                label=risk.event_type.replace("_", " ").title(),
                description=risk.message,
                company_id=risk.company_id,
                entity_type="risk_event",
                entity_id=risk.id,
                attributes={"severity": risk.severity},
            )
        db.flush()

        existing_edges = {
            (row.from_node_id, row.to_node_id, row.edge_type): row
            for row in db.scalars(select(KnowledgeGraphEdge)).all()
        }
        for row in existing_edges.values():
            row.status = "stale"
        touched_edges: set[int] = set()

        def edge(
            source_key: str,
            target_key: str,
            edge_type: str,
            *,
            evidence: list[dict] | None = None,
            confidence: Decimal = Decimal("1"),
        ) -> None:
            source, target = nodes.get(source_key), nodes.get(target_key)
            if source is None or target is None:
                return
            row = self._edge(
                db,
                existing_edges,
                source,
                target,
                edge_type,
                evidence=evidence or [],
                confidence=confidence,
            )
            db.flush()
            touched_edges.add(row.id)

        edge("concept:capital_intensity", "concept:funding_risk", "increases")
        edge("concept:funding_risk", "concept:dilution", "increases")
        for principle in principles:
            principle_key = f"principle:{principle.id}"
            if principle.author:
                edge(f"author:{_slug(principle.author)}", principle_key, "authored")
            for company_id in principle.applies_to_company_ids:
                edge(
                    principle_key,
                    f"company:{company_id}",
                    "applies_to",
                    evidence=[{"investment_principle_id": principle.id}],
                    confidence=principle.confidence,
                )
        for case in cases:
            if case.company_id:
                edge(f"case:{case.id}", f"company:{case.company_id}", "about_company")
        for decision in decisions:
            edge(
                f"decision:{decision.id}",
                f"company:{decision.company_id}",
                "about_company",
            )
        for lesson in lessons:
            if lesson.decision_journal_entry_id:
                edge(
                    f"decision:{lesson.decision_journal_entry_id}",
                    f"lesson:{lesson.id}",
                    "produced_lesson",
                    evidence=lesson.evidence,
                )
            if lesson.company_id:
                edge(f"lesson:{lesson.id}", f"company:{lesson.company_id}", "applies_to")
            edge(
                f"lesson:{lesson.id}",
                f"concept:{lesson.taxonomy}",
                "evidence_for",
                evidence=lesson.evidence,
            )
            if lesson.taxonomy == "underestimating_dilution":
                edge(f"lesson:{lesson.id}", "concept:dilution", "evidence_for")
        for kpi in kpis:
            edge(
                f"company:{kpi.company_id}",
                f"kpi:{kpi.company_id}:{kpi.metric_key}",
                "tracks_kpi",
            )
        for risk in risks:
            if risk.company_id:
                edge(f"company:{risk.company_id}", f"risk:{risk.id}", "exposed_to")
        for company in db.scalars(select(Company)).all():
            tags = {tag.lower().replace("-", "_") for tag in company.factor_tags}
            if tags & {"capital_intensive", "space", "pre_revenue"}:
                edge(f"company:{company.id}", "concept:capital_intensity", "exposed_to")
            if tags & {"space", "pre_revenue", "funding_risk"}:
                edge(f"company:{company.id}", "concept:funding_risk", "exposed_to")
                edge(f"company:{company.id}", "concept:dilution", "exposed_to")
        db.commit()
        active_nodes = sum(row.status == "active" for row in existing_nodes.values())
        return {
            "status": "synced",
            "nodes": active_nodes,
            "edges": len(touched_edges),
            "node_types": sorted(
                {row.node_type for row in existing_nodes.values() if row.status == "active"}
            ),
        }

    @staticmethod
    def _node(
        db: Session,
        existing: dict[str, KnowledgeGraphNode],
        *,
        key: str,
        node_type: str,
        label: str,
        description: str,
        company_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        confidence: Decimal = Decimal("1"),
        attributes: dict[str, Any],
    ) -> KnowledgeGraphNode:
        row = existing.get(key)
        if row is None:
            row = KnowledgeGraphNode(node_key=key)
            db.add(row)
            existing[key] = row
        row.node_type = node_type
        row.label = label
        row.description = description
        row.company_id = company_id
        row.entity_type = entity_type
        row.entity_id = entity_id
        row.confidence = confidence
        row.status = "active"
        row.attributes = attributes
        return row

    @staticmethod
    def _edge(
        db: Session,
        existing: dict[tuple[int, int, str], KnowledgeGraphEdge],
        source: KnowledgeGraphNode,
        target: KnowledgeGraphNode,
        edge_type: str,
        *,
        evidence: list[dict],
        confidence: Decimal,
    ) -> KnowledgeGraphEdge:
        key = (source.id, target.id, edge_type)
        row = existing.get(key)
        if row is None:
            row = KnowledgeGraphEdge(
                from_node_id=source.id,
                to_node_id=target.id,
                edge_type=edge_type,
            )
            db.add(row)
            existing[key] = row
        row.weight = Decimal("1")
        row.confidence = confidence
        row.evidence = evidence
        row.provenance = "deterministic_graph_sync_v1"
        row.status = "active"
        row.attributes = {}
        return row

    def graph(
        self,
        db: Session,
        *,
        node_types: set[str] | None = None,
        company_id: int | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        conds: list[Any] = [KnowledgeGraphNode.status == "active"]
        if node_types:
            conds.append(KnowledgeGraphNode.node_type.in_(node_types))
        if company_id is not None:
            conds.append(KnowledgeGraphNode.company_id == company_id)
        statement = select(KnowledgeGraphNode).where(*conds)
        # Rank by actual active degree within the requested scope, not insertion
        # order (sync inserts all companies before their connected knowledge).
        eligible = select(KnowledgeGraphNode.id).where(
            *conds, *tenant_filters(db, KnowledgeGraphNode)
        ).subquery()
        active_edges = select(KnowledgeGraphEdge).where(
            KnowledgeGraphEdge.status == "active",
            KnowledgeGraphEdge.from_node_id.in_(select(eligible.c.id)),
            KnowledgeGraphEdge.to_node_id.in_(select(eligible.c.id)),
            *tenant_filters(db, KnowledgeGraphEdge),
        ).subquery()
        endpoints = union_all(
            select(active_edges.c.from_node_id.label("node_id")),
            select(active_edges.c.to_node_id.label("node_id")),
        ).subquery()
        degrees = select(endpoints.c.node_id, func.count().label("degree")).group_by(endpoints.c.node_id).subquery()
        nodes = list(db.scalars(
            statement.outerjoin(degrees, degrees.c.node_id == KnowledgeGraphNode.id)
            .order_by(func.coalesce(degrees.c.degree, 0).desc(), KnowledgeGraphNode.id)
            .limit(limit)
        ).all())
        node_ids = {node.id for node in nodes}
        edges = (
            list(
                db.scalars(
                    select(KnowledgeGraphEdge).where(
                        KnowledgeGraphEdge.status == "active",
                        KnowledgeGraphEdge.from_node_id.in_(node_ids),
                        KnowledgeGraphEdge.to_node_id.in_(node_ids),
                    )
                ).all()
            )
            if node_ids
            else []
        )
        payload = self._payload(nodes, edges)
        # El recorte del backend se DECLARA: `node_count` es lo devuelto (lo que
        # dejo `limit`), `total_node_count` es cuantos nodos hay con los MISMOS
        # filtros. Sin esto la pagina presenta 120 (lo paginado) como el tamano
        # del grafo y el usuario cree que el grafo tiene 120 nodos.
        payload["total_node_count"] = int(
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGraphNode)
                .where(*conds, *tenant_filters(db, KnowledgeGraphNode))
            )
            or 0
        )
        return payload

    def neighborhood(
        self, db: Session, node_id: int, *, depth: int = 2
    ) -> dict[str, Any]:
        root = db.get(KnowledgeGraphNode, node_id)
        if root is None or root.status != "active":
            raise ValueError("Knowledge graph node not found")
        seen = {node_id}
        frontier = {node_id}
        edges_by_id: dict[int, KnowledgeGraphEdge] = {}
        for _ in range(max(1, min(depth, 4))):
            rows = list(
                db.scalars(
                    select(KnowledgeGraphEdge).where(
                        KnowledgeGraphEdge.status == "active",
                        or_(
                            KnowledgeGraphEdge.from_node_id.in_(frontier),
                            KnowledgeGraphEdge.to_node_id.in_(frontier),
                        ),
                    )
                ).all()
            )
            next_frontier: set[int] = set()
            for edge in rows:
                edges_by_id[edge.id] = edge
                next_frontier.update((edge.from_node_id, edge.to_node_id))
            next_frontier -= seen
            if not next_frontier:
                break
            seen.update(next_frontier)
            frontier = next_frontier
        nodes = list(
            db.scalars(
                select(KnowledgeGraphNode)
                .where(KnowledgeGraphNode.id.in_(seen))
                .order_by(KnowledgeGraphNode.id)
            ).all()
        )
        payload = self._payload(nodes, list(edges_by_id.values()))
        payload["root_node_id"] = node_id
        payload["depth"] = depth
        return payload

    @staticmethod
    def _payload(
        nodes: list[KnowledgeGraphNode], edges: list[KnowledgeGraphEdge]
    ) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": node.id,
                    "key": node.node_key,
                    "type": node.node_type,
                    "label": node.label,
                    "description": node.description,
                    "company_id": node.company_id,
                    "entity_type": node.entity_type,
                    "entity_id": node.entity_id,
                    "confidence": node.confidence,
                    "attributes": node.attributes,
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": edge.id,
                    "from": edge.from_node_id,
                    "to": edge.to_node_id,
                    "type": edge.edge_type,
                    "weight": edge.weight,
                    "confidence": edge.confidence,
                    "evidence": edge.evidence,
                    "provenance": edge.provenance,
                }
                for edge in edges
            ],
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
