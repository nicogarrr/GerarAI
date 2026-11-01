"""Stable internal model names mapped to concrete OpenCode Go provider models.

Costes: OpenCode Go factura vía suscripción de opencode.ai/zen, SIN lista
pública de precios por token. Por eso ``input_cost``/``output_cost`` son
``Decimal("0")`` con ``cost_basis="unknown"`: el 0 es un MARCADOR DE
"DESCONOCIDO", nunca una afirmación de que el modelo sea gratis.
``cost_basis="list_price"`` exige costes positivos y solo debe usarse con
tarifas públicas verificables. La factura del proveedor siempre prevalece;
``BudgetController.estimate_cost_eur`` usa además estimaciones heurísticas
internas conservadoras para los topes de gasto (ver app/services/budget.py).

Modelo por defecto: ``Settings.opencode_go_model`` (env ``OPENCODE_GO_MODEL``,
ver app/core/config.py). ``default_model_from_env()`` expone la misma
resolución para código que no pasa por Settings.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelAlias:
    """Stable internal name mapped to a concrete provider model.

    Costs are list prices in USD per million tokens when ``cost_basis`` is
    ``"list_price"``. With ``cost_basis="unknown"`` (default) the zero costs
    are an explicit "unknown" placeholder, NOT a claim of being free.
    """

    internal_alias: str
    provider: str
    provider_model_id: str
    enabled: bool
    context_window: int
    input_cost: Decimal
    output_cost: Decimal
    supported_capabilities: frozenset[str]
    cost_basis: str = "unknown"

    def __post_init__(self) -> None:
        if not self.internal_alias.strip():
            raise ValueError("ModelAlias.internal_alias cannot be empty")
        if not self.provider.strip():
            raise ValueError("ModelAlias.provider cannot be empty")
        if not self.provider_model_id.strip():
            raise ValueError("ModelAlias.provider_model_id cannot be empty")
        if self.context_window <= 0:
            raise ValueError("ModelAlias.context_window must be positive")
        if self.input_cost < 0 or self.output_cost < 0:
            raise ValueError("ModelAlias costs cannot be negative")
        if self.cost_basis not in {"unknown", "list_price"}:
            raise ValueError("ModelAlias.cost_basis must be 'unknown' or 'list_price'")
        if self.cost_basis == "list_price" and (
            self.input_cost <= 0 or self.output_cost <= 0
        ):
            raise ValueError(
                "ModelAlias with cost_basis='list_price' requires positive costs; "
                "use cost_basis='unknown' when tariffs are not public"
            )
        if not self.supported_capabilities:
            raise ValueError("ModelAlias.supported_capabilities cannot be empty")

    @property
    def has_known_costs(self) -> bool:
        """True only when costs are verified public list prices."""
        return self.cost_basis == "list_price"


#: Env var that overrides the default cheap-but-good OpenCode Go model.
DEFAULT_MODEL_ENV_VAR = "OPENCODE_GO_MODEL"
#: Fallback when the env var is unset/blank. Kept in sync with
#: Settings.opencode_go_model in app/core/config.py.
DEFAULT_MODEL_FALLBACK = "deepseek-v4.1-flash"

#: Modelos gratuitos verificados; los guards de tareas fijadas aceptan solo estos
#: (ademas del modelo Go aprobado cuando la suscripcion esta confirmada).
VERIFIED_FREE_MODELS = frozenset({"deepseek-v4.1-flash-free", "space-bunny-free"})

#: Modelo cubierto por la suscripcion OpenCode Go contratada por el dueno.
#: NO es gratis: el coste es la suscripcion, no una tarifa por token.
GO_SUBSCRIPTION_MODELS = frozenset({"deepseek-v4.1-flash"})


def go_subscription_confirmed(settings: object) -> bool:
    """True si el dueno confirmo la suscripcion Go para este despliegue."""
    return bool(getattr(settings, "chat_go_subscription_enabled", False))


def verified_models(settings: object) -> frozenset[str]:
    """Modelos que los guards aceptan: free reales + Go aprobado si aplica.

    El nombre historico ``VERIFIED_FREE_MODELS`` se conserva para los free
    reales; este helper anade ``GO_SUBSCRIPTION_MODELS`` SOLO cuando la
    suscripcion Go esta confirmada, sin afirmar que el modelo Go sea gratis.
    """
    models = set(VERIFIED_FREE_MODELS)
    if go_subscription_confirmed(settings):
        models |= GO_SUBSCRIPTION_MODELS
    return frozenset(models)


def is_owner_approved_model(model: str, settings: object) -> bool:
    """True si ``model`` es free verificado o el Go aprobado por el dueno.

    El flag explicito ``opencode_go_allow_unverified_model`` (solo para un
    piloto auditado) tambien se acepta: el arranque de produccion ya lo exige.
    """
    if getattr(settings, "opencode_go_allow_unverified_model", False):
        return True
    return model in verified_models(settings)


def default_model_from_env(
    *, env_var: str = DEFAULT_MODEL_ENV_VAR, fallback: str = DEFAULT_MODEL_FALLBACK
) -> str:
    """Resolve the default model, overridable via environment.

    Lets ops switch to the current cheapest-good OpenCode Go model without a
    code change (e.g. ``OPENCODE_GO_MODEL=qwen3.7-plus``). Blank values fall
    back to ``fallback``.
    """
    return os.environ.get(env_var, fallback).strip() or fallback


class _ModelRoute(Protocol):
    @property
    def task(self) -> str: ...

    @property
    def model(self) -> str: ...


OPENCODE_GO_MODEL_ALIASES = (
    ModelAlias(
        # Cerebro aprobado por el dueno: cubierto por la suscripcion OpenCode
        # Go (no free, no tarifa por token). cost_basis="unknown" porque Go no
        # publica tarifa por token para la suscripcion.
        internal_alias="deepseek-v4.1-flash",
        provider="opencode-go",
        provider_model_id="deepseek-v4.1-flash",
        enabled=True,
        context_window=1_048_576,
        input_cost=Decimal("0"),
        output_cost=Decimal("0"),
        cost_basis="unknown",
        supported_capabilities=frozenset(
            {"text", "reasoning", "tool_calling", "structured_output"}
        ),
    ),
    ModelAlias(
        internal_alias="deepseek-v4.1-flash-free",
        provider="opencode-go",
        provider_model_id="deepseek-v4.1-flash-free",
        enabled=True,
        context_window=1_048_576,
        # OpenCode Go bills via subscription, no public per-token tariffs:
        # 0 = UNKNOWN placeholder (cost_basis="unknown"), not "free".
        input_cost=Decimal("0"),
        output_cost=Decimal("0"),
        cost_basis="unknown",
        supported_capabilities=frozenset(
            {"text", "reasoning", "tool_calling", "structured_output"}
        ),
    ),
    ModelAlias(
        # Stealth model de OpenCode (anuncio 2026-09-23): 1M contexto,
        # multimodal, zero data retention. Gratis en promocion de lanzamiento
        # (una semana); revisar precio/disponibilidad tras la promo.
        internal_alias="space-bunny-free",
        provider="opencode-go",
        provider_model_id="space-bunny-free",
        enabled=True,
        context_window=1_048_576,
        # Promo gratuita: sin tarifa publica por token; 0 = UNKNOWN
        # placeholder (cost_basis="unknown"), no "gratis para siempre".
        input_cost=Decimal("0"),
        output_cost=Decimal("0"),
        cost_basis="unknown",
        supported_capabilities=frozenset(
            {"text", "reasoning", "tool_calling", "structured_output"}
        ),
    ),
)


class ModelAliasRegistry:
    def __init__(self, aliases: Iterable[ModelAlias]) -> None:
        self.replace(aliases)

    def replace(self, aliases: Iterable[ModelAlias]) -> None:
        by_alias: dict[str, ModelAlias] = {}
        by_provider_id: dict[tuple[str, str], ModelAlias] = {}
        for alias in aliases:
            if alias.internal_alias in by_alias:
                raise ValueError(f"Duplicate model alias: {alias.internal_alias!r}")
            provider_key = (alias.provider, alias.provider_model_id)
            if provider_key in by_provider_id:
                raise ValueError(
                    f"Duplicate provider model id: {alias.provider}/{alias.provider_model_id}"
                )
            by_alias[alias.internal_alias] = alias
            by_provider_id[provider_key] = alias
        self._by_alias = MappingProxyType(by_alias)
        self._by_provider_id = MappingProxyType(by_provider_id)

    @property
    def aliases(self) -> Mapping[str, ModelAlias]:
        return self._by_alias

    def get(self, internal_alias: str) -> ModelAlias | None:
        return self._by_alias.get(internal_alias)

    def resolve(self, model: str, *, provider: str) -> str:
        alias = self._by_alias.get(model)
        if alias is None:
            registered_model = self._by_provider_id.get((provider, model))
            if registered_model is None:
                # Low-level adapters remain usable with explicit provider IDs.
                # Application task routes are checked strictly below.
                return model
            if not registered_model.enabled:
                raise ValueError(f"Provider model {model!r} is disabled")
            return model
        if not alias.enabled:
            raise ValueError(f"Model alias {model!r} is disabled")
        if alias.provider != provider:
            # La suscripcion Go y la capa free de Zen son el mismo proveedor
            # logico con otro nombre de adaptador (opencode-go-subscription /
            # opencode-free); sus modelos aprobados son los del registro de
            # opencode-go.
            if provider in {"opencode-go-subscription", "opencode-free"} and alias.provider == "opencode-go":
                return alias.provider_model_id
            raise ValueError(
                f"Model alias {model!r} belongs to provider {alias.provider!r}, "
                f"not active provider {provider!r}"
            )
        return alias.provider_model_id

    def validate_active_routes(
        self,
        routes: Iterable[_ModelRoute],
        *,
        provider: str,
        overrides: Mapping[str, str] | None = None,
    ) -> None:
        overrides = overrides or {}
        for route in routes:
            configured = overrides.get(route.task, overrides.get(route.model, route.model))
            registered = self._by_alias.get(configured) or self._by_provider_id.get(
                (provider, configured)
            )
            if registered is None:
                raise ValueError(
                    f"Active LLM task {route.task!r} references unknown model alias "
                    f"or provider model {configured!r}"
                )
            try:
                self.resolve(configured, provider=provider)
            except ValueError as exc:
                raise ValueError(
                    f"Active LLM task {route.task!r} references an unavailable model: {exc}"
                ) from exc


MODEL_ALIASES = ModelAliasRegistry(OPENCODE_GO_MODEL_ALIASES)


def configure_model_aliases(db) -> ModelAliasRegistry:
    """Load persisted aliases while preserving user enable/disable choices."""

    from sqlalchemy import select

    from app.models import ModelAlias as PersistedModelAlias

    existing = {
        (row.internal_alias, row.provider)
        for row in db.scalars(select(PersistedModelAlias)).all()
    }
    changed = False
    for alias in OPENCODE_GO_MODEL_ALIASES:
        if (alias.internal_alias, alias.provider) in existing:
            continue
        db.add(
            PersistedModelAlias(
                internal_alias=alias.internal_alias,
                provider=alias.provider,
                provider_model_id=alias.provider_model_id,
                enabled=alias.enabled,
                context_window=alias.context_window,
                input_cost=alias.input_cost,
                output_cost=alias.output_cost,
                supported_capabilities=sorted(alias.supported_capabilities),
            )
        )
        changed = True
    if changed:
        db.commit()

    rows = db.scalars(
        select(PersistedModelAlias).where(
            PersistedModelAlias.provider == "opencode-go"
        )
    ).all()
    MODEL_ALIASES.replace(
        ModelAlias(
            internal_alias=row.internal_alias,
            provider=row.provider,
            provider_model_id=row.provider_model_id,
            enabled=row.enabled,
            context_window=row.context_window,
            input_cost=Decimal(row.input_cost),
            output_cost=Decimal(row.output_cost),
            supported_capabilities=frozenset(row.supported_capabilities),
        )
        for row in rows
    )
    return MODEL_ALIASES
