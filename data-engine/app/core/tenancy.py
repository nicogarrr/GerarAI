"""Explicit tenant predicates for reads that bypass ORM entity loading.

`with_loader_criteria` in app/core/database.py scopes ORM entity loads. A
`select(Model.column)` or an aggregate (`func.count`, `func.max`, a window
function) is a column query and can be compiled without that criteria
(SQLAlchemy 2.0), so every read of a ``TenantOwnedMixin`` model must add its
own tenant predicate. Use :func:`tenant_filters` as ``*tenant_filters(db,
Model)`` in the ``where``/subquery of those reads.
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
