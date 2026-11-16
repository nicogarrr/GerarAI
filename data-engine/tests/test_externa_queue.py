"""Carril "externa": los trabajos que queman cuota HTTP fuera no comparten
la cola default (31-oct: 2 refresh_valuation_metrics ocupando los 2 hilos de
default, 7.617 pendientes; 1.077 HTTP 429 en 10 min, medido por el piloto).

queue_name solo enruta mensajes NUEVOS: los ya encolados en default los
drena el worker default; nada que purgar.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
WORKERS_PATH = Path(__file__).resolve().parents[1] / "app" / "workers" / "dramatiq_app.py"

# 31-oct: backfill_finnhub_profiles salio al carril "finnhub" (test_provider_lanes.py).
ACTORES_EXTERNOS = [
    "refresh_valuation_metrics",      # yfinance + Finnhub (las 1.077)
    "backfill_sec_fundamentals",      # SEC EDGAR
    "backfill_company_price_history",  # proveedor de precios
]


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, tag, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode)
    else (loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
          else loader.construct_scalar(node)),
)


def test_actores_de_apis_externas_van_en_cola_externa():
    from app.workers.dramatiq_app import broker

    for nombre in ACTORES_EXTERNOS:
        actor = broker.get_actor(nombre)
        assert actor.queue_name == "externa", f"{nombre} en {actor.queue_name}"


def test_solo_esos_actores_declaran_la_cola():
    fuente = WORKERS_PATH.read_text()
    declaraciones = re.findall(r"queue_name=EXTERNA_QUEUE_NAME", fuente)
    assert len(declaraciones) == len(ACTORES_EXTERNOS), declaraciones


def test_worker_externa_consume_la_cola_con_claves_de_fuente():
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    servicio = compose["services"]["worker-externa"]
    comando = servicio["command"]
    assert comando[comando.index("-Q") + 1] == "externa"
    env = servicio["environment"]
    assert "FINNHUB_API_KEY" in env
    # El worker general NO consume externa: el aislamiento del carril es real.
    general = compose["services"]["worker"]["command"]
    assert "externa" not in general
    # Techo 20480 MiB frente a host23972; margen3492, no garantia de capacidad.
    _assert_memory_budget(compose)
    compose["services"]["backend"]["deploy"]["resources"]["limits"]["memory"] = "3G"
    with pytest.raises(AssertionError, match="20480"):
        _assert_memory_budget(compose)


def test_refresh_valuation_metrics_tiene_time_limit_acotado():
    """Sin limite, una corrida lenta de universo ocupaba un hilo del carril
    horas (31-oct: 2 corridas sosteniendo 7.617 pendientes). 1 h acota la
    ocupacion; el cursor en Redis reanuda sin rehacer lo comprometido."""
    from app.workers.dramatiq_app import broker

    actor = broker.get_actor("refresh_valuation_metrics")
    assert actor.options["time_limit"] == 3_600_000


def test_worker_externa_sin_prefetch_extra():
    """Trabajos pesados y largos: prefetch 1 como worker-knowledge; un
    mensaje prefetcheado espera en local invisible para HLEN."""
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    env = compose["services"]["worker-externa"]["environment"]
    assert env["dramatiq_queue_prefetch"] == "1"
    assert env["dramatiq_delay_queue_prefetch"] == "1"


def _assert_memory_budget(compose):
    """Presupuesto fijo, no derivado de la suma ni del tamaño del mutante."""
    total = 0
    for name, service in compose["services"].items():
        limits = service.get("deploy", {}).get("resources", {}).get("limits", {})
        assert "memory" in limits, f"{name} sin limite de memoria"
        memory = str(limits["memory"])
        value = float(memory.rstrip("MG"))
        total += int(value * 1024) if memory.endswith("G") else int(value)
    assert total <= 20480, f"los limites suman {total} MiB (>20480 MiB)"
