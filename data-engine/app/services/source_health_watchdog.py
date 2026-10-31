"""Watchdog de fuentes de datos externas: alerta in-app al operador al degradarse.

Fulfills: VAL-DATA-004
Expected Behavior:
- Cuando una fuente pasa a "degraded" (half_open) o "failing" (circuito abierto),
  el operador recibe una ResearchAlert in-app (coste 0) con la causa registrada
- Idempotente: una alerta por fuente, estado y día (fingerprint único)
- Nunca inventa: el mensaje solo recoge lo que el registry MIDIO (estado del
  circuito, fallos consecutivos, última comprobación); si la fuente nunca se
  ha sondeado ("unknown") no se alerta nada

Limitación declarada (MEDIDO): el registry es por proceso. El watchdog corre en
el worker de alertas y ve las transiciones registradas EN ese proceso; la
agregación entre procesos requiere un backend compartido en
data_source_health.py (fuera del alcance de este módulo).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ResearchAlert

VERSION = "source-health-v1"
ALERT_TYPE = "source_health"
ALERT_STATES = {"degraded", "failing"}

# Último estado visto por (tenant, fuente) EN ESTE PROCESO. La dedup durable la
# garantiza el fingerprint único en research_alerts: el dict en memoria solo
# evita realertar dentro del mismo día. Se clavea por tenant para que el primer
# tenant sondeado no se "coma" la transición de los demás, y solo se actualiza
# DESPUÉS de un commit exitoso: un rollback no consume la transición y el
# siguiente ciclo reintenta (la dedup por fingerprint evita duplicados).
_last_states: dict[tuple[Any, str], str] = {}
_last_states_lock = threading.Lock()


def _collect_sources(registry: Any) -> list[dict[str, Any]]:
    """Estado actual por fuente, con su clave de registry (el summary no la da)."""
    return [{"key": key, **status.as_dict()} for key, status in registry.sources.items()]


def detect_transitions(
    sources: list[dict[str, Any]],
    *,
    tenant_id: Any = None,
    last_states: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Diff puro: fuentes que ACABAN de entrar en degraded/failing.

    NO muta estado: ``record_states`` lo graba tras el commit. Una fuente que
    sigue degradada no realerta; si se recupera y vuelve a caer otro día, la
    dedup por fingerprint (fuente, estado, día) permite la nueva alerta.
    """
    transitions: list[dict[str, Any]] = []
    for source in sources:
        key = source["key"]
        status = source["status"]
        if last_states is not None:
            previous = last_states.get(key)
        else:
            previous = _last_states.get((tenant_id, key))
        if status in ALERT_STATES and previous != status:
            transitions.append({**source, "previous_status": previous})
    return transitions


def record_states(
    sources: list[dict[str, Any]],
    *,
    tenant_id: Any = None,
    last_states: dict[str, str] | None = None,
) -> None:
    """Graba el estado observado; llamar solo tras un commit exitoso."""
    if last_states is not None:
        for source in sources:
            last_states[source["key"]] = source["status"]
        return
    with _last_states_lock:
        for source in sources:
            _last_states[(tenant_id, source["key"])] = source["status"]


def _message(source: dict[str, Any]) -> tuple[str, str, str]:
    """(severity, title, message) en español, solo con lo medido por el registry."""
    name = source["name"]
    failing = source["status"] == "failing"
    severity = "high" if failing else "medium"
    title = f"Fuente {'caída' if failing else 'degradada'}: {name}"[:300]
    parts = [
        f"{name} ha pasado a estado '{source['status']}' (circuito {source['circuit_state']}) "
        f"con {source['consecutive_failures']} fallos consecutivos.",
    ]
    if source.get("last_checked_at"):
        parts.append(f"Última comprobación: {source['last_checked_at']} (UTC).")
    if source.get("fallback_source"):
        # VERACIDAD por fuente: el registry distingue respaldo EJECUTADO por
        # codigo (fallback_automatic=True: SEC->mirror HF, ESEF->snapshot,
        # Qdrant->lexical, Damodaran->settings) de respaldo solo DECLARADO
        # (yahoo->AV sin consumidores, ecb->cached_fx inexistente,
        # redis->in_memory_lru sin LRU: cached es fail-open).
        if source.get("fallback_automatic"):
            parts.append(f"Fuente de respaldo automática: {source['fallback_source']}.")
        else:
            parts.append(
                f"Fuente de respaldo prevista: {source['fallback_source']} "
                "(declarada en el registry, sin degradación automática cableada: "
                "la conmutación es manual hoy)."
            )
    parts.append(
        "Causa posible: CAPTCHA, cambio de formato del proveedor, límite de cuota "
        "o bloqueo de IP; la causa registrada está en los logs del worker. "
        "Estado medido por el circuit breaker de fuentes de datos (GerarAI)."
    )
    return severity, title, " ".join(parts)


def emit_source_health_alerts(
    db: Session,
    *,
    registry: Any = None,
    now: datetime | None = None,
    last_states: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Persiste una alerta in-app por transición a degradada/caída; idempotente."""
    if registry is None:
        from app.services.data_source_health import get_data_source_registry

        registry = get_data_source_registry()
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    now = (now or datetime.now(UTC)).astimezone(UTC)

    sources = _collect_sources(registry)
    transitions = detect_transitions(sources, tenant_id=tenant_id, last_states=last_states)
    created: list[int] = []
    existing = 0
    for source in transitions:
        fingerprint = f"{VERSION}:{tenant_id}:{source['key']}:{source['status']}:{now.date().isoformat()}"
        if (
            db.scalar(
                select(ResearchAlert.id).where(
                    ResearchAlert.tenant_id == tenant_id,
                    ResearchAlert.fingerprint == fingerprint,
                )
            )
            is not None
        ):
            existing += 1
            continue
        severity, title, message = _message(source)
        alert = ResearchAlert(
            tenant_id=tenant_id,
            company_id=None,
            severity=severity,
            status="open",
            alert_type=ALERT_TYPE,
            title=title,
            message=message,
            fingerprint=fingerprint,
            channels=["in_app"],
            last_triggered_at=now,
            metadata_={
                "rule_version": VERSION,
                "source_key": source["key"],
                "source_status": source["status"],
                "circuit_state": source["circuit_state"],
                "consecutive_failures": source["consecutive_failures"],
                "fallback_source": source.get("fallback_source"),
                "measured_at": source.get("last_checked_at"),
            },
        )
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
        except IntegrityError:
            existing += 1
            continue
        created.append(alert.id)
    db.commit()
    # Solo tras el commit: un rollback no consume las transiciones y el
    # siguiente ciclo las reintenta (el fingerprint las deduplica).
    record_states(sources, tenant_id=tenant_id, last_states=last_states)
    return {
        "created": len(created),
        "existing": existing,
        "transitions": len(transitions),
        "alert_ids": created,
    }
