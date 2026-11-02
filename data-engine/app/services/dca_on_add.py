"""DCA al añadir: encola la evaluación de los símbolos que el usuario acaba de
seguir (watchlist o cartera) para que la ficha no espere al barrido diario.

Reutiliza la cola ``dca-manual`` y su worker (1 proceso, 1 hilo: una descarga
de Yahoo a la vez) y el mismo lease por tenant que el barrido diario y el
botón manual, así que nunca corre en paralelo con ellos. No cambia cadencias
ni ritmos. Una marca Redis por (tenant, símbolo) evita encolar dos veces el
mismo ticker y deja a la ficha decir «preparando…» mientras tanto. La primera
evaluación de un símbolo nunca avisa (``should_alert``), así que añadir no
dispara alertas. Nada de esto rompe el alta: los fallos se registran.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import tenant_filters
from app.models import DcaSignalState

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  # mismo tope por mensaje que el refresco manual
MARK_TTL_SECONDS = 20 * 60
FRESH_FOR = timedelta(hours=24)


def mark_key(tenant_id: Any, symbol: str) -> str:
    return f"cavaai:dca-on-add:{tenant_id}:{symbol.strip().upper()}"


def redis_client():
    import redis

    from app.core.redis_retry import no_retry

    return redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=1, socket_timeout=2, retry=no_retry()
    )


def due_symbols(
    db: Session, symbols: Iterable[str], *, now: datetime | None = None, only_new: bool = False
) -> list[str]:
    """Símbolos seguidos por el tenant de la sesión cuya señal falta o está vieja.

    ``only_new``: solo los que nunca se han evaluado (importaciones y
    sincronizaciones: lo ya evaluado lo refresca el barrido diario).
    """
    from app.services.dca_signal_engine import DEFAULT_PARAMS
    from app.services.dca_signal_service import tracked_symbols

    now = now or datetime.now(UTC)
    wanted = sorted({(s or "").strip().upper() for s in symbols} - {""})
    if not wanted:
        return []
    tracked = tracked_symbols(db)
    wanted = [s for s in wanted if s in tracked]
    if not wanted:
        return []
    states = {
        row.symbol.upper(): row
        for row in db.scalars(
            select(DcaSignalState).where(
                DcaSignalState.symbol.in_(wanted), *tenant_filters(db, DcaSignalState)
            )
        )
    }
    due = []
    for symbol in wanted:
        state = states.get(symbol)
        evaluated = state.evaluated_at if state is not None else None
        if evaluated is not None and evaluated.tzinfo is None:
            evaluated = evaluated.replace(tzinfo=UTC)
        if only_new:
            if state is None:
                due.append(symbol)
            continue
        if (
            state is None
            or evaluated is None
            or state.params_version != DEFAULT_PARAMS.version
            or now - evaluated >= FRESH_FOR
        ):
            due.append(symbol)
    return due


def _default_sender(tenant_id: int, user_id: str, symbols: list[str]) -> None:
    from app.workers.dramatiq_app import evaluate_dca_on_add

    evaluate_dca_on_add.send(tenant_id, user_id, symbols)


def enqueue_dca_on_add(
    db: Session,
    symbols: Iterable[str],
    *,
    client: Any = None,
    sender: Callable[[int, str, list[str]], None] | None = None,
    only_new: bool = False,
) -> int:
    """Encola la evaluación DCA de los símbolos recién seguidos. Nunca lanza.

    Devuelve cuántos mensajes se encolaron (lotes de ``BATCH_SIZE``).
    """
    try:
        return _enqueue(db, list(symbols), client=client, sender=sender or _default_sender, only_new=only_new)
    except Exception:  # noqa: BLE001 - el alta de watchlist/cartera manda
        logger.warning("dca on-add: no se pudo encolar %s", list(symbols)[:BATCH_SIZE], exc_info=True)
        return 0


def _enqueue(db: Session, symbols: list[str], *, client: Any, sender: Callable, only_new: bool = False) -> int:
    tenant_id = db.info.get("tenant_id")
    user_id = db.info.get("user_id")
    if tenant_id is None or not user_id or not get_settings().dca_evaluation_enabled:
        return 0
    due = due_symbols(db, symbols, only_new=only_new)
    if not due:
        return 0
    own_client = client is None
    client = client or redis_client()
    sent = 0
    try:
        claimed = [s for s in due if client.set(mark_key(tenant_id, s), "queued", nx=True, ex=MARK_TTL_SECONDS)]
        for start in range(0, len(claimed), BATCH_SIZE):
            batch = claimed[start:start + BATCH_SIZE]
            try:
                sender(int(tenant_id), str(user_id), batch)
                sent += 1
            except Exception:  # noqa: BLE001 - sin cola: se libera la marca, el diario lo cubre
                logger.warning("dca on-add: fallo al encolar %s", batch, exc_info=True)
                for symbol in batch:
                    client.delete(mark_key(tenant_id, symbol))
    finally:
        if own_client:
            client.close()
    return sent


def enqueue_dca_for_new_tracked(db: Session) -> int:
    """Tras una importación o sincronización: encola la señal de lo que el
    usuario sigue y nunca se ha evaluado (lo ya evaluado no se repite). Nunca lanza."""
    try:
        from app.services.dca_signal_service import tracked_symbols

        symbols = list(tracked_symbols(db))
    except Exception:  # noqa: BLE001 - la importación ya está confirmada
        logger.warning("dca on-add: no se pudieron leer los símbolos seguidos", exc_info=True)
        db.rollback()
        return 0
    return enqueue_dca_on_add(db, symbols, only_new=True)


def is_preparing(db: Session, symbol: str, *, client: Any = None) -> bool:
    """¿Hay una evaluación al añadir en cola o en curso para este símbolo?"""
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        return False
    own_client = client is None
    try:
        client = client or redis_client()
        return bool(client.exists(mark_key(tenant_id, symbol)))
    except Exception:  # noqa: BLE001 - sin Redis la ficha dice lo de siempre
        return False
    finally:
        if own_client and client is not None:
            client.close()


def run_on_add(db: Session, symbols: list[str], *, client: Any = None) -> dict[str, Any]:
    """Cuerpo del actor (con el lease ya tomado): evalúa solo lo que siga debido."""
    from app.services.dca_signal_service import evaluate_watchlist

    tenant_id = db.info.get("tenant_id")
    requested = [str(s).strip().upper() for s in symbols][:BATCH_SIZE]
    own_client = client is None
    try:
        due = due_symbols(db, requested)
        if not due:
            return {"status": "skipped", "reason": "al_dia", "requested": requested}
        summary = evaluate_watchlist(db, symbols=set(due))
        db.commit()
        return {"status": "ok", "requested": requested, **summary}
    finally:
        try:
            client = client or redis_client()
            for symbol in requested:
                client.delete(mark_key(tenant_id, symbol))
        except Exception:  # noqa: BLE001 - la marca caduca sola
            logger.warning("dca on-add: no se pudieron borrar las marcas", exc_info=True)
        finally:
            if own_client and client is not None:
                client.close()
