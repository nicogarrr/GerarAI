"""Caché corta del cálculo de /api/market/movers con invalidación explícita.

`compute_session_changes(db)` recorre los cierres de todo el universo (~230 ms con
1200 compañías) y Movers lo pedía en cada llamada. El resultado solo cambia
cuando se escriben cierres oficiales (source="yfinance"), y eso pasa por un
único camino: `propicks_price_service.upsert_prices` (sync diario de cierres,
backfill de historia y job F2 de propicks).

- TTL corto (`TTL_SECONDS`): tope de antigüedad aunque falle la invalidación.
- Invalidación explícita: `upsert_prices` marca la sesión con
  `mark_prices_written(db)`; tras el `commit` (nunca antes, para no recachear
  datos viejos entre la invalidación y el commit) se vacía la caché local y se
  sube una versión en Redis (`market_prices:version`).
- Varios procesos: el sync corre en el worker de dramatiq, no en el backend.
  Cada entrada guarda la versión de Redis leída ANTES de calcular; si otro
  proceso la sube, la siguiente petición recalcula. Sin Redis (o caído) la caché
  degrada a TTL puro y Redis no se reintenta durante `_REDIS_BACKOFF_S`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

TTL_SECONDS = 60.0
VERSION_KEY = "market_prices:version"
_SESSION_FLAG = "market_prices_written"
_REDIS_BACKOFF_S = 30.0

_lock = threading.Lock()
_compute_lock = threading.Lock()
_entry: dict[str, Any] | None = None
_generation = 0
_redis_state: dict[str, Any] = {"client": None, "down_until": 0.0}


def _redis():
    """Cliente Redis con timeouts cortos; None sin URL o en backoff tras un fallo."""
    if time.monotonic() < _redis_state["down_until"]:
        return None
    if _redis_state["client"] is not None:
        return _redis_state["client"]
    try:
        import redis as _redis_lib

        from app.core.config import get_settings
        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        client = _redis_lib.from_url(
            url, socket_connect_timeout=0.25, socket_timeout=0.25, retry=no_retry()
        )
    except Exception:
        _redis_down()
        return None
    _redis_state["client"] = client
    return client


def _redis_down() -> None:
    _redis_state["client"] = None
    _redis_state["down_until"] = time.monotonic() + _REDIS_BACKOFF_S


def _read_version() -> str | None:
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(VERSION_KEY)
    except Exception:
        _redis_down()
        return None
    if raw is None:
        return "0"
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def _bump_version() -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.incr(VERSION_KEY)
    except Exception:
        _redis_down()


def invalidate() -> None:
    """Vacía la caché de este proceso y avisa al resto (versión en Redis)."""
    global _entry, _generation
    with _lock:
        _entry = None
        _generation += 1
    _bump_version()


def clear_local() -> None:
    """Solo la caché local (tests)."""
    global _entry
    with _lock:
        _entry = None


def get_or_compute(compute: Callable[[], Any], *, ttl: float = TTL_SECONDS) -> Any:
    """Devuelve el cálculo cacheado si es reciente y nadie escribió cierres desde entonces."""
    global _entry
    version = _read_version()
    now = time.monotonic()
    with _lock:
        entry = _entry
    if entry is not None and now - entry["at"] < ttl and entry["version"] == version:
        return entry["value"]
    # Un solo cálculo a la vez: las peticiones simultáneas tras caducar esperan
    # al primero en vez de lanzar N recorridos completos.
    with _compute_lock:
        with _lock:
            entry = _entry
        if entry is not None and time.monotonic() - entry["at"] < ttl and entry["version"] == version:
            return entry["value"]
        with _lock:
            generation = _generation
        started = time.monotonic()
        value = compute()
        with _lock:
            # Si alguien invalidó mientras se calculaba, no se guarda: el valor
            # podría ser anterior a esa escritura.
            if generation == _generation:
                _entry = {"at": started, "version": version, "value": value}
        return value


def mark_prices_written(db: Session) -> None:
    """Marca la sesión: al hacer commit se invalidará la caché de Movers."""
    db.info[_SESSION_FLAG] = True


@event.listens_for(Session, "after_commit")
def _invalidate_after_commit(session: Session) -> None:
    if session.info.pop(_SESSION_FLAG, False):
        invalidate()


@event.listens_for(Session, "after_rollback")
def _clear_flag_after_rollback(session: Session) -> None:
    session.info.pop(_SESSION_FLAG, None)
