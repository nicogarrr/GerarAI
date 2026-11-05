"""Pipeline de inputs de la tesis: Recopilador y mezcla de analistas, en orden.

Es la costura que usará el gancho de la tesis: primero el Recopilador hace el
inventario de impulsores y, cuando termina, la mezcla de analistas rellena los
huecos del modelo. Cada etapa corre por separado y con su propio plazo: un
fallo del Recopilador no impide la mezcla y un fallo de la mezcla no rompe la
generación de la tesis. No commitea la sesión; los servicios de debajo hacen
sus propios ``flush``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import current_language
from app.services.async_bridge import run_from_any_context
from app.services.expert_team.analyst_blend import run_analyst_blend
from app.services.expert_team.models import RunContext
from app.services.expert_team.recopilador import run_recopilador
from app.services.expert_team.service import provider_reasoner

#: Estados de etapa que cuentan como resultado aprovechable (no son errores).
USABLE_STATUSES: frozenset[str] = frozenset(
    {"stored", "full_data", "no_assumptions", "no_firms", "no_data"}
)


@dataclass
class PipelineInputsResult:
    """Qué dejó el pipeline de inputs en una corrida."""

    status: str  # disabled | no_tenant | ok | partial | error
    recopilador: dict[str, Any] = field(default_factory=dict)
    analista: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recopilador": dict(self.recopilador),
            "analista": dict(self.analista),
            "errors": list(self.errors),
        }


def _jsonable(value: Any) -> Any:
    """Convierte fechas, decimales y contenedores a tipos que ``json.dumps`` acepta."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _stage_dict(result: Any) -> dict[str, Any]:
    """Resultado de una etapa como diccionario serializable."""
    if result is None:
        return {}
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        data: Any = dataclasses.asdict(result)
    else:
        try:
            data = dict(cast(Any, result))
        except (TypeError, ValueError):
            return {"status": str(result)}
    return _jsonable(data)


def _pipeline_status(
    recopilador: dict[str, Any], analista: dict[str, Any], errors: Sequence[str]
) -> str:
    statuses = (recopilador.get("status"), analista.get("status"))
    stage_error = "error" in statuses
    usable = any(status in USABLE_STATUSES for status in statuses)
    if not errors and not stage_error:
        return "ok"
    if usable:
        return "partial"
    return "error"


def run_pipeline_inputs(
    db: Session,
    company: Any,
    *,
    reasoner: Any | None = None,
    history: Any | None = None,
    load_history: Any | None = None,
    extra_sources: Sequence[Any] = (),
    enabled: bool | None = None,
    timeout: float = 90.0,
) -> PipelineInputsResult:
    """Corre Recopilador y mezcla de analistas para ``company``, en ese orden.

    ``enabled`` None = ``EXPERT_TEAM_ENABLED``. Apagado no toca la base ni el
    LLM. Sin tenant válido no se ejecuta nada. Cada etapa tiene su ``timeout``
    y sus excepciones se recogen sin impedir la otra etapa.
    """
    if enabled is None:
        enabled = bool(get_settings().expert_team_enabled)
    if not enabled:
        return PipelineInputsResult(status="disabled")

    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return PipelineInputsResult(status="no_tenant")

    ctx = RunContext(
        tenant_id=tenant_id,
        ticker=company.ticker.strip().upper(),
        mode="thesis",
        lang=current_language(),
    )
    if reasoner is None:
        reasoner = provider_reasoner(db=db)

    errors: list[str] = []

    def run_stage(label: str, coro_factory: Callable[[], Any]) -> dict[str, Any]:
        try:
            return _stage_dict(run_from_any_context(coro_factory(), timeout=timeout))
        except Exception as exc:
            errors.append(f"{label}:{type(exc).__name__}")
            return {}

    recopilador = run_stage(
        "recopilador",
        lambda: run_recopilador(db, ctx=ctx, reasoner=reasoner, enabled=True),
    )
    analista = run_stage(
        "analista",
        lambda: run_analyst_blend(
            db,
            ctx=ctx,
            reasoner=reasoner,
            history=history,
            load_history=load_history,
            extra_sources=extra_sources,
            enabled=True,
        ),
    )
    return PipelineInputsResult(
        status=_pipeline_status(recopilador, analista, errors),
        recopilador=recopilador,
        analista=analista,
        errors=errors,
    )


__all__ = ["PipelineInputsResult", "run_pipeline_inputs"]
