"""Provider Go DEDICADO a las narrativas de tesis (extensa y de noticias).

Contrato (decisión 2026-10-26, tras evidencia VM del piloto: la generación
es síncrona en la API y en worker-thesis; inyectar env solo en el worker NO
basta — la factoría resuelve en ambos porque vive en el código de la
narrativa):

- ``thesis_go_enabled`` falso (defecto): devuelve el provider GLOBAL de
  siempre; comportamiento previo intacto, ni chat ni otros consumidores
  estructurados se tocan.
- Enabled + config válida: OpenCode Go dedicado con endpoint, key y modelo
  PROPIOS (``THESIS_GO_*``), sin fallback y sin overrides de rutas: el
  adaptador hereda el strip de ``response_format`` (fix #2181) y los
  timeouts/retries existentes, y cada narrativa sigue pidiendo su
  ``reasoning_effort`` por request (#2183) y registrando modelo
  ejecutado/finish/uso reales.
- Enabled + config inválida (sin key, endpoint distinto del aprobado,
  modelo fuera de la allowlist): ``DisabledProvider`` con motivo. Las
  narrativas ya fallan cerrado ante ``provider.name == "disabled"``; NUNCA
  se cae al bridge global presentándolo como Go.

Sin contadores propios (BD/Redis/cuotas): la acotación es la existente
(BudgetController + retries del adaptador + ExtraUsage OFF que verifica
ops); los intentos reales quedan en la traza del provider.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import Settings, get_settings
from app.llm.adapters import DisabledProvider
from app.llm.base import LLMProvider
from app.llm.factory import _opencode_go, create_llm_provider
from app.llm.tenant_config import current_tenant_llm_config

logger = logging.getLogger(__name__)

#: Endpoint Go aprobado. Cualquier otro (incluido un bridge local) invalida
#: la config dedicada: una URL distinta podría servir otro modelo cobrando
#: como Go.
THESIS_GO_ENDPOINT = "https://opencode.ai/zen/go/v1"

#: Allowlist cerrada del modelo aprobado para las narrativas de tesis.
THESIS_GO_ALLOWED_MODELS = frozenset({"deepseek-v4.1-flash"})


def create_thesis_narrative_provider(
    settings: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> LLMProvider:
    """Provider para las narrativas de tesis según ``THESIS_GO_ENABLED``.

    Ver docstring del módulo: global si disabled, Go dedicado si enabled y
    válido, ``DisabledProvider`` con motivo si enabled e inválido.
    """
    settings = settings or get_settings()
    if current_tenant_llm_config() is not None:
        return create_llm_provider(settings, client=client)
    if not getattr(settings, "thesis_go_enabled", False):
        return create_llm_provider(settings, client=client)

    base_url = (settings.thesis_go_base_url or "").strip().rstrip("/")
    model = (settings.thesis_go_model or "").strip()
    key = settings.thesis_go_api_key
    if base_url != THESIS_GO_ENDPOINT:
        logger.warning(
            "thesis Go dedicado: endpoint no aprobado (%r); narrativa omitida",
            base_url,
        )
        return DisabledProvider("thesis_go_endpoint_not_approved")
    if not (key and key.strip()):
        logger.warning("thesis Go dedicado: sin THESIS_GO_API_KEY; narrativa omitida")
        return DisabledProvider("thesis_go_api_key_not_configured")
    if model not in THESIS_GO_ALLOWED_MODELS:
        logger.warning(
            "thesis Go dedicado: modelo %r fuera de la allowlist; narrativa omitida",
            model,
        )
        return DisabledProvider("thesis_go_model_not_allowed")

    dedicated = settings.model_copy(
        update={
            "llm_provider": "opencode-go",
            "llm_model_overrides": {},
            "opencode_go_api_key": key,
            "opencode_go_base_url": THESIS_GO_ENDPOINT,
            "opencode_go_model": model,
            # Fail-closed real: sin fallback interno del adaptador. Si Go
            # falla, la narrativa se omite; nunca otro modelo facturable
            # presentado como Go.
            "opencode_go_fallback_model": "",
        }
    )
    return _opencode_go(dedicated, client=client)
