"""Contrato de fallo rapido de app/core/redis_retry.py.

El modulo fija por contrato 0 reintentos en los clientes Redis del servicio
(rate limit, replay, cache, sondas, leases, cuota LLM): si redis-py cambia
el defecto en una version futura, estos clientes NO pueden empezar a
reintentar con backoff porque el llamador degrada sobre fallo rapido.
El guard estatico (test_redis_no_retry_guard.py) exige el ``retry=no_retry()``
en cada ``from_url``; aqui se prueba el comportamiento del objeto devuelto.
"""
from __future__ import annotations

import redis
import redis.asyncio as redis_async
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.redis_retry import no_retry, no_retry_async


def test_no_retry_es_retry_de_cero_intentos() -> None:
    retry = no_retry()
    assert isinstance(retry, Retry)
    assert retry.get_retries() == 0
    assert isinstance(retry._backoff, NoBackoff)


def test_no_retry_no_reintenta_un_fallo_de_conexion() -> None:
    """0 reintentos = una sola llamada a ``do`` y la excepcion propaga."""
    retry = no_retry()
    llamadas = 0

    def falla() -> None:
        nonlocal llamadas
        llamadas += 1
        raise redis.ConnectionError("caido")

    import pytest

    with pytest.raises(redis.ConnectionError):
        retry.call_with_retry(falla, lambda exc: None)
    assert llamadas == 1


def test_no_retry_async_es_la_variante_de_asyncio() -> None:
    retry = no_retry_async()
    assert isinstance(retry, redis_async.retry.Retry)
    assert retry.get_retries() == 0
    assert isinstance(retry._backoff, NoBackoff)


def test_cada_llamada_devuelve_una_instancia_nueva() -> None:
    """Un Retry compartido arrastraria _retries mutado entre clientes."""
    assert no_retry() is not no_retry()
    assert no_retry_async() is not no_retry_async()
