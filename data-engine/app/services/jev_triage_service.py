"""Triage barato de noticias con TypeSafe Jev delante del LLM principal.

Si Jev clasifica la noticia como "routine" con confianza alta, se guardinga
la ruta del LLM principal (news_triage barato) y se abre la gate para
degradar profundidad. Nunca decide solo: solo ajusta materiality/reasoning.

Coste: Jev factura ~$0.042 / millón de tokens de entrada (salida gratis).
Fallback: sin TYPESAFE_API_KEY el cliente no se construye y cada
classify_*_sync devuelve None (el llamador sigue sin Jev, sin romper nada).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.async_bridge import run_from_any_context

logger = logging.getLogger("gerarai.jev_triage")

# Umbral de confianza de Jev para degradar a "routine".
ROUTINE_CONFIDENCE_THRESHOLD = 0.85
# Si Jev dice "urgent" con esta confianza, sumamos materialidad.
URGENT_CONFIDENCE_THRESHOLD = 0.80
URGENT_MATERIALITY_BUMP = 1


@dataclass(frozen=True)
class JevTriageResult:
    label: str
    confidence: float
    applied: bool  # True si el resultado influyó en el score
    latency_s: float
    error: str | None = None
    backend: str = "jev"


def build_client():
    """Devuelve JevDecisionClient o None si no hay TYPESAFE_API_KEY."""
    settings = get_settings()
    if not settings.typesafe_api_key:
        return None
    # import diferido para no penalizar arranque sin key
    from app.llm.jev import JevDecisionClient

    client = JevDecisionClient(
        api_key=settings.typesafe_api_key,
        base_url=settings.typesafe_base_url,
        default_model=settings.typesafe_model,
    )
    client.guard_required = bool(settings.llm_run_guard_required)
    return client


CRITERIA = {
    "urgent": (
        "price crash, circuit breaker, bankruptcy, fraud, accounting scandal, "
        "regulatory investigation, downgrade to junk, guidance cut, dilution, "
        "halted trading, urgent investor action needed"
    ),
    "routine": (
        "mild move on a quiet session, routine news, no new facts, opinion piece, "
        "conference appearance without announcements, generic market commentary"
    ),
}

# Coste: ~$0.042/MTok in. Fallback: sin key, build_client() -> None y esto -> None.
DOC_TYPE_CRITERIA = {
    "earnings": "quarterly/annual results, EPS, revenue, guidance, earnings call",
    "filing": "SEC filing, 10-K, 10-Q, 8-K, prospectus, regulatory submission",
    "macro": "central banks, rates, inflation, GDP, employment, market-wide data",
    "opinion": "op-ed, analyst opinion, commentary without new facts or filings",
}


def classify_urgency_sync(text: str) -> JevTriageResult | None:
    """Clasifica urgencia con Jev. Devuelve None si no está configurado o falla."""
    from app.services.jev_availability import credit_status
    if credit_status()["status"] != "activo":
        return None
    client = build_client()
    if client is None:
        return None

    try:
        decision = run_from_any_context(
            client.classify(
                text[:2000],
                name="urgency",
                instructions="How urgent is this market news for an investor?",
                criteria=CRITERIA,
            )
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, nunca rompe ingesta
        from app.llm.jev import JevCreditExhausted
        from app.services.jev_availability import mark_credit_exhausted
        if isinstance(exc, JevCreditExhausted):
            mark_credit_exhausted()
        logger.warning("jev triage failed: %s", exc)
        return JevTriageResult(
            label="", confidence=0.0, applied=False, latency_s=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )
    return JevTriageResult(
        label=decision.label,
        confidence=decision.confidence,
        applied=False,
        latency_s=decision.latency_s,
        backend=getattr(decision, "backend", "jev"),
    )


def classify_doc_type_sync(text: str) -> JevTriageResult | None:
    """Clasifica tipo documental con Jev (1 llamada). None sin key; error suave.

    Coste: ~$0.042/MTok in. Fallback: sin TYPESAFE_API_KEY devuelve None y el
    llamador ingiere sin `jev_doc_type` en metadata (best-effort, nunca rompe).
    """
    from app.services.jev_availability import credit_status
    if credit_status()["status"] != "activo":
        return None
    client = build_client()
    if client is None:
        return None

    try:
        decision = run_from_any_context(
            client.classify(
                text[:2000],
                name="doc_type",
                instructions="What kind of financial document is this?",
                criteria=DOC_TYPE_CRITERIA,
            )
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, nunca rompe ingesta
        from app.llm.jev import JevCreditExhausted
        from app.services.jev_availability import mark_credit_exhausted
        if isinstance(exc, JevCreditExhausted):
            mark_credit_exhausted()
        logger.warning("jev doc-type failed: %s", exc)
        return JevTriageResult(
            label="", confidence=0.0, applied=False, latency_s=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )
    return JevTriageResult(
        label=decision.label,
        confidence=decision.confidence,
        applied=False,
        latency_s=decision.latency_s,
        backend=getattr(decision, "backend", "jev"),
    )


def jev_metadata(triage: JevTriageResult | None) -> dict | None:
    """Serializa un veredicto Jev para metadata (alerta/documento). None sin veredicto."""
    if triage is None or not triage.label:
        return None
    payload: dict = {
        "label": triage.label,
        "confidence": round(triage.confidence, 4),
        "latency_s": triage.latency_s,
        "backend": triage.backend,
    }
    if triage.error:
        payload["error"] = triage.error[:200]
    return payload


def apply_to_materiality(
    materiality: int, reasons: list[str], triage: JevTriageResult
) -> int:
    """Ajusta materialidad en sitio según el veredicto de Jev (sin romper clamps externos)."""
    if triage.label == "urgent" and triage.confidence >= URGENT_CONFIDENCE_THRESHOLD:
        materiality += URGENT_MATERIALITY_BUMP
        reasons.append(
            f"jev_urgent(conf={triage.confidence:.2f}) +{URGENT_MATERIALITY_BUMP}"
        )
    elif triage.label == "routine" and triage.confidence >= ROUTINE_CONFIDENCE_THRESHOLD:
        materiality -= 1
        reasons.append(f"jev_routine(conf={triage.confidence:.2f}) -1")
    return materiality
