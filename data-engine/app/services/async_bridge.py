"""Ejecuta una corrutina desde contexto sync o desde un event loop en marcha.

`asyncio.run()` lanza `RuntimeError: asyncio.run() cannot be called from a
running event loop` cuando ya hay un loop activo en el hilo. Todos los
`except Exception` de los callers se lo comian, asi que la funcion Jev
(urgencia, tipo documental, gates de noticias) no se ejecutaba nunca desde
ninguna ruta async -ingesta de documentos, ingesta de noticias, workers- y
ademas grababa el RuntimeError en los metadatos que se persisten.

Aqui no se puede hacer otra cosa que ejecutar la corrutina en un hilo propio
con su propio loop: la firma es sync (los callers son sync y hay muchos) y
bloquear el loop en curso seria peor que el bug original.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

_BRIDGE = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gerarai-jev-bridge")
_BRIDGE_LOCAL = threading.local()
# Espera maxima cuando el llamador esta en el hilo de un loop activo: sin tope,
# un proveedor colgado dejaria el loop entero bloqueado para siempre.
LOOP_WAIT_TIMEOUT_SECONDS = 120.0


def _run_in_bridge(coro: Coroutine[Any, Any, T]) -> T:
    _BRIDGE_LOCAL.active = True
    try:
        return asyncio.run(coro)
    finally:
        _BRIDGE_LOCAL.active = False


def run_from_any_context(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """Ejecuta ``coro`` tanto en codigo sync como desde un hilo con loop activo.

    Sin loop en marcha es un ``asyncio.run`` normal. Con loop activo en el hilo
    NO hay forma sync de esperar una corrutina sin bloquear ese hilo: la
    corrutina corre en un hilo del pool con su propio loop y el llamador espera
    con un tope duro. Las rutas async deben evitar este camino llamando al
    servicio sync via ``run_in_threadpool``/``asyncio.to_thread`` (ver
    knowledge.upload_document e sources.ingest_document_file).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No hay loop en este hilo: es el caso sync normal.
        return asyncio.run(coro)

    if getattr(_BRIDGE_LOCAL, "active", False):
        # Reentrada desde un hilo puente: otro submit consumiria un segundo
        # worker mientras el primero espera; con 4 llamadas encadenadas el
        # pool se agota y hay deadlock. Falla en voz alta en su lugar.
        coro.close()
        raise RuntimeError(
            "run_from_any_context no puede anidarse desde un hilo puente: "
            "usa 'await' dentro de la cadena async o run_in_threadpool"
        )
    # Propaga contextvars (p.ej. el guard LLM por corrida) al hilo puente.
    future = _BRIDGE.submit(contextvars.copy_context().run, _run_in_bridge, coro)
    return future.result(
        timeout=timeout if timeout is not None else LOOP_WAIT_TIMEOUT_SECONDS
    )
