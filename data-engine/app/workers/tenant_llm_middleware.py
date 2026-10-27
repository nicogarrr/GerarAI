"""Fija el proveedor LLM del tenant durante un mensaje de Dramatiq.

Los workers no pasan por las dependencias de FastAPI: sin este middleware,
una extraccion, tesis o resumen en segundo plano seguiria usando la clave de
la plataforma aunque el tenant tuviera la suya. El tenant sale del argumento
``tenant_id`` del actor (por firma, no por posicion).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

import dramatiq

logger = logging.getLogger(__name__)


def _tenant_id_from_message(broker: Any, message: Any) -> int | None:
    kwargs = dict(getattr(message, "kwargs", None) or {})
    value = kwargs.get("tenant_id")
    if isinstance(value, int):
        return value
    try:
        actor = broker.get_actor(message.actor_name)
        bound = inspect.signature(actor.fn).bind_partial(
            *(message.args or ()), **kwargs
        )
        value = bound.arguments.get("tenant_id")
    except Exception:  # noqa: BLE001 - el mensaje se procesa como antes
        return None
    return value if isinstance(value, int) else None


class TenantLLMSettingsMiddleware(dramatiq.Middleware):
    """Bind/restore del ContextVar por mensaje, en el hilo del worker."""

    def before_process_message(self, broker, message):
        from app.core.database import SessionLocal
        from app.llm.tenant_config import set_tenant_llm_config
        from app.services.tenant_llm_settings_service import load_config_for_tenant

        tenant_id = _tenant_id_from_message(broker, message)
        config = None
        if tenant_id is not None:
            db = SessionLocal()
            try:
                config = load_config_for_tenant(db, tenant_id)
            finally:
                db.close()
        token = set_tenant_llm_config(config)
        self._store_token(message, token)

    @staticmethod
    def _store_token(message, token) -> None:
        try:
            message.options["_tenant_llm_token"] = token
        except Exception:  # noqa: BLE001 - el cleanup degrada a no-op
            message._tenant_llm_token = token  # type: ignore[attr-defined]

    def _reset(self, message) -> None:
        from app.llm.tenant_config import reset_tenant_llm_config

        options = getattr(message, "options", None)
        token = None
        if isinstance(options, dict):
            token = options.pop("_tenant_llm_token", None)
        if token is None:
            token = getattr(message, "_tenant_llm_token", None)
        if token is not None:
            reset_tenant_llm_config(token)

    def after_process_message(self, broker, message, *, result=None, exception=None):
        del broker, result, exception
        self._reset(message)

    def after_skip_message(self, broker, message):
        del broker
        self._reset(message)
