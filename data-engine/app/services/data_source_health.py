"""Servicio de monitorización de salud y circuit breaker para fuentes de datos externas.

Fulfills: VAL-DATA-004 (y complementa VAL-DATA-001, VAL-DATA-002, VAL-DATA-003)
Expected Behavior:
- Endpoint de comprobación de salud de fuentes de datos externas
- Patrón Circuit Breaker para fuentes con fallos consecutivos
- Conmutación automática por error (failover) a fuentes secundarias
- Registro y trazabilidad de fallos en fuentes de datos
- Una fuente nunca sondeada se reporta como "unknown", nunca como "healthy"
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"  # Operativo normal
    OPEN = "open"  # Cortocircuitado tras fallos consecutivos (usa fallback)
    HALF_OPEN = "half_open"  # Probando recuperación


@dataclass
class DataSourceStatus:
    name: str
    is_primary: bool
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    last_failure_time: float = 0.0
    # None hasta la primera comprobación real: la fuente nunca se ha sondeado.
    last_checked_at: str | None = None
    fallback_source: str | None = None
    response_time_ms: float = 0.0
    _transition_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record_success(self, elapsed_ms: float = 0.0) -> None:
        with self._transition_lock:
            self.consecutive_failures = 0
            self.state = CircuitState.CLOSED
            self.last_checked_at = datetime.now(UTC).isoformat()
            self.response_time_ms = elapsed_ms

    def record_failure(self, error: str) -> None:
        with self._transition_lock:
            self.consecutive_failures += 1
            self.last_failure_time = time.perf_counter()
            self.last_checked_at = datetime.now(UTC).isoformat()
            if self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker abierto para fuente '%s' tras %d fallos consecutivos. Error: %s",
                    self.name,
                    self.consecutive_failures,
                    error,
                )
            else:
                logger.info(
                    "Fallo registrado en fuente '%s' (%d/%d): %s",
                    self.name,
                    self.consecutive_failures,
                    self.failure_threshold,
                    error,
                )

    def can_attempt(self) -> bool:
        with self._transition_lock:
            if self.state == CircuitState.OPEN:
                if time.perf_counter() - self.last_failure_time > self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    return True
                return False
            return True

    def as_dict(self) -> dict[str, Any]:
        if self.last_checked_at is None:
            # Nunca sondeada: no se afirma salud que no se ha comprobado.
            status = "unknown"
        elif self.state == CircuitState.CLOSED:
            status = "healthy"
        elif self.state == CircuitState.HALF_OPEN:
            status = "degraded"
        else:
            status = "failing"
        return {
            "name": self.name,
            "is_primary": self.is_primary,
            "status": status,
            "circuit_state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "last_checked_at": self.last_checked_at,
            "fallback_source": self.fallback_source,
            "response_time_ms": round(self.response_time_ms, 2),
        }


class DataSourceHealthRegistry:
    """Registro global singleton para la salud de fuentes externas."""

    _instance: DataSourceHealthRegistry | None = None
    _lock = threading.Lock()

    def __new__(cls) -> DataSourceHealthRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_registry()
            return cls._instance

    def _init_registry(self) -> None:
        self.sources: dict[str, DataSourceStatus] = {
            "yahoo_finance": DataSourceStatus(
                name="Yahoo Finance",
                is_primary=True,
                fallback_source="alpha_vantage",
            ),
            "alpha_vantage": DataSourceStatus(
                name="Alpha Vantage",
                is_primary=False,
                fallback_source=None,
            ),
            "ecb": DataSourceStatus(
                name="European Central Bank (ECB)",
                is_primary=True,
                fallback_source="cached_fx",
            ),
            "sec_edgar": DataSourceStatus(
                name="SEC EDGAR",
                is_primary=False,
                fallback_source="hf_snapshot",
            ),
            "esef": DataSourceStatus(
                name="ESEF (filings.xbrl.org)",
                is_primary=False,
                fallback_source="esef_snapshot",
            ),
            "openfigi": DataSourceStatus(
                name="OpenFIGI",
                is_primary=False,
                fallback_source=None,
            ),
            "cnmv": DataSourceStatus(
                name="CNMV",
                is_primary=False,
                fallback_source=None,
            ),
            "qdrant": DataSourceStatus(
                name="Qdrant Vector Database",
                is_primary=True,
                fallback_source="keyword_search",
            ),
            "redis": DataSourceStatus(
                name="Redis Cache",
                is_primary=True,
                fallback_source="in_memory_lru",
            ),
        }

    def get_status(self, source_key: str) -> DataSourceStatus:
        return self.sources.get(
            source_key,
            DataSourceStatus(name=source_key, is_primary=False),
        )

    def record_success(self, source_key: str, elapsed_ms: float = 0.0) -> None:
        if source_key in self.sources:
            self.sources[source_key].record_success(elapsed_ms)

    def record_failure(self, source_key: str, error: str) -> None:
        if source_key in self.sources:
            self.sources[source_key].record_failure(error)

    def should_use_fallback(self, source_key: str) -> tuple[bool, str | None]:
        """Indica si el circuit breaker está abierto y cuál es la fuente de contingencia."""
        status = self.get_status(source_key)
        if not status.can_attempt():
            return True, status.fallback_source
        return False, None

    def summary(self) -> dict[str, Any]:
        all_sources = [s.as_dict() for s in self.sources.values()]
        any_failing = any(s["circuit_state"] == CircuitState.OPEN.value for s in all_sources)
        any_degraded = any(s["circuit_state"] == CircuitState.HALF_OPEN.value for s in all_sources)
        if any_failing or any_degraded:
            overall = "degraded"
        elif all(s["status"] == "unknown" for s in all_sources):
            # Ninguna fuente se ha sondeado aún: no se afirma salud.
            overall = "unknown"
        else:
            overall = "healthy"

        return {
            "overall_status": overall,
            "checked_at": datetime.now(UTC).isoformat(),
            "sources": all_sources,
        }


def get_data_source_registry() -> DataSourceHealthRegistry:
    return DataSourceHealthRegistry()
