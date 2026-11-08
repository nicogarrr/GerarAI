"""Huecos de cobertura en la ruta de chat (lote 7).

Medicion previa (mismo metodo, tests que referencian el modulo): chat 89 %
(tope de hilos vivos -> respuesta "ocupado", TimeoutError propio del
servicio -> chat_total_deadline, muro duro -> chat_hard_deadline, error del
servicio -> telemetria y propagacion, y la liberacion del hueco cuando el
hilo nunca arranco). Estos tests cubren esas ramas doblando
anyio.to_thread.run_sync: nada de hilos reales.

Que NO se prueba aqui: nada de HTTP ni auth; ningun LLM ni ChatService
real (va doblado via run_from_any_context); NINGUNA concurrencia real: el
tope de hilos se fuerza escribiendo el contador del modulo y el "hilo" se
ejecuta inline en el event loop, asi que esto no prueba el comportamiento
bajo carga ni la carrera entre abandonar y arrancar; y no se usa reloj
real para los plazos: time.monotonic va doblado. La rama de linea 64
("abandonado antes de arrancar" dentro de _work) NO es alcanzable sin
cancelacion real de un hilo y queda deliberadamente sin cubrir.
"""

from __future__ import annotations

import asyncio
import itertools
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api.routes import chat as chat_route
from app.schemas import ChatRequest, ChatResponse


def run_async(coro):
    return asyncio.run(coro)


def _db():
    db = Mock()
    db.info = {"tenant_id": 1}
    return db


def _run_sync_ejecuta_inline(fn, abandon_on_cancel=False):
    """Falso run_sync: ejecuta el 'hilo' inline, sin concurrencia."""

    async def _coro():
        return fn()

    return _coro()


def _run_sync_lanza(exc):
    def _fake(fn, abandon_on_cancel=False):
        async def _coro():
            raise exc

        return _coro()

    return _fake


def _respuesta(texto="ok"):
    return ChatResponse(answer=texto, sources=[], model="m", confidence=0, llm_trace={})


def test_chat_ocupado_cuando_el_tope_de_hilos_esta_lleno(monkeypatch):
    """_live_workers al tope -> respuesta honesta de 'ocupado', sin encolar."""
    monkeypatch.setattr(chat_route, "_live_workers", chat_route.CHAT_MAX_LIVE_WORKERS)
    lanzado = []
    monkeypatch.setattr(
        chat_route.anyio.to_thread,
        "run_sync",
        lambda fn, abandon_on_cancel=False: lanzado.append(fn),
    )
    result = run_async(chat_route.chat(ChatRequest(question="hola que tal"), db=_db()))
    assert result.llm_trace["fallback_reason"] == "chat_busy"
    assert lanzado == []  # no se despacha nada cuando esta lleno


def test_timeout_propio_del_servicio_es_total_deadline(monkeypatch):
    """wait_for salta casi al instante: no es el muro, se re-lanza (linea 111)."""
    # Reloj doblado a cero: la espera medida es 0, siempre por debajo del
    # muro, sin depender del reloj real ni de lo que tarde el event loop.
    monkeypatch.setattr(chat_route.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(chat_route, "record_chat_event", lambda **kw: None)
    monkeypatch.setattr(
        chat_route.anyio.to_thread, "run_sync", _run_sync_lanza(TimeoutError())
    )
    result = run_async(chat_route.chat(ChatRequest(question="hola que tal"), db=_db()))
    assert result.llm_trace["fallback_reason"] == "chat_total_deadline"


def test_muro_duro_es_hard_deadline_sin_reloj_real(monkeypatch):
    """TimeoutError con espera larga (monotonic doblado) -> chat_hard_deadline."""
    # El event loop tambien llama a time.monotonic (loop.time): valores
    # crecientes y enormes para que cualquier diferencia supere el muro.
    pasos = itertools.count()
    monkeypatch.setattr(chat_route.time, "monotonic", lambda: next(pasos) * 10000.0)
    monkeypatch.setattr(
        chat_route,
        "get_settings",
        lambda: SimpleNamespace(chat_total_timeout_seconds=1.0),
    )
    monkeypatch.setattr(chat_route, "record_chat_event", lambda **kw: None)
    monkeypatch.setattr(
        chat_route.anyio.to_thread, "run_sync", _run_sync_lanza(TimeoutError())
    )
    result = run_async(chat_route.chat(ChatRequest(question="hola que tal"), db=_db()))
    assert result.llm_trace["fallback_reason"] == "chat_hard_deadline"


def test_error_del_servicio_registra_y_propaga(monkeypatch):
    """Excepcion del servicio: telemetria con route=error y se propaga."""
    eventos = []
    monkeypatch.setattr(
        chat_route, "record_chat_event", lambda **kw: eventos.append(kw)
    )
    monkeypatch.setattr(
        chat_route.anyio.to_thread, "run_sync", _run_sync_lanza(ValueError("boom"))
    )
    with pytest.raises(ValueError, match="boom"):
        run_async(chat_route.chat(ChatRequest(question="hola que tal"), db=_db()))
    assert eventos[0]["route"] == "error"
    assert "boom" in eventos[0]["error"]


def test_hueco_liberado_si_el_hilo_nunca_arranco(monkeypatch):
    """Tras un fallo antes de arrancar, el contador vuelve a su sitio."""
    monkeypatch.setattr(chat_route, "record_chat_event", lambda **kw: None)
    monkeypatch.setattr(
        chat_route.anyio.to_thread, "run_sync", _run_sync_lanza(ValueError("boom"))
    )
    antes = chat_route._live_workers
    with pytest.raises(ValueError):
        run_async(chat_route.chat(ChatRequest(question="hola que tal"), db=_db()))
    assert chat_route._live_workers == antes


def test_camino_feliz_delega_en_el_servicio(monkeypatch):
    """El hilo ejecuta _work y la respuesta pasa por clasificacion y telemetria."""
    eventos = []
    def _servicio_doblado(coro):
        coro.close()  # la corutina del servicio doblado no se descarta viva
        return _respuesta()

    monkeypatch.setattr(chat_route, "run_from_any_context", _servicio_doblado)
    monkeypatch.setattr(chat_route, "classify_response", lambda r: ("chat", False))
    monkeypatch.setattr(
        chat_route, "record_chat_event", lambda **kw: eventos.append(kw)
    )
    monkeypatch.setattr(
        chat_route.anyio.to_thread, "run_sync", _run_sync_ejecuta_inline
    )
    result = run_async(chat_route.chat(ChatRequest(question="hola que tal"), db=_db()))
    assert result.answer == "ok"
    assert eventos[0]["route"] == "chat"
    assert chat_route._live_workers == 0  # el hueco se libero al terminar
