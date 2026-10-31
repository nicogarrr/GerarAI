"""Actores fixture del A/B real de carriles por proveedor (#3763).

Sin red, sin DB: los actores SOLO duermen y anotan tiempos en el Redis
aislado de la corrida (TcpFakeServer local, un servidor nuevo por corrida).
Duraciones por env para el humo rapido y la corrida oficial.
"""
from __future__ import annotations

import os
import time

import dramatiq
import redis
from dramatiq.brokers.redis import RedisBroker

REDIS_URL = os.environ["BENCH_REDIS_URL"]
NAMESPACE = os.environ.get("BENCH_NS", "bench")
LONG_S = float(os.environ.get("BENCH_LONG_S", "20"))
SHORT_S = float(os.environ.get("BENCH_SHORT_S", "0.5"))
# Cola de cada actor segun la topologia de la corrida (A: ambas "shared";
# B: "largo"/"corto"). Dramatiq solo crea consumidores de colas con actores
# declarados en ellas, asi que la cola se declara en el actor.
QUEUE_LARGO = os.environ.get("BENCH_QUEUE_LARGO", "shared")
QUEUE_CORTO = os.environ.get("BENCH_QUEUE_CORTO", "shared")

broker = RedisBroker(url=REDIS_URL, namespace=NAMESPACE)
dramatiq.set_broker(broker)


def _marca(clave: str) -> None:
    redis.Redis.from_url(REDIS_URL).rpush(f"bench:marca:{clave}", repr(time.time()))


@dramatiq.actor(max_retries=0, queue_name=QUEUE_LARGO)
def bench_largo(indice: int) -> None:
    _marca(f"largo:{indice}:inicio")
    time.sleep(LONG_S)
    _marca(f"largo:{indice}:fin")


@dramatiq.actor(max_retries=0, queue_name=QUEUE_CORTO)
def bench_corto(indice: int) -> None:
    time.sleep(SHORT_S)
    _marca(f"corto:{indice}:fin")
