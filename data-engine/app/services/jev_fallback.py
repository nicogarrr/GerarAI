"""Fallback tipado sobre el proveedor alternativo configurado (OpenCode Go
con la clave del despliegue). Su coste NO está verificado: no presentarlo
como gratuito.

La confianza del modelo generativo no es una probabilidad calibrada Jev: solo
marca/ordena; no puede tomar decisiones irreversibles ni excluir evidencia.
Las etiquetas generativas metadata-only no verifican hechos: no leerlas como
evidencia.
"""
from __future__ import annotations

import json
import math
from time import monotonic

from pydantic import BaseModel, Field

from app.llm.contracts import LLMRequest, Message
from app.llm.factory import create_llm_provider
from app.llm.jev import JevDecision
from app.services.prompt_registry import get_prompt

_PROMPT = get_prompt("jev_fallback", allow_remote=False)


class _Answer(BaseModel):
    choice: str
    confidence: float = Field(ge=0, le=1)


async def classify_free(text: str, *, instructions: str, criteria: dict[str, str]) -> JevDecision | None:
    provider = create_llm_provider()
    if provider.name == "disabled" or not criteria:
        return None
    started = monotonic()
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"choice": {"type": "string", "enum": list(criteria)},
                       "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
        "required": ["choice", "confidence"],
    }
    try:
        response = await provider.generate_json(
            LLMRequest(messages=(
                Message("system", _PROMPT.text),
                Message("user", json.dumps({"text": text[:2000], "instructions": instructions,
                                             "criteria": criteria}, ensure_ascii=False)),
            ), task="jev_fallback", metadata=_PROMPT.trace_metadata()), schema=schema, schema_name="jev_fallback",
        )
        result = _Answer.model_validate(response)
        if result.choice not in criteria or not math.isfinite(result.confidence):
            return None
        return JevDecision(label=result.choice, confidence=result.confidence,
                           model=provider.name, latency_s=round(monotonic()-started, 3),
                           backend="jev_fallback_alternative")
    except Exception:  # noqa: BLE001
        return None
