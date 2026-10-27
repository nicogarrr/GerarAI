from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.llm.adapters import DisabledProvider, OpenAICompatibleProvider
from app.llm.base import LLMProvider
from app.llm.cascade import CascadeProvider
from app.llm.model_aliases import VERIFIED_FREE_MODELS
from app.llm.response_cache import build_response_cache
from app.llm.tenant_config import TenantLLMConfig, current_tenant_llm_config


def _has_key(value: str | None) -> bool:
    return bool(value and value.strip())


def create_llm_provider(
    settings: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    total_timeout_seconds: float | None = None,
    reasoning_effort: str | None = None,
) -> LLMProvider:
    """Create the application LLM provider: OpenCode Go (default) or the free cascade.

    Los overrides (timeout_seconds, max_retries, total_timeout_seconds,
    reasoning_effort) solo aplican al primario OpenCode Go; la cascada
    gratuita usa sus propios presupuestos por miembro. None = valor de
    settings.
    """
    settings = settings or get_settings()
    tenant = current_tenant_llm_config()
    if tenant is not None:
        return _tenant_provider(
            tenant,
            settings,
            client=client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            total_timeout_seconds=total_timeout_seconds,
            reasoning_effort=reasoning_effort,
        )
    if not settings.llm_enabled:
        return DisabledProvider("disabled_by_configuration")

    requested = settings.llm_provider.strip().lower()
    if requested in {"auto", "opencode", "opencode_go"}:
        requested = "opencode-go"
    if requested not in {"opencode-go", "cascade", "disabled"}:
        raise ValueError(
            "GerarAI supports the OpenCode Go provider or the free cascade; "
            f"received {settings.llm_provider!r}"
        )
    if requested == "disabled":
        return DisabledProvider("disabled_by_configuration")
    if requested == "cascade":
        return _create_cascade(settings, client=client)
    if not _has_key(settings.opencode_go_api_key):
        return DisabledProvider("opencode_go_api_key_not_configured")

    return _opencode_go(
        settings,
        client=client,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        total_timeout_seconds=total_timeout_seconds,
        reasoning_effort=reasoning_effort,
    )


def _pin_routes_to_model(model: str) -> dict[str, str]:
    """Manda SOLO los modelos por defecto de las rutas al modelo indicado.

    A diferencia de ``_pin_to_model`` no toca alias explicitos (p. ej. el
    ``fallback_model``), que deben seguir siendo distintos del primario.
    """
    from app.services.llm_router import ROUTES

    return {route.model: model for route in ROUTES.values()}


def _pin_to_model(model: str) -> dict[str, str]:
    """Overrides que mandan al modelo `model` toda ruta o alias interno de OpenCode.

    Las rutas por tarea (`app/services/llm_router.py`) y los modelos fijados en
    codigo usan alias de OpenCode (`space-bunny-free`...). Un miembro de otro
    proveedor no los conoce y el registro de alias lo rechaza (alias de otro
    proveedor); sin esto, cualquier peticion con `task` fallaria en Gemini u
    OpenRouter. Los overrides del usuario (`llm_model_overrides`) siguen
    siendo solo de OpenCode.
    """
    from app.llm.model_aliases import MODEL_ALIASES
    from app.services.llm_router import ROUTES

    names = {route.model for route in ROUTES.values()} | set(MODEL_ALIASES.aliases)
    return dict.fromkeys(names, model)


def _tenant_provider(
    config: TenantLLMConfig,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None,
    timeout_seconds: float | None,
    max_retries: int | None,
    total_timeout_seconds: float | None,
    reasoning_effort: str | None,
) -> LLMProvider:
    """Proveedor del tenant; sin clave o fila corrupta se apaga (fail-closed).

    Nunca cae al proveedor global: si la fila existe, la plataforma no pone
    su clave. El unico camino que usa la clave de GerarAI es la ausencia total
    de fila (tenant sin configuracion propia).
    """
    if not config.enabled:
        return DisabledProvider("tenant_llm_disabled")
    if config.error:
        return DisabledProvider(config.error)
    if not config.has_api_key:
        return DisabledProvider("tenant_llm_key_missing")
    overrides = _pin_to_model(config.model)
    effort = config.reasoning_effort if reasoning_effort is None else reasoning_effort
    headers = {"User-Agent": "gerarai/1.0"}
    is_opencode_go = config.provider == "opencode-go"
    if is_opencode_go:
        # OpenCode Go rechaza con HTTP 400 MissingSessionID cualquier peticion
        # sin `x-opencode-session` (verificado en vivo el 2026-10-27 con la
        # clave del dueno). Sin esta cabecera, configurar OpenCode Go en
        # Ajustes dejaba el Cerebro y las tesis sin LLM.
        headers["x-opencode-session"] = settings.opencode_go_session
        if effort is None:
            # "Sin especificar" en Ajustes = el nivel por defecto del despliegue
            # (OPENCODE_GO_REASONING_EFFORT, `high`), igual que la ruta global.
            effort = settings.opencode_go_reasoning_effort
    try:
        provider = OpenAICompatibleProvider(
            api_key=str(config.api_key or ""),
            base_url=config.base_url,
            default_model=config.model,
            provider_name=config.provider,
            extra_headers=headers,
            # El endpoint Go rechaza `response_format` (json_schema) con 400;
            # mismo tratamiento que la ruta global (_opencode_go).
            strip_response_format=is_opencode_go,
            model_overrides=overrides,
            fallback_model=config.fallback_model or None,
            reasoning_effort=effort,
            reasoning_effort_models={
                model for model in (config.model, config.fallback_model) if model
            },
            response_cache=build_response_cache(settings),
            client=client,
            timeout_seconds=(
                settings.llm_timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            max_retries=(
                settings.llm_max_retries if max_retries is None else max_retries
            ),
            total_timeout_seconds=(
                settings.llm_total_timeout_seconds
                if total_timeout_seconds is None
                else total_timeout_seconds
            ),
            max_output_tokens=settings.llm_max_output_tokens,
        )
    except (ValueError, TypeError):
        return DisabledProvider("tenant_llm_settings_invalid")
    provider.billing_scope = "tenant"
    return provider


def _create_cascade(settings: Settings, *, client: httpx.AsyncClient | None) -> LLMProvider:
    """Gemini -> OpenRouter :free -> OpenCode, solo los miembros con clave."""
    members: list[LLMProvider] = []
    shared = {
        "client": client,
        "timeout_seconds": settings.llm_cascade_member_timeout_seconds,
        "max_retries": settings.llm_cascade_member_max_retries,
        "total_timeout_seconds": settings.llm_cascade_member_total_timeout_seconds,
        "max_output_tokens": settings.llm_max_output_tokens,
    }
    if _has_key(settings.gemini_api_key):
        members.append(
            OpenAICompatibleProvider(
                api_key=str(settings.gemini_api_key),
                base_url=settings.gemini_base_url,
                default_model=settings.gemini_model,
                provider_name="gemini",
                model_overrides=_pin_to_model(settings.gemini_model),
                response_cache=build_response_cache(settings),
                **shared,
            )
        )
    if _has_key(settings.openrouter_api_key):
        members.append(
            OpenAICompatibleProvider(
                api_key=str(settings.openrouter_api_key),
                base_url=settings.openrouter_base_url,
                default_model=settings.openrouter_model,
                provider_name="openrouter",
                model_overrides=_pin_to_model(settings.openrouter_model),
                response_cache=build_response_cache(settings),
                **shared,
            )
        )
    if _has_key(settings.opencode_go_api_key):
        members.append(_opencode_go(settings, client=client))
    if not members:
        return DisabledProvider("cascade_without_any_api_key")
    return CascadeProvider(members, total_timeout_seconds=settings.llm_cascade_total_timeout_seconds)


def _opencode_go(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    total_timeout_seconds: float | None = None,
    reasoning_effort: str | None = None,
) -> OpenAICompatibleProvider:
    overrides = settings.llm_model_overrides
    if settings.opencode_go_model in VERIFIED_FREE_MODELS:
        # Free/legacy: las rutas por defecto apuntan al modelo Go. Si el
        # operador elige un free (bridge), se fijan todas las rutas a ese
        # modelo para que ninguna llamada acabe pidiendo el Go al bridge.
        overrides = {**_pin_routes_to_model(settings.opencode_go_model), **overrides}
    provider = OpenAICompatibleProvider(
        api_key=settings.opencode_go_api_key,
        base_url=settings.opencode_go_base_url,
        default_model=settings.opencode_go_model,
        provider_name="opencode-go",
        extra_headers={
            # OpenCode Go documenta: user agent propio (no el generico de la
            # libreria HTTP) + session id estable. https://opencode.ai/docs/go/
            "User-Agent": "gerarai/1.0",
            "x-opencode-session": settings.opencode_go_session,
        },
        model_overrides=overrides,
        fallback_model=settings.opencode_go_fallback_model,
        # El endpoint /zen/go/v1 rechaza `response_format` con HTTP 400
        # (verificado en vivo por el piloto el 2026-10-26 con
        # deepseek-v4.1-flash: json_schema estricto -> 400; json_object/plain
        # -> 200). Sin este ajuste TODA salida estructurada (narrativa de
        # tesis, KPI, ASTS, second-order) falla contra Go directo. El
        # contrato viaja en el prompt y la validacion local fail-closed de
        # cada llamador sigue siendo la puerta, como en el chat.
        strip_response_format=True,
        reasoning_effort=(
            settings.opencode_go_reasoning_effort
            if reasoning_effort is None
            else reasoning_effort
        ),
        reasoning_effort_models={
            model.strip()
            for model in settings.opencode_go_reasoning_effort_models.split(",")
            if model.strip()
        },
        response_cache=build_response_cache(settings),
        client=client,
        timeout_seconds=(
            settings.llm_timeout_seconds if timeout_seconds is None else timeout_seconds
        ),
        max_retries=settings.llm_max_retries if max_retries is None else max_retries,
        total_timeout_seconds=(
            settings.llm_total_timeout_seconds
            if total_timeout_seconds is None
            else total_timeout_seconds
        ),
        hidden_reasoning_models={
            model.strip()
            for model in settings.llm_hidden_reasoning_models.split(",")
            if model.strip()
        },
        hidden_reasoning_min_tokens=settings.llm_hidden_reasoning_min_tokens,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    # Fail-closed opcional: sin guard de corrida activo no sale ningun POST.
    provider.guard_required = bool(settings.llm_run_guard_required)
    return provider


create_provider = create_llm_provider


def validate_llm_configuration(settings: Settings | None = None) -> None:
    """Validate the single-provider configuration without making a request."""
    provider = create_llm_provider(settings or get_settings())
    if provider.name != "disabled":
        return
