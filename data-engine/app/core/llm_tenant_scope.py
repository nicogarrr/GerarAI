"""Fija el tenant verificado como alcance de la cache de respuestas LLM.

``app.llm.response_cache`` falla cerrada sin tenant (no lee ni escribe), y
nadie entraba en ``tenant_cache_scope``: la cache estaba inerte salvo en el
unico servicio que pasa ``metadata["tenant_id"]``. Esta dependencia entra en el
scope con el tenant YA verificado por la firma, para todo el request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends

from app.core.auth import ResearchPrincipal, get_research_principal
from app.llm.response_cache import tenant_cache_scope


async def bind_llm_cache_tenant(
    principal: ResearchPrincipal | None = Depends(get_research_principal),
) -> AsyncIterator[None]:
    tenant = principal.tenant_external_id if principal is not None else None
    with tenant_cache_scope(tenant):
        yield
