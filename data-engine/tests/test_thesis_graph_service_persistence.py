"""Thesis graph persistence and impact mapping with real SQLite, no model/network."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Claim, Company, ThesisNode, ThesisSection, ThesisVersion
from app.models.entities import Base
from app.services.thesis_graph_service import ThesisGraphService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def company(db, ticker="GRAPH"):
    row = Company(
        ticker=ticker,
        name=ticker,
        exchange="TEST",
        currency="USD",
        sector="S",
        industry="I",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(row)
    db.flush()
    return row


def thesis(db, company):
    row = ThesisVersion(
        company_id=company.id,
        version=1,
        status="draft",
        thesis_markdown="# Graph",
        executive_summary="Funding capital debt dilution",
        data_confidence_score=75,
    )
    db.add(row)
    db.flush()
    return row


def test_missing_thesis_read_build_raise_and_impact_is_explicit(db):
    c = company(db)
    service = ThesisGraphService()
    for method in (service.read, service.build):
        with pytest.raises(ValueError, match="No thesis exists for GRAPH"):
            method(db, c)
    result = service.assess_impact(db, c, "funding capital", base_materiality=7, impact_direction="negative")
    assert result.affected_claim_ids == result.affected_node_ids == []
    assert result.impact_score == 7 and result.impact_direction == "negative"
    assert result.trace == {"status": "missing_thesis"}
    assert "No stored thesis" in result.summary
    assert db.scalars(select(ThesisNode)).all() == []


def test_sections_unmatched_claims_and_rebuild_update_existing_rows(db):
    c = company(db)
    t = thesis(db, c)
    section = ThesisSection(
        company_id=c.id,
        thesis_version_id=t.id,
        section_key="business",
        title="Business",
        body="x" * 1100,
        order_index=1,
        confidence=Decimal("0.55"),
    )
    claim = Claim(
        company_id=c.id,
        thesis_version_id=t.id,
        statement="Auditors review accounts annually",
        status="uncertain",
        confidence=Decimal("0.4"),
        materiality_score=4,
        metadata_={"invalidation_conditions": ["audit delayed", "audit delayed"]},
    )
    db.add_all([section, claim])
    db.flush()
    service = ThesisGraphService()
    _, nodes, edges = service.build(db, c, t, commit=False)
    section_node = next(n for n in nodes if n.node_key == "section:business")
    claim_node = next(n for n in nodes if n.node_key == f"claim:{claim.id}")
    root = next(n for n in nodes if n.node_key == "thesis:root")
    assert section_node.description == "x" * 1000 and section_node.confidence == Decimal("0.55")
    assert claim_node.status == "uncertain" and claim_node.invalidation_conditions == ["audit delayed"]
    assert any(
        e.from_node_id == root.id and e.to_node_id == claim_node.id and e.strength == Decimal("0.5")
        for e in edges
    )
    ids = [n.id for n in nodes], [e.id for e in edges]
    section.title, section.body = "Updated business", "new content"
    claim.statement, claim.status = "Auditors report annually", "supported"
    db.flush()
    _, updated, new_edges = service.build(db, c, t)
    assert ([n.id for n in updated], [e.id for e in new_edges]) == ids
    updated_section = next(n for n in updated if n.id == section_node.id)
    assert updated_section.label == "Updated business" and updated_section.description == "new content"
    assert next(n for n in updated if n.id == claim_node.id).status == "supported"


def test_real_impact_matches_company_claim_and_nodes_caps_score_and_keeps_direction(db):
    c = company(db)
    t = thesis(db, c)
    statement = "Funding capital debt dilution"
    claim = Claim(
        company_id=c.id,
        thesis_version_id=t.id,
        statement=statement,
        materiality_score=8,
        confidence=Decimal("0.8"),
    )
    other = company(db, "OTHER")
    other_claim = Claim(company_id=other.id, statement=statement, materiality_score=10)
    db.add_all([claim, other_claim])
    db.flush()
    service = ThesisGraphService()
    impact = service.assess_impact(db, c, statement, base_materiality=9, impact_direction="negative")
    assert impact.affected_claim_ids == [claim.id]
    assert impact.impact_score == 10 and impact.impact_direction == "negative"
    nodes = {n.id: n for n in db.scalars(select(ThesisNode)).all()}
    assert impact.affected_node_ids and all(nodes[i].company_id == c.id for i in impact.affected_node_ids)
    assert "Afecta a 1 afirmaciones" in impact.summary and "Funding" in impact.summary
    assert impact.trace["method"] == "lexical_semantic_v1"
    assert impact.trace["claim_matches"] == [{"claim_id": claim.id, "similarity": 1.0}]
    assert all(row["similarity"] >= 0.1 for row in impact.trace["node_matches"])
    unrelated = service.assess_impact(db, c, "zebra violin canyon", base_materiality=3)
    assert unrelated.affected_claim_ids == unrelated.affected_node_ids == []
    assert unrelated.impact_score == 3 and unrelated.impact_direction == "neutral"
    assert unrelated.trace["node_matches"] == unrelated.trace["claim_matches"] == []
    assert unrelated.summary == "Ningún nodo estructural de la tesis coincide con confianza suficiente."
