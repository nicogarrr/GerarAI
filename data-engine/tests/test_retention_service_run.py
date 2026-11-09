"""Retención (2.ª tanda): RetentionService.run sobre varios tenants con
SessionLocal y settings doblados, la guarda sin tenant de purge_tenant y el
entrypoint run_retention del scheduler.

Sin red ni Postgres: SessionLocal se dobla a una fábrica SQLite en memoria;
no hay documentos, así que store/index nunca se llaman. Settings falsas por
monkeypatch (se restauran solas). Tenants sintéticos.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant
from app.services import retention_service as rs

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)

FAKE_SETTINGS = SimpleNamespace(
    retention_dry_run=True,
    financial_document_retention_days=30,
    chat_telemetry_retention_days=7,
    retention_batch_limit=500,
)


def _engine_con_tenants():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(external_id="ret-a", name="A", status="active"))
        session.add(Tenant(external_id="ret-b", name="B", status="active"))
        session.add(Tenant(external_id="ret-c", name="C", status="paused"))
        session.commit()
    return engine


@pytest.fixture
def session_local_doblada(monkeypatch):
    engine = _engine_con_tenants()
    monkeypatch.setattr(rs, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(rs, "get_settings", lambda: FAKE_SETTINGS)
    return engine


def test_run_recorre_solo_tenants_activos_y_totaliza(session_local_doblada):
    totals = rs.RetentionService().run(now=NOW)
    assert totals == {
        "dry_run": True,
        "cutoff_documents": (NOW - timedelta(days=30)).isoformat(),
        "cutoff_telemetry": (NOW - timedelta(days=7)).isoformat(),
        "tenants": 2,
        "documents_tombstoned": 0,
        "documents_examined": 0,
        "chunks_deleted": 0,
        "telemetry_deleted": 0,
        "external_failures": 0,
        "documents_deferred_evidence": 0,
        "database_failures": 0,
        "access_requests": {
            "engine": "mongodb_ttl",
            "note": "Las solicitudes de acceso no viven en Postgres; Mongo las expira por TTL.",
        },
    }


def test_run_filtra_por_tenant_ids(session_local_doblada):
    totals = rs.RetentionService().run(now=NOW, tenant_ids=[1])
    assert totals["tenants"] == 1


def test_run_respeta_dry_run_de_settings_por_defecto(session_local_doblada):
    # dry_run=None → toma settings.retention_dry_run (True en las falsas).
    totals = rs.RetentionService().run(now=NOW)
    assert totals["dry_run"] is True
    totals2 = rs.RetentionService().run(dry_run=False, now=NOW)
    assert totals2["dry_run"] is False


def test_purge_tenant_sin_contexto_de_tenant_lanza():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(ValueError, match="Tenant context is required for retention"):
            rs.RetentionService().purge_tenant(
                db,
                now=NOW,
                dry_run=True,
                retention_days=30,
                telemetry_days=7,
            )


def test_run_retention_entrypoint(session_local_doblada):
    totals = rs.run_retention()
    assert totals["tenants"] == 2
    assert totals["dry_run"] is True


def test_purge_tombstona_documento_sin_uri_externa(monkeypatch):
    # Documento viejo sin storage_uri: tombstone real sin borrado externo
    # (rama `if uri:` falsa), chunks eliminados y metadata de tombstone.
    # store/index doblados: sin red.
    from app.core.database import Base as BaseDB
    from app.models import Company, Document, DocumentChunk

    engine = create_engine("sqlite+pysqlite:///:memory:")
    BaseDB.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="ret-non-uri", name="NoUri")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        company = Company(
            ticker="NURI",
            name="NoUri Co",
            exchange="NASDAQ",
            currency="USD",
            sector="Technology",
            industry="Software",
            company_type="holding",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            title="Sin URI",
            source_type="SEC",
            storage_uri=None,
            published_at=NOW - timedelta(days=3000),
        )
        session.add(document)
        session.flush()
        session.add(DocumentChunk(document_id=document.id, chunk_index=0, text="texto"))
        session.commit()
        doc_id = document.id

        service = rs.RetentionService()
        monkeypatch.setattr(service.store, "delete", lambda uri: None)
        monkeypatch.setattr(service.index, "delete_document_points", lambda *args: None)
        result = service.purge_tenant(
            session,
            now=NOW,
            dry_run=False,
            retention_days=2555,
            telemetry_days=90,
        )

        assert result["documents_examined"] == 1
        assert result["documents_tombstoned"] == 1
        assert result["chunks_deleted"] == 1
        assert result["external_failures"] == 0
        session.expire_all()
        purgado = session.get(Document, doc_id)
        assert purgado.storage_uri is None
        assert purgado.retention_tombstoned_at == NOW.replace(tzinfo=None)
        assert purgado.metadata_["retention_tombstone"] == {
            "tombstoned_at": NOW.isoformat(),
            "policy_days": 2555,
            "reason": "financial_document_retention",
        }
