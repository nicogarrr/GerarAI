"""Toda cola declarada tiene consumidor EFECTIVO y fila en docs/workers-colas.md.

Deriva de la misma clase de fallos que cerro #4812 (DEFAULT_QUEUES del
watchdog vs colas vivas): una cola declarada sin consumidor acumula
mensajes en Redis para siempre (ningun actor usa ``max_age``), y la tabla
de ``docs/workers-colas.md`` es la referencia operativa que la taxonomia
promete. Este test fija ambas cosas contra el codigo vivo.

Las colas efectivas se calculan con el PARSER REAL de la version de
Dramatiq instalada, no releyendo los valores tras ``-Q``: #4888 demostro
que ``-Q yahoo -Q yahoo-news`` deja la cola ``yahoo`` sin consumidor
porque argparse conserva solo la ultima ocurrencia. Una lectura en union
habria dado verde falso.

Excepciones fijadas a proposito (no descuido):

- ``ibkr-sync``: su consumidor vive en el overlay opt-in
  ``docker-compose.ibkr-sync.yml`` (PR #2773), no en el compose principal.
- ``yahoo-news``: cola efimera sin actores; ``worker-yahoo`` solo la drena
  (transicion de #3763, ver ``tests/test_provider_lanes.py``). No se exige
  que este declarada.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = [
    REPO_ROOT / "docker-compose.prod.yml",
    REPO_ROOT / "docker-compose.ibkr-sync.yml",
]
DOC_PATH = REPO_ROOT / "docs" / "workers-colas.md"


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, tag, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode)
    else (
        loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node)
    ),
)


def _colas_consumidas() -> dict[str, str]:
    """Cola -> servicio que la consume, con la semantica real del CLI."""
    from dramatiq.cli import make_argument_parser

    consumidas: dict[str, str] = {}
    for path in COMPOSE_PATHS:
        compose = yaml.load(path.read_text(), Loader=_ComposeLoader)
        for nombre, svc in (compose.get("services") or {}).items():
            comando = svc.get("command")
            if not comando or "dramatiq" not in comando:
                continue
            resuelto = [
                re.sub(r"\$\{[^}]*:-([^}]*)\}", r"\1", str(parte))
                for parte in comando
            ]
            args = make_argument_parser().parse_args(resuelto[1:])
            # Sin -Q, Worker consume TODAS las colas declaradas
            # (``consumer_whitelist = queues and set(queues)`` -> None).
            if args.queues is None:
                from app.workers.dramatiq_app import broker

                colas = broker.get_declared_queues()
            else:
                colas = args.queues
            for cola in colas:
                consumidas.setdefault(cola, nombre)
    return consumidas


def test_toda_cola_declarada_tiene_consumidor():
    from app.workers.dramatiq_app import broker

    consumidas = _colas_consumidas()
    declaradas = set(broker.get_declared_queues())
    huerfanas = declaradas - set(consumidas)
    assert not huerfanas, (
        f"colas declaradas sin consumidor efectivo en compose: {sorted(huerfanas)}; "
        "consumidas: " + ", ".join(f"{q}->{s}" for q, s in sorted(consumidas.items()))
    )


def test_doc_workers_colas_menciona_toda_cola_declarada():
    from app.workers.dramatiq_app import broker

    doc = DOC_PATH.read_text()
    faltan = [q for q in broker.get_declared_queues() if f"`{q}`" not in doc]
    assert not faltan, f"docs/workers-colas.md no documenta: {sorted(faltan)}"
