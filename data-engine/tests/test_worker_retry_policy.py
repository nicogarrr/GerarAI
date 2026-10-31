"""Contrato de la taxonomia de colas y la politica de reintentos (orden 31 oct).

Cubre:
- todo actor declarado esta clasificado (interactiva/ingesta/calculo/
  mantenimiento) y la clasificacion no sobra;
- ingesta reintenta con backoff: 3 intentos totales -> dead-letter (XQ del
  broker Redis) tras 3 fallos;
- las importaciones aceptadas tienen time_limit generoso y explicito: el
  default implicito de Dramatiq (10 min) las mataba a mitad;
- ningun actor usa max_age: un mensaje encolado no expira esperando worker;
- el broker tiene dead-letter activo (dead_message_ttl > 0).
"""

from __future__ import annotations

import dramatiq
import pytest

from app.workers import dramatiq_app as _dramatiq_actors  # noqa: F401 - registra actores
from app.workers import knowledge_rag_actors as _knowledge_actors  # noqa: F401
from app.workers.queue_taxonomy import (
    ACTOR_CLASS,
    IMPORT_ACTORS,
    INGESTA,
    INGESTA_MAX_RETRIES,
)


@pytest.fixture(scope="module")
def registry():
    broker = dramatiq.get_broker()
    return {name: broker.get_actor(name) for name in broker.get_declared_actors()}


def test_every_actor_is_classified(registry) -> None:
    missing = set(registry) - set(ACTOR_CLASS)
    extra = set(ACTOR_CLASS) - set(registry)
    assert not missing, f"actores sin clasificar: {sorted(missing)}"
    assert not extra, f"clasificados pero no declarados: {sorted(extra)}"


def test_ingesta_retries_with_backoff_then_dead_letter(registry) -> None:
    """Ingesta: >= 3 intentos totales con backoff -> DL tras 3 fallos."""
    offenders = []
    for name, cls in ACTOR_CLASS.items():
        if cls != INGESTA:
            continue
        actor = registry[name]
        retries = actor.options.get("max_retries")
        backoff = actor.options.get("min_backoff")
        if retries is None or retries < INGESTA_MAX_RETRIES or not backoff:
            offenders.append((name, retries, backoff))
    assert not offenders, f"ingesta sin politica 3-fallos+backoff: {offenders}"


def test_accepted_imports_have_generous_time_limit(registry) -> None:
    for name, minimum in IMPORT_ACTORS.items():
        limit = registry[name].options.get("time_limit")
        assert limit is not None and limit >= minimum, (
            f"{name}: time_limit={limit} < {minimum} (el default de 10 min "
            "mataba importaciones aceptadas a mitad)"
        )


def test_no_actor_expires_queued_messages(registry) -> None:
    """Una importacion aceptada no puede caducar esperando worker (max_age)."""
    offenders = [name for name, actor in registry.items() if actor.options.get("max_age")]
    assert not offenders, f"actores con max_age (caducidad en cola): {offenders}"


def test_broker_dead_letter_is_enabled(registry) -> None:
    broker = dramatiq.get_broker()
    # RedisBroker mueve a <cola>.XQ (zset; .DQ es la cola DELAYED, no la DL)
    # lo que agota reintentos y lo conserva dead_message_ttl ms (7 dias por
    # defecto). Sin DL, un job fallido se perdia en silencio.
    
    ttl = broker.dead_message_ttl
    assert ttl and ttl > 0
