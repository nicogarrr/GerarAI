"""Cliente de decisiones TypeSafe Jev (SystemOne API).

Jev no genera texto: responde preguntas tipadas sobre un `state` con
probabilidades calibradas. Uso en GerarAI: capa barata de micro-decisiones
(triage de alertas, clasificación en ingesta) delante del LLM principal.
Referencia: https://docs.typesafe.ai (OpenAPI en api.typesafe.ai/openapi.json).

Coste: $0.042 / millón de tokens de entrada, salida gratis.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import httpx

from app.llm.run_guard import LLMGuardAbort, reserve_post_without_tokens


@dataclass(frozen=True)
class JevDecision:
    """Una respuesta `choice` normalizada: etiqueta + confianza calibrada."""

    label: str
    confidence: float
    probabilities: Mapping[str, float] = field(default_factory=dict)
    model: str = ""
    latency_s: float = 0.0
    backend: str = "jev"


class JevAuthError(RuntimeError):
    """401/403 sin señal de facturación: credencial o permiso, NO crédito."""


class JevCreditExhausted(RuntimeError):
    """Rechazo de facturacion: no debe reintentarse ni ocultarse como 5xx."""


class JevDecisionClient:
    """Cliente mínimo async sobre POST /v1/systemone (Bearer)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.typesafe.ai",
        default_model: str = "jev-latest",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client = client
        #: True = fail-closed: sin guard activo no se envia nada.
        self.guard_required = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def systemone(
        self,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
        model: str | None = None,
    ) -> dict[str, Any]:
        """Llama cruda a /v1/systemone; devuelve el JSON (answers+usage)."""
        payload = {
            "model": model or self._default_model,
            "state": state,
            "questions": dict(questions),
        }
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            # Guard por corrida: cada POST (reintentos incluidos) reserva 1 POST
            # y exige destino permitido antes de la red; abortar no es reintentable.
            reserve_post_without_tokens(f"{self._base_url}/v1/systemone", guard_required=self.guard_required)
            try:
                if self._client is not None:
                    response = await self._client.post(
                        f"{self._base_url}/v1/systemone",
                        headers=self._headers(),
                        json=payload,
                        timeout=self._timeout,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        response = await client.post(
                            f"{self._base_url}/v1/systemone",
                            headers=self._headers(),
                            json=payload,
                            timeout=self._timeout,
                        )
                text_lower = response.text.lower() if response.status_code >= 400 else ""
                billing_signal = any(
                    word in text_lower
                    for word in (
                        "insufficient credit", "credit exhausted", "billing",
                        "payment required", "insufficient_quota", "quota exceeded",
                    )
                )
                # 402 siempre es facturación; 403 solo con señal explícita de
                # billing del proveedor — un 403 plano es auth/permiso.
                if response.status_code == 402 or billing_signal:
                    raise JevCreditExhausted(f"TypeSafe billing HTTP {response.status_code}")
                if response.status_code in {401, 403}:
                    raise JevAuthError(f"TypeSafe auth HTTP {response.status_code}")
                response.raise_for_status()
                return response.json()
            except (JevCreditExhausted, JevAuthError, LLMGuardAbort):
                raise
            except Exception as exc:  # noqa: BLE001 — reintento best-effort
                last_error = exc
        raise RuntimeError(f"Jev systemone failed after retries: {last_error}")

    async def classify(
        self,
        text: str,
        name: str,
        instructions: str,
        criteria: Mapping[str, str],
        model: str | None = None,
    ) -> JevDecision:
        """Atajo para una pregunta `choice`: devuelve etiqueta + confianza."""
        started = monotonic()
        result = await self.systemone(
            {"message": text},
            {name: {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}},
            model=model,
        )
        latency = monotonic() - started
        answer = (result.get("answers") or {}).get(name) or {}
        probabilities = answer.get("probabilities") or {}
        label = str(answer.get("choice") or "").lower()
        confidence = float(answer.get("confidence") or 0.0)
        if label not in criteria or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Invalid JEV choice/confidence")
        return JevDecision(
            label=label,
            confidence=confidence,
            probabilities=dict(probabilities),
            model=str(result.get("model") or ""),
            latency_s=round(latency, 3),
        )
