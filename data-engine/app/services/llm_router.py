"""Rutas LLM por tarea y capacidades que cada ruta REQUIERE.

`required_capabilities` es la unica fuente de verdad de "que necesita esta
ruta". Antes el router declaraba `agentic_red_team` como "tool-using
adversarial review" y `tool_workflow` como "complex tool calling" sin que
nadie comprobara que el adaptador pudiera usar herramientas: `_complete()`
nunca enviaba `tools`. Una capacidad afirmada y no implementada es peor que
no tenerla, porque el resto del sistema razona sobre una mentira.

Ahora el adaptador SI implementa tool calling (ver
`app.llm.base.ADAPTER_CAPABILITIES`) y `unsupported_routes()` deja la
coherencia verificable: `tests/test_llm_tool_calling.py` falla si una ruta exige
algo que el adaptador no hace, y falla si el adaptador deja de hacerlo sin que
la ruta lo refleje.
"""

from dataclasses import dataclass, field

#: Tool calling es una capacidad del ADAPTADOR, no de una ruta concreta.
_TOOL = frozenset({"tool_calling"})
_TEXT = frozenset({"text"})


@dataclass(frozen=True)
class ModelRoute:
    task: str
    model: str
    reason: str
    max_materiality: int | None = None
    required_capabilities: frozenset[str] = field(default=_TEXT)


ROUTES = {
    "cheap_extraction": ModelRoute("cheap_extraction", "deepseek-v4.1-flash", "low-cost structured extraction"),
    "main_financial_analysis": ModelRoute("main_financial_analysis", "deepseek-v4.1-flash", "source-grounded financial analysis"),
    "agentic_red_team": ModelRoute(
        "agentic_red_team",
        "deepseek-v4.1-flash",
        "adversarial review that MAY request tools; no tools are registered, so "
        "the run stays single-shot and deterministic",
        required_capabilities=_TOOL,
    ),
    "news_triage": ModelRoute("news_triage", "deepseek-v4.1-flash", "cheap high-volume triage"),
    "dedupe_news": ModelRoute("dedupe_news", "deepseek-v4.1-flash", "cheap semantic dedupe"),
    "claim_extraction": ModelRoute("claim_extraction", "deepseek-v4.1-flash", "structured extraction"),
    "kpi_extraction": ModelRoute("kpi_extraction", "deepseek-v4.1-flash", "company-specific KPI extraction"),
    "pdf_summary": ModelRoute("pdf_summary", "deepseek-v4.1-flash", "long-context extraction summary"),
    "chat": ModelRoute("chat", "deepseek-v4.1-flash", "grounded portfolio chat"),
    "thesis_update": ModelRoute("thesis_update", "deepseek-v4.1-flash", "partial thesis update"),
    "deep_thesis": ModelRoute("deep_thesis", "deepseek-v4.1-flash", "deep thesis workflow"),
    "red_team": ModelRoute("red_team", "deepseek-v4.1-flash", "adversarial review; the model may request tools but none are registered"),
    "source_audit": ModelRoute("source_audit", "deepseek-v4.1-flash", "critical source audit"),
    "tool_workflow": ModelRoute(
        "tool_workflow",
        "deepseek-v4.1-flash",
        "tool-calling workflow; the adapter sends `tools` when a caller registers "
        "them, and this app registers none, so the route is single-shot",
        required_capabilities=_TOOL,
    ),
    "code": ModelRoute("code", "deepseek-v4.1-flash", "product coding"),
    "premium_financial_analysis": ModelRoute("premium_financial_analysis", "deepseek-v4.1-flash", "eval-gated premium escalation"),
    "bottleneck_discovery": ModelRoute(
        "bottleneck_discovery", "deepseek-v4.1-flash", "owner-approved inferred candidates per bottleneck theme"
    ),
    "fallback": ModelRoute("fallback", "deepseek-v4.1-flash", "cheap fallback"),
}


def route_model(task: str, materiality_score: int = 0, portfolio_weight: float = 0) -> ModelRoute:
    if task == "deep_thesis" and materiality_score < 7 and portfolio_weight < 0.05:
        return ROUTES["thesis_update"]
    if task == "red_team" and materiality_score < 8 and portfolio_weight < 0.08:
        return ROUTES["thesis_update"]
    return ROUTES.get(task, ROUTES["fallback"])


def unsupported_routes(capabilities) -> list[str]:
    """Rutas que exigen una capacidad que `capabilities` no incluye.

    Con las capacidades reales del adaptador la lista esta vacia. Con un
    adaptador sin tool calling devuelve `agentic_red_team` y `tool_workflow`:
    es exactamente el defecto que se quiere hacer visible.
    """
    supported = frozenset(capabilities or ())
    return sorted(
        route.task
        for route in ROUTES.values()
        if not route.required_capabilities <= supported
    )


def route_table() -> list[dict]:
    from app.llm.model_aliases import MODEL_ALIASES

    rows = []
    for route in ROUTES.values():
        alias = MODEL_ALIASES.get(route.model)
        rows.append(
            {
                **route.__dict__,
                "required_capabilities": sorted(route.required_capabilities),
                "provider": alias.provider if alias else None,
                "provider_model_id": alias.provider_model_id if alias else None,
                "enabled": alias.enabled if alias else False,
                "context_window": alias.context_window if alias else None,
                "input_cost": str(alias.input_cost) if alias else None,
                "output_cost": str(alias.output_cost) if alias else None,
                "supported_capabilities": sorted(alias.supported_capabilities) if alias else [],
            }
        )
    return rows
