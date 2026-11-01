"""Slow query logging for database performance monitoring.

Logs queries that take longer than the configured threshold (default: 1 second).
Integrates with SQLAlchemy engine events to capture query execution time without
modifying application code.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Default threshold: 1 second
SLOW_QUERY_THRESHOLD_SECONDS = 1.0

_INSTALLED = False


def install(engine: Engine, threshold_s: float = SLOW_QUERY_THRESHOLD_SECONDS) -> None:
    """Install slow query logging on the given SQLAlchemy engine (idempotent).
    
    Args:
        engine: SQLAlchemy engine to monitor
        threshold_s: Queries taking longer than this will be logged (default: 1.0s)
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        conn.info.setdefault("query_start_time", []).append(time.monotonic())

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        query_times = conn.info.get("query_start_time", [])
        if not query_times:
            return
        
        start_time = query_times.pop()
        elapsed = time.monotonic() - start_time
        
        if elapsed >= threshold_s:
            # Redactar la consulta: solo la estructura, sin parámetros que puedan
            # contener datos sensibles. SQLAlchemy ya compila los parámetros por
            # separado, así que 'statement' no los incluye.
            safe_statement = statement.replace("\n", " ").strip()
            if len(safe_statement) > 500:
                safe_statement = safe_statement[:500] + "..."
            
            logger.warning(
                "slow_query: %.3fs | %s",
                elapsed,
                safe_statement,
            )
