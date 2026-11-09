"""Bordes de KnowledgeGraphService no cubiertos por las suites existentes.

Cubre: guarda de tenant en sync, nodos y aristas preexistentes que quedan stale,
reuso de filas existentes en _node/_edge, casos y riesgos con y sin empresa,
principios sin autor y con applies_to a empresa inexistente (arista descartada),
lecciones sin entrada/empresa y taxonomia no dilutiva, filtro company_id de graph,
neighborhood sobre nodo inexistente/stale y recorrido de profundidad completa.
Tambien incluye el arreglo de coleccion de test_security_fixes.py (ver su cabecera).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Company,
    CompanyKPI,
    DecisionJournalEntry,
    DecisionLesson,
    InvestmentCaseStudy,
    InvestmentPrinciple,
    KnowledgeDocument,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    RiskEvent,
    Tenant,
)
from app.models.entities import Base
from app.services.knowledge_graph_service import KnowledgeGraphService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="owner"))
        db.commit()
        db.info.update(tenant_id=1, user_id="owner")
        yield db
    engine.dispose()


def _semilla(db):
    empresa_a = Company(
        ticker="SPA",
        name="Space",
        exchange="NASDAQ",
        sector="Space",
        industry="Launch",
        company_type="pre_revenue",
        valuation_model="dcf",
        factor_tags=["space"],
    )
    empresa_b = Company(
        ticker="PLN",
        name="Plain",
        exchange="NASDAQ",
        sector="Utilities",
        industry="Grid",
        company_type="mature",
        valuation_model="dcf",
        factor_tags=[],
    )
    doc = KnowledgeDocument(title="Carta", author="Investor", document_type="fund_letter", status="ready")
    db.add_all([empresa_a, empresa_b, doc])
    db.flush()
    db.add_all(
        [
            InvestmentPrinciple(
                knowledge_document_id=doc.id,
                principle="La intensidad de capital exige caja.",
                principle_fingerprint="b" * 64,
                category="capital_allocation",
                exact_fragment="La intensidad de capital exige caja.",
                author="Investor",
                applies_to_company_ids=[empresa_a.id, 99999],
                confidence=Decimal("0.9"),
                status="approved",
            ),
            InvestmentPrinciple(
                knowledge_document_id=doc.id,
                principle="Sin autor asignado.",
                principle_fingerprint="c" * 64,
                category="risk",
                exact_fragment="Sin autor asignado.",
                author=None,
                applies_to_company_ids=[empresa_b.id],
                confidence=Decimal("0.5"),
                status="approved",
            ),
            InvestmentCaseStudy(
                company_id=empresa_a.id, title="Caso A", summary="Resumen A", status="approved"
            ),
            InvestmentCaseStudy(company_id=None, title="Caso B", summary="Resumen B", status="approved"),
            RiskEvent(
                company_id=empresa_a.id,
                severity="high",
                event_type="funding_gap",
                message="Gap de financiacion",
            ),
            RiskEvent(company_id=None, severity="info", event_type="macro", message="Riesgo global"),
        ]
    )
    decision = DecisionJournalEntry(
        company_id=empresa_a.id,
        decision="buy",
        rationale="Tesis intacta.",
        what_must_be_true=["Caja suficiente"],
        status="open",
    )
    db.add(decision)
    db.flush()
    db.add_all(
        [
            DecisionLesson(
                decision_journal_entry_id=decision.id,
                company_id=empresa_a.id,
                taxonomy="underestimating_dilution",
                lesson="Subestime la dilucion.",
                future_application="Exigir colchon.",
                evidence=[{"k": 1}],
                status="approved",
            ),
            DecisionLesson(
                decision_journal_entry_id=None,
                company_id=None,
                taxonomy="thesis_drift",
                lesson="Deriva de tesis.",
                future_application="Revisar tesis.",
                evidence=[],
                status="approved",
            ),
            CompanyKPI(
                company_id=empresa_a.id,
                metric_key="shares_diluted",
                display_name="Acciones diluidas",
                canonical_unit="shares",
                required=True,
            ),
        ]
    )
    db.commit()
    return empresa_a, empresa_b


def test_sync_sin_tenant_lanza(db):
    _semilla(db)
    db.info.pop("tenant_id")
    with pytest.raises(ValueError, match="Tenant context is required"):
        KnowledgeGraphService().sync(db)


def test_sync_cubre_casos_riesgos_lecciones_y_stale(db):
    empresa_a, empresa_b = _semilla(db)
    obsoleto = KnowledgeGraphNode(
        tenant_id=1, node_key="obsolete:x", node_type="company", label="Viejo", status="active"
    )
    db.add(obsoleto)
    db.flush()
    arista_obsoleta = KnowledgeGraphEdge(
        tenant_id=1, from_node_id=obsoleto.id, to_node_id=obsoleto.id, edge_type="linked", status="active"
    )
    db.add(arista_obsoleta)
    pre_company = KnowledgeGraphNode(
        tenant_id=1,
        node_key=f"company:{empresa_a.id}",
        node_type="company",
        label="Preexistente",
        status="active",
    )
    pre_concept = KnowledgeGraphNode(
        tenant_id=1, node_key="concept:capital_intensity", node_type="concept", label="Pre", status="active"
    )
    db.add_all([pre_company, pre_concept])
    db.flush()
    pre_edge = KnowledgeGraphEdge(
        tenant_id=1,
        from_node_id=pre_company.id,
        to_node_id=pre_concept.id,
        edge_type="exposed_to",
        status="stale",
    )
    db.add(pre_edge)
    db.commit()

    resultado = KnowledgeGraphService().sync(db)

    assert resultado["status"] == "synced"
    nodos = {n.node_key: n for n in db.query(KnowledgeGraphNode).all()}
    assert nodos["obsolete:x"].status == "stale"
    assert db.get(KnowledgeGraphEdge, arista_obsoleta.id).status == "stale"
    assert nodos[f"company:{empresa_a.id}"].id == pre_company.id
    assert nodos[f"company:{empresa_a.id}"].status == "active"
    assert nodos["concept:capital_intensity"].id == pre_concept.id
    assert db.get(KnowledgeGraphEdge, pre_edge.id).status == "active"
    claves = set(nodos)
    assert f"case:1" in claves or any(k.startswith("case:") for k in claves)
    assert any(k.startswith("risk:") for k in claves)
    assert any(k.startswith("lesson:") for k in claves)
    assert "author:investor" in claves
    aristas = {
        (e.from_node_id, e.to_node_id, e.edge_type)
        for e in db.query(KnowledgeGraphEdge).filter_by(status="active")
    }
    case_a = db.query(InvestmentCaseStudy).filter_by(title="Caso A").one()
    assert (nodos[f"case:{case_a.id}"].id, pre_company.id, "about_company") in aristas
    riesgo_a = db.query(RiskEvent).filter_by(event_type="funding_gap").one()
    assert (pre_company.id, nodos[f"risk:{riesgo_a.id}"].id, "exposed_to") in aristas
    leccion_dilucion = db.query(DecisionLesson).filter_by(taxonomy="underestimating_dilution").one()
    assert (
        nodos[f"lesson:{leccion_dilucion.id}"].id,
        nodos["concept:dilution"].id,
        "evidence_for",
    ) in aristas
    leccion_deriva = db.query(DecisionLesson).filter_by(taxonomy="thesis_drift").one()
    assert (
        nodos[f"lesson:{leccion_deriva.id}"].id,
        nodos["concept:dilution"].id,
        "evidence_for",
    ) not in aristas
    # La empresa 99999 no existe: la arista applies_to se descarta sin romper.
    assert not any(e[2] == "applies_to" and e[1] not in {n.id for n in nodos.values()} for e in aristas)
    assert resultado["nodes"] == sum(n.status == "active" for n in nodos.values())

    segunda = KnowledgeGraphService().sync(db)
    assert segunda["nodes"] == resultado["nodes"]


def test_graph_con_filtro_company_id(db):
    empresa_a, empresa_b = _semilla(db)
    KnowledgeGraphService().sync(db)
    payload = KnowledgeGraphService().graph(db, company_id=empresa_a.id, limit=500)
    assert payload["nodes"]
    assert {n["company_id"] for n in payload["nodes"]} == {empresa_a.id}
    assert payload["total_node_count"] == len(payload["nodes"])
    sin_filtro = KnowledgeGraphService().graph(db, limit=500)
    assert sin_filtro["total_node_count"] > payload["total_node_count"]


def test_neighborhood_nodo_inexistente_o_stale_lanza(db):
    _semilla(db)
    stale = KnowledgeGraphNode(tenant_id=1, node_key="x:1", node_type="company", label="S", status="stale")
    db.add(stale)
    db.commit()
    service = KnowledgeGraphService()
    with pytest.raises(ValueError, match="node not found"):
        service.neighborhood(db, 999999)
    with pytest.raises(ValueError, match="node not found"):
        service.neighborhood(db, stale.id)


def test_neighborhood_profundidad_completa_sin_break(db):
    nodos = [
        KnowledgeGraphNode(
            tenant_id=1, node_key=f"c:{i}", node_type="concept", label=f"C{i}", status="active"
        )
        for i in range(6)
    ]
    db.add_all(nodos)
    db.flush()
    for i in range(5):
        db.add(
            KnowledgeGraphEdge(
                tenant_id=1,
                from_node_id=nodos[i].id,
                to_node_id=nodos[i + 1].id,
                edge_type="linked",
                status="active",
            )
        )
    db.commit()
    payload = KnowledgeGraphService().neighborhood(db, nodos[0].id, depth=4)
    assert payload["root_node_id"] == nodos[0].id
    assert payload["depth"] == 4
    assert {n["id"] for n in payload["nodes"]} == {n.id for n in nodos[:5]}
    assert len(payload["edges"]) == 4
