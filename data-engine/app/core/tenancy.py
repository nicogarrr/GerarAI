"""Predicados explicitos de tenant: segunda capa sobre el loader criteria.

`with_loader_criteria` en app/core/database.py acota TODOS los selects ORM
con contexto de tenant: entity loads y tambien column selects de entidad
(`select(Model.column)`), agregados (`func.count`/`func.max`), GROUP BY,
joins, subqueries IN y window functions. Medido en SQLAlchemy 2.1.6 (rango
fijado >=2.0.32,<2.2) y fijado por
tests/test_tenant_column_isolation.py::test_loader_criteria_scopes_column_and_aggregate_selects_too,
que rompe CI si un bump de SQLAlchemy cambia ese comportamiento.

Aun asi, toda lectura de un modelo ``TenantOwnedMixin`` debe seguir usando
:func:`tenant_filters` (``*tenant_filters(db, Model)`` en el where/subquery):

1. Defensa en profundidad: si el criteria se pierde (un refactor del hook,
   un ``include_all_tenants`` mal puesto, un bump de SQLAlchemy), la
   consulta sigue acotada.
2. Fail-closed: sin contexto de tenant y con auth obligatoria o en
   produccion, :func:`tenant_filters` levanta en vez de leer todos los
   tenants; el criteria simplemente no se activa sin tenant en la sesion.
3. Ejecuciones no-ORM (``db.connection().execute(...)``, ``text()``) nunca
   pasan por el criteria: ahi el predicado explicito es la UNICA capa.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import TenantOwnedMixin

# Re-export tenant_cache_scope from llm.response_cache for backward compatibility
try:
    from app.llm.response_cache import tenant_cache_scope
except ImportError:
    # Fallback if llm module not available yet during import
    tenant_cache_scope = None  # type: ignore[assignment]


def tenant_filters(
    db: Session, *models: type[TenantOwnedMixin]
) -> list[ColumnElement[bool]]:
    """Return ``model.tenant_id == db.info["tenant_id"]`` for each model.

    Mirrors ``_scope_tenant_queries``: without tenant context in dev/test the
    list is empty (legacy unscoped behavior), but with auth required or in
    production it fails closed instead of reading every tenant's rows.
    """
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        settings = get_settings()
        if settings.research_auth_required or settings.is_production:
            raise RuntimeError(
                "Tenant context is required for tenant-owned column reads"
            )
        return []
    return [model.tenant_id == tenant_id for model in models]
