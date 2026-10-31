"""Carril "externa": los trabajos que queman cuota HTTP fuera no comparten
la cola default (31-oct: 2 refresh_valuation_metrics ocupando los 2 hilos de
default, 7.617 pendientes; 1.077 HTTP 429 en 10 min, medido por el piloto).

queue_name solo enruta mensajes NUEVOS: los ya encolados en default los
drena el worker default; nada que purgar.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
WORKERS_PATH = Path(__file__).resolve().parents[1] / "app" / "workers" / "dramatiq_app.py"

ACTORES_EXTERNOS = [
    "refresh_valuation_metrics",      # yfinance + Finnhub (las 1.077)
    "backfill_finnhub_profiles",      # Finnhub
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
    # Presupuesto de memoria del stack intacto (techo 16 GiB, host 24 GB).
    total = 0
    for svc in compose["services"].values():
        memoria = str(svc["deploy"]["resources"]["limits"]["memory"])
        valor = float(memoria.rstrip("MG"))
        total += int(valor * 1024) if memoria.endswith("G") else int(valor)
    assert total <= 16384, f"los limites suman {total} MiB"
