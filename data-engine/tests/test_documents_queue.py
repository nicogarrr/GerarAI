"""Carril "documents": la ingesta de documentos no frena los periodicos.

5-nov-2026 [medido piloto]: 677 process_document de KRKNF (reencolados cada
hora por refresh_ir_pages, sin dedup ni tope) ocupaban la cola default con
~3 h de backlog y los periodicos de datos (refresh_sec_filings, insider,
contradictions, RSS...) esperaban detras; el fallback de embeddings tenia el
host al 95 % CPU. Cola dedicada (autorizacion de Nico, 5-nov-2026: colas
nuevas que aporten velocidad real), 1 hilo, prefetch 1 y caches de modelos
persistentes. Los mensajes ya encolados en default los drena el worker
default; queue_name solo enruta mensajes NUEVOS, nada que purgar.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
WORKERS_PATH = Path(__file__).resolve().parents[1] / "app" / "workers" / "dramatiq_app.py"

ACTORES_DOCUMENTOS = ["process_document", "process_document_structured"]


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, tag, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode)
    else (loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
          else loader.construct_scalar(node)),
)


def test_actores_de_documentos_van_en_cola_documents():
    from app.workers.dramatiq_app import broker

    for nombre in ACTORES_DOCUMENTOS:
        actor = broker.get_actor(nombre)
        assert actor.queue_name == "documents", f"{nombre} en {actor.queue_name}"


def test_solo_esos_actores_declaran_la_cola():
    fuente = WORKERS_PATH.read_text()
    declaraciones = re.findall(r"queue_name=DOCUMENTS_QUEUE_NAME", fuente)
    assert len(declaraciones) == len(ACTORES_DOCUMENTOS), declaraciones


def test_worker_documents_consume_la_cola_aislada():
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    servicio = compose["services"]["worker-documents"]
    comando = servicio["command"]
    assert comando[comando.index("-Q") + 1] == "documents"
    # Un job pesado en curso como mucho: 1 hilo, prefetch 1.
    assert comando[comando.index("--threads") + 1] == "${DOCUMENTS_THREADS:-1}"
    env = servicio["environment"]
    assert env["dramatiq_queue_prefetch"] == "1"
    assert env["dramatiq_delay_queue_prefetch"] == "1"
    # Modelos horneados en la imagen (/opt/hf via ENV del Dockerfile): sin
    # override a un volumen vacio (con HF_HUB_OFFLINE=1 nunca se poblaria).
    assert "FASTEMBED_CACHE_PATH" not in env
    assert "HF_HOME" not in env
    # El worker general NO consume documents: el aislamiento es real.
    general = compose["services"]["worker"]["command"]
    assert "documents" not in general


def test_worker_default_usa_los_modelos_horneados_de_la_imagen():
    """El default drena el backlog ya encolado y ejecuta otros actores con
    embeddings. Primera version: FASTEMBED_CACHE_PATH=/data (volumen vacio).
    Con HF_HUB_OFFLINE=1 ese volumen nunca se poblaba: fastembed fallaba en
    el primer lote y el proceso caia PERMANENTEMENTE al fallback torch
    (103 % CPU, 2,13 GiB RSS + 1,2 GiB swap; medido por el piloto,
    5-nov-2026 02:22). Los modelos MiniLM/bm25 van horneados en la imagen
    (/opt/hf/fastembed via ENV del Dockerfile) y el carril NO puede
    re-apuntar la cache a un volumen."""
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    env = compose["services"]["worker"]["environment"]
    assert "FASTEMBED_CACHE_PATH" not in env
    assert "HF_HOME" not in env


def test_presupuesto_de_memoria_del_stack_intacto():
    """Techo 16 GiB (host 24 GB), mismo invariante que test_externa_queue."""
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    total = 0
    for svc in compose["services"].values():
        memoria = str(svc["deploy"]["resources"]["limits"]["memory"])
        valor = float(memoria.rstrip("MG"))
        total += int(valor * 1024) if memoria.endswith("G") else int(valor)
    assert total <= 16384, f"los limites suman {total} MiB"
