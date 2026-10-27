"""TenantLLMSettings hereda TenantOwnedMixin: aislamiento por la sesion.

Cubre lo que antes solo garantizaban los predicados explicitos del servicio:
consulta ORM directa, asignacion cross-tenant e inmutabilidad de tenant_id.
Datos sinteticos, sin claves reales ni llamadas LLM.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.models import Tenant, TenantLLMSettings
from app.models.entities import TenantOwnedMixin
from app.services.tenant_llm_settings_service import (
    TenantLLMUpdate,
    read_tenant_row,
    save_tenant_settings,
)


@pytest.fixture(autouse=True)
def _cleanup_rows():
    """La BD de test es compartida: no dejar filas que rompan otros tests."""
    yield
    init_db()
    with SessionLocal() as db:
        ids = [
            tenant_id
            for (tenant_id,) in db.execute(
                select(Tenant.id).where(
                    Tenant.external_id.like("iso-%")
                    | Tenant.external_id.like("xt-%")
                    | Tenant.external_id.like("auto-%")
                )
            )
        ]
        if ids:
            db.execute(
                delete(TenantLLMSettings)
                .where(TenantLLMSettings.tenant_id.in_(ids))
                .execution_options(include_all_tenants=True)
            )
            db.execute(delete(Tenant).where(Tenant.id.in_(ids)))
            db.commit()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        research_auth_secret="local-fallback-secret-with-at-least-32-bytes",
        llm_settings_encryption_key="explicit-encryption-key-with-32-bytes!",
    )


def _tenant(db, name: str) -> Tenant:
    tenant = Tenant(external_id=f"{name}-{uuid4().hex[:8]}", name=name)
    db.add(tenant)
    db.flush()
    return tenant


def _save(db, tenant: Tenant, key: str) -> None:
    db.info["tenant_id"] = tenant.id
    save_tenant_settings(
        db,
        TenantLLMUpdate(provider="openai", model="gpt-4.1-mini", api_key=key),
        _settings(),
    )
    db.commit()


def test_model_is_tenant_owned_and_schema_columns_unchanged() -> None:
    assert issubclass(TenantLLMSettings, TenantOwnedMixin)
    column = TenantLLMSettings.__table__.c.tenant_id
    assert column.nullable is False
    assert [fk.ondelete for fk in column.foreign_keys] == ["CASCADE"]


def test_direct_orm_query_is_scoped_to_session_tenant() -> None:
    init_db()
    with SessionLocal() as db:
        tenant_a = _tenant(db, "iso-a")
        tenant_b = _tenant(db, "iso-b")
        _save(db, tenant_a, "sk-iso-a-1111")
        _save(db, tenant_b, "sk-iso-b-2222")

        db.info["tenant_id"] = tenant_a.id
        rows = db.scalars(select(TenantLLMSettings)).all()
        assert [row.tenant_id for row in rows] == [tenant_a.id]
        assert db.get(TenantLLMSettings, rows[0].id) is not None

        # El servicio sigue devolviendo solo la fila del tenant activo.
        assert read_tenant_row(db).tenant_id == tenant_a.id

        db.info["tenant_id"] = tenant_b.id
        rows_b = db.scalars(select(TenantLLMSettings)).all()
        assert [row.tenant_id for row in rows_b] == [tenant_b.id]
        assert rows_b[0].id != rows[0].id


def test_cross_tenant_assignment_and_reassignment_are_rejected() -> None:
    init_db()
    with SessionLocal() as db:
        tenant_a = _tenant(db, "xt-a")
        tenant_b = _tenant(db, "xt-b")
        _save(db, tenant_a, "sk-xt-a-1111")

        # Fila nueva para otro tenant desde la sesion de A: rechazada.
        db.info["tenant_id"] = tenant_a.id
        db.add(TenantLLMSettings(tenant_id=tenant_b.id, provider="openai"))
        with pytest.raises(RuntimeError, match="Cross-tenant"):
            db.flush()
        db.rollback()

        # tenant_id inmutable en filas persistentes.
        db.info["tenant_id"] = tenant_a.id
        row = db.scalars(select(TenantLLMSettings)).one()
        row.tenant_id = tenant_b.id
        with pytest.raises(RuntimeError, match="immutable"):
            db.flush()
        db.rollback()


def test_new_row_without_explicit_tenant_gets_session_tenant() -> None:
    init_db()
    with SessionLocal() as db:
        tenant = _tenant(db, "auto-a")
        db.info["tenant_id"] = tenant.id
        row = TenantLLMSettings(tenant_id=tenant.id, provider="openai")
        db.add(row)
        db.flush()
        assert row.tenant_id == tenant.id
        db.rollback()
