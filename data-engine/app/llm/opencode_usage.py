"""Cuota de OpenCode: consulta real de Go (endpoint /usage) y Retry-After.

Medido el 2026-11-01 con la clave Go de GerarAI:

- ``GET {base}/usage`` (p. ej. ``https://opencode.ai/zen/go/v1/usage``)
  responde 200 con ``{"usage": {"rolling": {...}, "weekly": {"status":
  "rate-limited", "percent": 100, "resetsAt": "<ISO-UTC>"}, "monthly":
  {...}}}``. Es dato REAL del proveedor (no estimado).
- La capa free de Zen (``/zen/v1``) NO expone ``/usage`` (404): su consumo
  solo puede estimarse con los contadores propios (BudgetUsage) y el estado
  del breaker de cuota.

Ambos comportamientos son observados, no supuestos; si OpenCode cambia la API
la consulta degrada a ``None`` y el panel marca el dato como no disponible,
nunca inventa cifras.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

#: Tope de espera derivada de un Retry-After: un proveedor pidiendo mas de
#: 24 h equivale a "no vuelvas hoy"; se respeta como mucho 24 h.
MAX_RETRY_AFTER_SECONDS = 24 * 3600.0


def parse_retry_after(value: str | None) -> float | None:
    """Segundos de espera de un ``Retry-After`` (segundos o fecha HTTP).

    Devuelve None si la cabecera falta, es ilegible o ya paso; el llamador
    aplica entonces su cooldown por defecto. Siempre acotado por
    MAX_RETRY_AFTER_SECONDS.
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        seconds = -1.0
    if seconds >= 0:
        return min(seconds, MAX_RETRY_AFTER_SECONDS)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    seconds = (moment - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


async def fetch_go_usage(
    base_url: str,
    api_key: str,
    *,
    session: str | None = None,
    timeout: float = 5.0,
) -> dict | None:
    """GET ``{base_url}/usage`` con la clave Go de la plataforma.

    Devuelve el JSON del proveedor en exito; None ante cualquier fallo
    (transporte, estado no-200, cuerpo ilegible). Nunca lanza: el panel de
    uso no puede romper Ajustes porque OpenCode no responda.
    """
    key = (api_key or "").strip()
    base = (base_url or "").strip().rstrip("/")
    # Only this provider origin may receive the platform credential.
    # No redirects are followed (httpx default). Tenant/custom URLs never enter.
    if base != "https://opencode.ai/zen/go/v1":
        return None
    if not key or not base:
        return None
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "GerarAI-usage/1.0"}
    if session:
        headers["x-opencode-session"] = session
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base}/usage", headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("opencode usage: fallo de transporte (%s)", type(exc).__name__)
        return None
    if response.status_code != 200:
        logger.warning("opencode usage: HTTP %s", response.status_code)
        return None
    try:
        data = response.json()
    except ValueError:
        logger.warning("opencode usage: cuerpo no JSON")
        return None
    return data if isinstance(data, dict) else None
