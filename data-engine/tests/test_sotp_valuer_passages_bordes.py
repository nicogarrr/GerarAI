"""Selección de pasajes con SQL SQLite real y sin red ni modelo."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, DocumentChunk, Tenant
from app.services.expert_team import sotp_valuer as svc
from app.services.expert_team.models import RunContext


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add_all([Tenant(id=1, external_id="passage1"), Tenant(id=2, external_id="passage2")])
            session.flush()
            yield session
    finally:
        engine.dispose()


def test_pasajes_filtro_empresa_tenant_tombstone_tope_y_cita(db):
    companies = []
    for ticker in ("PASSAGE", "OTHER"):
        c = Company(
            ticker=ticker,
            name=ticker,
            exchange="TEST",
            currency="USD",
            company_type="operating",
            valuation_model="unassigned",
        )
        db.add(c)
        companies.append(c)
    db.flush()

    def document(tenant, company, title, tombstone=False):
        db.info["tenant_id"] = tenant
        doc = Document(
            tenant_id=tenant,
            company_id=company.id,
            title=title,
            source_type="SEC",
            source_url=f"https://example.test/{title}",
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            retention_tombstoned_at=datetime(2026, 1, 2, tzinfo=UTC) if tombstone else None,
        )
        db.add(doc)
        db.flush()
        for i, text in enumerate(
            [
                "irrelevant",
                "SHARES   OUTSTANDING 100",
                "shares outstanding 200",
                "shares outstanding " + "x" * 1600,
                "shares outstanding over-limit",
            ]
        ):
            db.add(
                DocumentChunk(tenant_id=tenant, document_id=doc.id, chunk_index=i, text=text, token_count=3)
            )
        db.commit()

    document(1, companies[0], "own")
    document(2, companies[0], "foreign-tenant")
    document(1, companies[1], "foreign-company")
    document(1, companies[0], "deleted", tombstone=True)
    db.info["tenant_id"] = 1
    tool = svc.share_count_documents_tool(db)
    assert tool.fn(RunContext(tenant_id=1, ticker=None)) == []
    assert tool.fn(RunContext(tenant_id=1, ticker="ABSENT")) == []
    out = tool.fn(RunContext(tenant_id=1, ticker="PASSAGE"))
    assert len(out) == 3
    assert [item.source["title"] for item in out] == ["own"] * 3
    assert out[0].data["text"] == "SHARES   OUTSTANDING 100"
    assert out[1].data["text"] == "shares outstanding 200"
    assert len(out[2].data["text"]) == 1500
    assert out[0].source["url"] == "https://example.test/own"
    assert out[0].source["date"] == "2026-01-01"
    assert svc.balance_asset_documents_tool(db).fn(RunContext(tenant_id=1, ticker="PASSAGE")) == []


def test_value_drivers_conserva_fuente_y_solo_vigentes_del_tenant(db):
    from app.models.value_driver import ValueDriver

    company = Company(
        ticker="DRIVERTEST",
        name="Driver",
        exchange="TEST",
        currency="USD",
        company_type="operating",
        valuation_model="unassigned",
    )
    db.add(company)
    db.flush()
    for tenant, key, expired in [(1, "active", False), (1, "old", True), (2, "foreign", False)]:
        db.info["tenant_id"] = tenant
        db.add(
            ValueDriver(
                tenant_id=tenant,
                company_id=company.id,
                driver_key=key,
                category="contrato",
                name=key,
                status="firmado",
                source_type="filing",
                evidence="oficial",
                treatment="pendiente",
                economics={"amount": 1},
                timing="2027",
                source_url="https://example.test/filing",
                source_quote="q" * 700,
                as_of=datetime(2026, 1, 1).date(),
                superseded_at=datetime(2026, 1, 2, tzinfo=UTC) if expired else None,
            )
        )
        db.commit()
    db.info["tenant_id"] = 1
    tool = svc.value_drivers_tool(db)
    assert tool.fn(RunContext(tenant_id=1, ticker=None)) == []
    assert tool.fn(RunContext(tenant_id="1", ticker="DRIVERTEST")) == []
    assert tool.fn(RunContext(tenant_id=1, ticker="ABSENT")) == []
    out = tool.fn(RunContext(tenant_id=1, ticker="DRIVERTEST"))
    assert len(out) == 1 and out[0].source["title"] == "active"
    assert out[0].source["url"] == "https://example.test/filing"
    assert out[0].source["date"] == "2026-01-01"
    assert out[0].data == {
        "name": "active",
        "category": "contrato",
        "status": "firmado",
        "economics": {"amount": 1},
        "timing": "2027",
        "evidence": "oficial",
        "quote": "q" * 600,
    }
