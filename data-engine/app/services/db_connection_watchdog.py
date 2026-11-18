"""Watchdog de conexiones Postgres: alerta in-app al operador al degradarse.

Motivo (medido en prod, 15-nov-2026 ~23:58 CET): el backend devolvio 503 con
el pool de conexiones 20+10 agotado y nadie lo vio hasta que lo reporto el
usuario; la recuperacion fue un reinicio manual del backend. El endpoint
db_metrics expone el pool del PROCESO API solo por pull (panel admin) y no
alerta; ``pg_stat_activity`` es visible desde cualquier proceso con sesion,
asi que este watchdog mide el lado servidor en cada tick:

- sesiones "idle in transaction" envejecidas: la edad es la del ESTADO idle
  (``state_change``), no la de la transaccion (``xact_start``): una consulta
  legitima larga que acaba de terminar publica edad idle ~0, no la duracion
  de la consulta; lo contrario dispararia falsas alertas (reproducido por el
  auditor en PG14 real);
- consultas "active" viejas: una consulta colgada retiene su conexion;
- saturacion del servidor: conexiones totales DEL SERVIDOR (todas las bases;
  el techo max_connections es global y otras bases tambien pueden agotarlo)
  >= umbral % de max_connections (el pool por proceso no es visible desde
  fuera; el techo compartido del servidor si).

Las lecturas llevan statement_timeout y lock_timeout acotados (por defecto
10 s, configurables) para que una lectura bloqueada no supere el lease del
actor ni ocupe la cola de alertas.

Veracidad: el mensaje recoge solo lo MEDIDO (conteos, edades, techo); nunca
afirma la causa. Idempotente: una alerta por tenant, condicion y dia
(fingerprint unico; patron source_health_watchdog). Coste ~0: tres lecturas
baratas cada 5 min (un set_config transaccional, un agregado sobre
pg_stat_activity y el catalogo pg_settings). Fuera de Postgres (sqlite en
tests/desarrollo) el tick es skipped, nunca una falsa alarma.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.in_app_alerts import InAppAlert, persist_in_app_alerts

logger = logging.getLogger(__name__)

VERSION = "db-connections-v2"
ALERT_TYPE = "db_connection"

# Sin cache de max_connections: pg_settings es una lectura de catalogo local
# (microsegundos) y el valor puede cambiar con un ALTER SYSTEM + reload.


def idle_tx_threshold_seconds() -> float:
    """Edad de una sesion 'idle in transaction' a partir de la cual se alerta."""
    try:
        return max(30.0, float(os.getenv("DB_WATCHDOG_IDLE_TX_SECONDS", "300")))
    except ValueError:
        return 300.0


def active_query_threshold_seconds() -> float:
    """Edad de una consulta activa a partir de la cual se alerta.

    Por encima del TimeLimit del actor de ingesta mas largo declarado (2 h) lo
    veria el watchdog de colas; este umbral (15 min) apunta a consultas HTTP
    colgadas, que no tienen TimeLimit propio.
    """
    try:
        return max(60.0, float(os.getenv("DB_WATCHDOG_ACTIVE_QUERY_SECONDS", "900")))
    except ValueError:
        return 900.0


def saturation_pct_threshold() -> float:
    """Porcentaje de max_connections a partir del cual se alerta."""
    try:
        value = float(os.getenv("DB_WATCHDOG_SATURATION_PCT", "80"))
    except ValueError:
        return 80.0
    return min(100.0, max(1.0, value))


def query_timeout_ms() -> int:
    """Timeout de las lecturas del watchdog (statement y lock), en ms.

    Sin el, una lectura bloqueada (locks sobre catalogo, servidor saturado)
    podria exceder el lease de 120 s del actor y ocupar la cola de alertas.
    """
    try:
        return max(1000, int(os.getenv("DB_WATCHDOG_QUERY_TIMEOUT_MS", "10000")))
    except ValueError:
        return 10000


def sample_connections(db: Session) -> dict[str, Any] | None:
    """Una medicion agregada de pg_stat_activity; None fuera de Postgres.

    Alcance: TODO el servidor. El techo max_connections es global y otras
    bases del mismo servidor tambien lo agotan, asi que contar solo la base
    actual ocultaria la saturacion (reproducido por el auditor). Las edades
    miden: consulta activa mas vieja por ``query_start`` y sesion 'idle in
    transaction' mas vieja por ``state_change`` (edad EN ESTADO idle, no
    edad de la transaccion: una consulta larga que acaba de terminar no es
    una sesion idle vieja).

    Antes de leer fija statement_timeout y lock_timeout locales a la
    transaccion (set_config(..., is_local=true), parametrizado), para que
    una lectura bloqueada no supere el lease del actor.

    Se excluye la propia sesion del watchdog (su SELECT apareceria como
    'active'). Sin acceso a pg_stat_activity (permisos) el tick es skipped:
    un error de lectura nunca se convierte en alerta inventada.
    """
    if db.get_bind().dialect.name != "postgresql":
        return None
    timeout_ms = str(query_timeout_ms())
    try:
        # Timeout local a la transaccion (is_local=true): no toca la sesion
        # compartida y muere con la transaccion del tick.
        db.execute(
            text(
                "SELECT set_config('statement_timeout', :ms, true), "
                "set_config('lock_timeout', :ms, true)"
            ),
            {"ms": timeout_ms},
        )
        row = db.execute(
            text(
                """
                SELECT
                  count(*) FILTER (WHERE state = 'active') AS active,
                  count(*) FILTER (WHERE state = 'idle') AS idle,
                  count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx,
                  count(*) AS total,
                  COALESCE(max(EXTRACT(EPOCH FROM (now() - query_start)))
                           FILTER (WHERE state = 'active'), 0) AS oldest_active_s,
                  COALESCE(max(EXTRACT(EPOCH FROM (now() - state_change)))
                           FILTER (WHERE state = 'idle in transaction'), 0) AS oldest_idle_tx_s
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                """
            )
        ).one()
        max_conn = db.execute(
            text("SELECT setting::int FROM pg_settings WHERE name = 'max_connections'")
        ).scalar_one()
    except Exception as exc:  # noqa: BLE001 - permisos o conexion: skipped, no alarma
        logger.warning("db_connection_watchdog: lectura de pg_stat_activity fallida: %s", exc)
        return None
    return {
        "active": int(row.active),
        "idle": int(row.idle),
        "idle_in_tx": int(row.idle_in_tx),
        "total": int(row.total),
        "oldest_active_s": float(row.oldest_active_s),
        "oldest_idle_tx_s": float(row.oldest_idle_tx_s),
        "max_connections": int(max_conn),
    }


def detect_issues(
    sample: dict[str, Any],
    *,
    idle_tx_s: float | None = None,
    active_s: float | None = None,
    saturation_pct: float | None = None,
) -> list[dict[str, Any]]:
    """Diff puro sobre la muestra: condiciones medidas que superan su umbral.

    NO muta estado y no lee reloj ni entorno: mismos datos, mismas issues.
    """
    idle_tx_s = idle_tx_threshold_seconds() if idle_tx_s is None else idle_tx_s
    active_s = active_query_threshold_seconds() if active_s is None else active_s
    saturation_pct = saturation_pct_threshold() if saturation_pct is None else saturation_pct
    issues: list[dict[str, Any]] = []
    if sample["idle_in_tx"] > 0 and sample["oldest_idle_tx_s"] >= idle_tx_s:
        issues.append(
            {
                "kind": "idle_in_transaction",
                "severity": "medium",
                "count": sample["idle_in_tx"],
                "oldest_s": sample["oldest_idle_tx_s"],
                "threshold_s": idle_tx_s,
            }
        )
    if sample["active"] > 0 and sample["oldest_active_s"] >= active_s:
        issues.append(
            {
                "kind": "active_query",
                "severity": "medium",
                "count": sample["active"],
                "oldest_s": sample["oldest_active_s"],
                "threshold_s": active_s,
            }
        )
    max_conn = sample["max_connections"]
    if max_conn > 0:
        pct = 100.0 * sample["total"] / max_conn
        if pct >= saturation_pct:
            issues.append(
                {
                    "kind": "saturation",
                    "severity": "high",
                    "total": sample["total"],
                    "max_connections": max_conn,
                    "pct": round(pct, 1),
                    "threshold_pct": saturation_pct,
                }
            )
    return issues


def _message(issue: dict[str, Any]) -> tuple[str, str, str]:
    """(severity, title, message) en español, solo con lo medido en el tick."""
    kind = issue["kind"]
    if kind == "idle_in_transaction":
        title = "Sesiones 'idle in transaction' envejecidas"[:300]
        message = (
            f"{issue['count']} sesiones estan 'idle in transaction' y la mas vieja "
            f"lleva {issue['oldest_s']:.0f} s en ese estado (umbral "
            f"{issue['threshold_s']:.0f} s; edad medida por state_change, no por el "
            "inicio de la transaccion). "
            "Una transaccion abierta sin trabajar retiene su conexion del pool y sus "
            "locks. Causa posible: una sesion sin commit/rollback o un proceso colgado; "
            "lo cierto es solo lo medido arriba. Estado medido en pg_stat_activity "
            "por el watchdog de conexiones (GerarAI)."
        )
    elif kind == "active_query":
        title = "Consultas activas envejecidas"[:300]
        message = (
            f"{issue['count']} consultas activas y la mas vieja lleva "
            f"{issue['oldest_s']:.0f} s (umbral {issue['threshold_s']:.0f} s). "
            "Una consulta colgada retiene su conexion del pool. Causa posible: un "
            "plan de consulta degenerado o un proveedor externo esperado dentro de la "
            "transaccion; lo cierto es solo lo medido arriba. Estado medido en "
            "pg_stat_activity por el watchdog de conexiones (GerarAI)."
        )
    else:
        title = "Conexiones de Postgres cerca del techo"[:300]
        message = (
            f"{issue['total']}/{issue['max_connections']} conexiones del servidor "
            "(todas las bases) en uso "
            f"({issue['pct']}%, umbral {issue['threshold_pct']:.0f}%). Por encima, Postgres "
            "rechaza conexiones nuevas y el backend devuelve errores. Causa posible: "
            "fuga de conexiones o pico de procesos; lo cierto es solo lo medido arriba. "
            "Estado medido en pg_stat_activity por el watchdog de conexiones (GerarAI)."
        )
    return issue["severity"], title, message


def emit_db_connection_alerts(
    db: Session,
    *,
    now: datetime | None = None,
    sampler: Any = None,
) -> dict[str, Any]:
    """Persiste una alerta in-app por condicion medida; idempotente por dia.

    ``sampler`` inyecta la muestra en tests; en prod es ``sample_connections``
    sobre la propia sesion. Muestra ilegible o no-Postgres = skipped (fail-open,
    como queue_watchdog con Redis caido).
    """
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    sample = sampler() if sampler is not None else sample_connections(db)
    if sample is None:
        return {"status": "skipped", "reason": "sample_unavailable", "issues": 0}

    issues = detect_issues(sample)
    prepared: list[InAppAlert] = []
    for issue in issues:
        severity, title, message = _message(issue)
        prepared.append(
            InAppAlert(
                fingerprint=(
                    f"{VERSION}:{tenant_id}:{issue['kind']}:{now.date().isoformat()}"
                ),
                alert_type=ALERT_TYPE,
                severity=severity,
                title=title,
                message=message,
                metadata={
                    "rule_version": VERSION,
                    "kind": issue["kind"],
                    "sample": sample,
                    "measured_at": now.isoformat(),
                },
            )
        )
    created, existing = persist_in_app_alerts(db, tenant_id=tenant_id, now=now, alerts=prepared)
    return {
        "status": "ok",
        "created": len(created),
        "existing": existing,
        "issues": len(issues),
        "alert_ids": created,
    }
