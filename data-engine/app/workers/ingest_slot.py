"""Semaforo proceso-global para la ingesta pesada de documentos.

5-nov-2026: la avalancha de process_document (677 docs de KRKNF reencolados
cada hora) con 4 hilos en el worker default solapaba descargas + extraccion
Docling + embeddings con fallback a sentence-transformers: worker a 103 % CPU
y 2,27 GiB, host al 95 % y swap casi lleno. Este semaforo acota cuantas
ingestas corren a la vez EN ESTE PROCESO (defecto 1, setting
``document_ingest_max_concurrency``), independientemente de los hilos del
worker. No reordena ni descarta trabajo: el resto espera su turno en el hilo.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class DocumentIngestSlot:
    """BoundedSemaphore con contadores observables (tests sin reloj)."""

    def __init__(self, limit: int):
        if limit < 1:
            raise ValueError("limit debe ser >= 1")
        self.limit = limit
        self._sem = threading.BoundedSemaphore(limit)
        self._lock = threading.Lock()
        self._active = 0
        # Observabilidad determinista: total de adquisiciones y pico de
        # concurrencia real observado (lo usan los tests, sin reloj).
        self.acquired = 0
        self.max_active = 0

    @contextmanager
    def hold(self) -> Iterator[None]:
        self._sem.acquire()
        with self._lock:
            self._active += 1
            self.acquired += 1
            if self._active > self.max_active:
                self.max_active = self._active
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._sem.release()

    def try_hold(self) -> bool:
        """Sonda no bloqueante: hay hueco ahora mismo (uso en tests)."""
        return self._sem.acquire(blocking=False) and (self._sem.release() or True)


_slot: DocumentIngestSlot | None = None
_slot_lock = threading.Lock()


def document_ingest_slot(limit: int | None = None) -> DocumentIngestSlot:
    """Singleton por proceso; se recrea si cambia el limite (tests/config)."""
    global _slot
    if limit is None:
        from app.core.config import get_settings

        limit = get_settings().document_ingest_max_concurrency
    with _slot_lock:
        if _slot is None or _slot.limit != limit:
            _slot = DocumentIngestSlot(limit)
        return _slot


def reset_document_ingest_slot() -> None:
    """Limpia el singleton (aislamiento entre tests)."""
    global _slot
    with _slot_lock:
        _slot = None
