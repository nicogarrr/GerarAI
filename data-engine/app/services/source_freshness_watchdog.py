"""Watchdog de frescura de fuentes: alerta in-app cuando una fuente envejece.

Motivo (medido en prod, 1-nov-2026): las fuentes de precios FMP y
yahoo_intraday llevaban sin escribir desde el 2 y el 7 de octubre y nadie lo
vio hasta una revision manual. El panel de salud de datos
(data_health_service) ya marca cada fuente "stale" por su ultima escritura,
pero es pull: hay que abrirlo para verlo. Este watchdog convierte ese estado
MEDIDO en una ResearchAlert in-app al operador (coste 0).

Reusa el inventario del panel (misma politica de edad por capa: precios 4 d,
noticias 7 d, documentos 30 d, fundamentales 90 d) y su regla de veracidad:
la medida es la ULTIMA ESCRITURA en la base de datos, no la fecha del dato ni
una prueba de que el proveedor este caido; el mensaje lo dice asi.

Dedup DURABLE por episodio (v2, tras la auditoria): cada transicion se
persiste como ResearchAlert (entra en stale / se recupera) y el estado del
episodio se lee de esa historia en cada tick, no solo del dict en memoria del
proceso. Una fuente que SIGUE stale al dia siguiente (o tras un reinicio del
worker) NO genera otra alerta; solo cuando se recupera y vuelve a envejecer
se abre un episodio nuevo. El fingerprint por dia queda como respaldo de
carreras: dentro del mismo dia solo se persiste una transicion de cada tipo.

Una capa con status=error en el inventario NO es un tick sano: la lectura no
pudo medir esa capa, asi que el tick entero es skipped visible
(reason=inventory_layer_error con las capas afectadas), nunca ok.

El inventario real se lee con statement_timeout/lock_timeout propios (por
defecto 20 s, configurables) REAPLICADOS dentro de inventory() tras cada
rollback de capa: SET LOCAL muere con la transaccion y un solo set_config
previo dejaba las capas siguientes sin limite (medido en PG real, 18-nov).
Lectura fallida del inventario = skipped, nunca una falsa alarma.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ResearchAlert
from app.services.in_app_alerts import InAppAlert, persist_in_app_alerts

logger = logging.getLogger(__name__)

VERSION = "source-freshness-v3"
ALERT_TYPE = "source_freshness"

# Ultimo estado visto por (tenant, capa, fuente) EN ESTE PROCESO (misma
# limitacion declarada que source_health_watchdog: el dict solo evita
# realertar dentro del proceso; la dedup durable es el fingerprint por dia).
_last_states: dict[tuple[Any, str, str], str] = {}
_last_states_lock = threading.Lock()


def query_timeout_ms() -> int:
    """Timeout por consulta de la lectura del inventario real, en ms.

    Se pasa a inventory() como statement_timeout_ms, que lo reaplica tras
    cada rollback interno de capa (un rollback descarta el SET LOCAL).
    """
    try:
        return max(1000, int(os.getenv("SOURCE_WATCHDOG_QUERY_TIMEOUT_MS", "20000")))
    except ValueError:
        return 20000


def load_episode_states(db: Session, tenant_id: Any) -> dict[tuple[str, str], str]:
    """Estado durable del episodio por (capa, fuente): stale o recovered.

    Se deriva de la historia de alertas de este watchdog (ordenadas por id):
    la ultima transicion persistida de cada fuente manda. Las filas v1 (sin
    campo ``transition`` en metadata) cuentan como episodio stale abierto,
    asi el despliegue de v2 no realerta episodios ya notificados.
    """
    rows = db.scalars(
        select(ResearchAlert)
        .where(
            ResearchAlert.tenant_id == tenant_id,
            ResearchAlert.alert_type == ALERT_TYPE,
        )
        .order_by(ResearchAlert.id)
    ).all()
    states: dict[tuple[str, str], str] = {}
    for alert in rows:
        md = alert.metadata_ or {}
        layer = md.get("layer")
        if layer is None:
            continue
        transition = md.get("transition") or "stale"  # legado v1 = stale abierto
        states[(layer, md.get("source") or "")] = transition
    return states


def _previous_status(
    row: dict[str, Any],
    *,
    tenant_id: Any = None,
    last_states: dict[tuple[str, str], str] | None = None,
    durable_states: dict[tuple[str, str], str] | None = None,
) -> str | None:
    """Estado previo de la fuente: memoria del proceso y, si no, el episodio
    durable persistido (supera reinicios y cambios de dia)."""
    key = (row.get("layer"), row.get("source") or "")
    previous: str | None = None
    if durable_states:
        previous = durable_states.get(key)
    if last_states is not None:
        previous = last_states.get(key, previous)
    else:
        previous = _last_states.get((tenant_id, key[0], key[1]), previous)
    return previous


def detect_stale(
    sources: list[dict[str, Any]],
    *,
    tenant_id: Any = None,
    last_states: dict[tuple[str, str], str] | None = None,
    durable_states: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Diff puro: fuentes que ACABAN de pasar a stale en este tick.

    Una fuente que SIGUE stale (memoria del proceso o episodio durable
    abierto) no realerta; si se recupero antes (estado recovered), el nuevo
    stale abre un episodio nuevo y si alerta. NO muta estado:
    ``record_states`` lo graba tras el commit.
    """
    stale: list[dict[str, Any]] = []
    for row in sources:
        previous = _previous_status(
            row, tenant_id=tenant_id, last_states=last_states,
            durable_states=durable_states,
        )
        if row.get("status") == "stale" and previous != "stale":
            stale.append({**row, "previous_status": previous})
    return stale


def detect_recoveries(
    sources: list[dict[str, Any]],
    *,
    tenant_id: Any = None,
    last_states: dict[tuple[str, str], str] | None = None,
    durable_states: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Fuentes con episodio stale abierto que vuelven a escribir.

    Cerrar el episodio (transicion recovered persistida) es lo que permite
    que un FUTURO stale de la misma fuente alerte de nuevo.
    """
    recovered: list[dict[str, Any]] = []
    for row in sources:
        previous = _previous_status(
            row, tenant_id=tenant_id, last_states=last_states,
            durable_states=durable_states,
        )
        if previous == "stale" and row.get("status") not in (None, "stale", "error"):
            recovered.append({**row, "previous_status": previous})
    return recovered


def record_states(
    sources: list[dict[str, Any]],
    *,
    tenant_id: Any = None,
    last_states: dict[tuple[str, str], str] | None = None,
) -> None:
    """Graba el estado observado; llamar solo tras un commit exitoso."""
    if last_states is not None:
        for row in sources:
            last_states[(row["layer"], row["source"] or "")] = row["status"]
        return
    with _last_states_lock:
        for row in sources:
            _last_states[(tenant_id, row["layer"], row["source"])] = row["status"]


def _message(row: dict[str, Any]) -> tuple[str, str, str]:
    """(severity, title, message) en español, solo con lo medido por el panel."""
    layer = row["layer"]
    source = row["source"]
    # Precios diarios alimentan cartera, watchlist y DCA: su frescura es la
    # que mas duele cuando falta (FMP/yahoo_intraday, oct-2026).
    severity = "high" if layer == "Precios diarios" else "medium"
    title = f"Fuente envejecida: {source} ({layer})"[:300]
    last_update = row.get("last_update") or "desconocida"
    message = (
        f"La fuente {source} de la capa {layer} no registra escrituras nuevas "
        f"desde {last_update} (limite del panel: {row['max_age_days']} dias). "
        "Es la ultima escritura medida en la base de datos, no la fecha del dato "
        "ni una prueba de que el proveedor este caido. Causa posible: job sin "
        "programar, cuota agotada o cambio del proveedor; lo cierto es solo lo "
        "medido arriba. Estado medido por el inventario de salud de datos (GerarAI)."
    )
    return severity, title, message


def _recovery_message(row: dict[str, Any]) -> tuple[str, str, str]:
    """(severity, title, message) del cierre de episodio; cierra el ciclo."""
    layer = row.get("layer")
    source = row.get("source")
    title = f"Fuente recuperada: {source} ({layer})"[:300]
    last_update = row.get("last_update") or "desconocida"
    message = (
        f"La fuente {source} de la capa {layer} vuelve a registrar escrituras "
        f"(ultima medida: {last_update}). El episodio de fuente envejecida "
        "abierto para esta fuente queda cerrado; si vuelve a envejecer se "
        "notificara como episodio nuevo. Estado medido por el inventario de "
        "salud de datos (GerarAI)."
    )
    return "info", title, message


def emit_source_freshness_alerts(
    db: Session,
    *,
    now: datetime | None = None,
    inventory_provider: Any = None,
    last_states: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    """Persiste las transiciones de episodio (stale/recovered); durable.

    ``inventory_provider`` inyecta el inventario en tests; en prod es
    ``data_health_service.inventory`` sobre la propia sesion, con
    statement/lock timeout propios (la sonda postgres es la ruta barata
    medida; la cache del panel es por proceso y este actor corre en el
    worker de alertas, asi que aqui no aplica).

    Una capa con status=error significa "esa capa no se pudo medir": el tick
    es skipped visible, nunca ok con cero alertas. El estado durable del
    episodio (historia de alertas) evita realertar una fuente que sigue
    stale tras un reinicio o un cambio de dia.
    """
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    real_inventory = inventory_provider is None
    if real_inventory:
        from app.services.data_health_service import inventory

        # El timeout se pasa a inventory(), que lo reaplica tras cada
        # rollback interno de capa (aplicarlo aqui fuera solo protegia la
        # primera transaccion: SET LOCAL muere con ella, medido en PG real).
        timeout_ms = query_timeout_ms()
        inventory_provider = lambda: inventory(db, statement_timeout_ms=timeout_ms)  # noqa: E731
    try:
        started = time.monotonic()
        snapshot = inventory_provider()
        tick_ms = round(1000.0 * (time.monotonic() - started), 1)
    except Exception as exc:  # noqa: BLE001 - lectura fallida = skipped, no alarma
        logger.warning("source_freshness_watchdog: inventario ilegible: %s", exc)
        return {"status": "skipped", "reason": "inventory_unavailable", "stale": 0}

    sources = list(snapshot.get("sources", []))
    error_layers = sorted(
        {str(row.get("layer") or "desconocida") for row in sources if row.get("status") == "error"}
    )
    if error_layers:
        # "No medido" visible: inventario devuelto sin excepcion pero con
        # capas ilegibles; tratarlo como ok seria una falsa sensacion de
        # salud (hallazgo del auditor).
        logger.warning(
            "source_freshness_watchdog: capas no medibles en el inventario: %s",
            ", ".join(error_layers),
        )
        return {
            "status": "skipped",
            "reason": "inventory_layer_error",
            "layers": error_layers,
            "stale": 0,
        }

    durable = load_episode_states(db, tenant_id)
    stale = detect_stale(sources, tenant_id=tenant_id, last_states=last_states,
                         durable_states=durable)
    recovered = detect_recoveries(sources, tenant_id=tenant_id, last_states=last_states,
                                  durable_states=durable)
    prepared: list[InAppAlert] = []
    for row in stale:
        severity, title, message = _message(row)
        prepared.append(
            InAppAlert(
                fingerprint=(
                    f"{VERSION}:{tenant_id}:{row['layer']}:{row['source']}:stale:{now.date().isoformat()}"
                ),
                alert_type=ALERT_TYPE,
                severity=severity,
                title=title,
                message=message,
                metadata={
                    "rule_version": VERSION,
                    "transition": "stale",
                    "layer": row["layer"],
                    "source": row["source"],
                    "last_update": row.get("last_update"),
                    "max_age_days": row.get("max_age_days"),
                    "previous_status": row.get("previous_status"),
                    "measured_at": snapshot.get("as_of"),
                },
            )
        )
    for row in recovered:
        severity, title, message = _recovery_message(row)
        prepared.append(
            InAppAlert(
                fingerprint=(
                    f"{VERSION}:{tenant_id}:{row['layer']}:{row['source']}:recovered:{now.date().isoformat()}"
                ),
                alert_type=ALERT_TYPE,
                severity=severity,
                title=title,
                message=message,
                metadata={
                    "rule_version": VERSION,
                    "transition": "recovered",
                    "layer": row["layer"],
                    "source": row["source"],
                    "last_update": row.get("last_update"),
                    "max_age_days": row.get("max_age_days"),
                    "previous_status": row.get("previous_status"),
                    "measured_at": snapshot.get("as_of"),
                },
            )
        )
    created, existing = persist_in_app_alerts(db, tenant_id=tenant_id, now=now, alerts=prepared)
    # Solo tras el commit: un rollback no consume las transiciones y el
    # siguiente tick las reintenta (el fingerprint las deduplica).
    record_states(sources, tenant_id=tenant_id, last_states=last_states)
    return {
        "status": "ok",
        "created": len(created),
        "existing": existing,
        "stale": len(stale),
        "recovered": len(recovered),
        "tick_ms": tick_ms,
        "alert_ids": created,
    }
