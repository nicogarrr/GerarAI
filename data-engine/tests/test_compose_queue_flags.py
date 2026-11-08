"""Los comandos Dramatiq del compose no repiten -Q: el ultimo pisa a los demas.

Bug real (8-nov-2026): `worker-yahoo` arrancaba con
``-Q yahoo -Q yahoo-news``. ``argparse`` conserva solo la ULTIMA ocurrencia
de una opcion, asi que el proceso consumia unicamente ``yahoo-news`` y la
cola ``yahoo`` (6 actores de ingesta) se quedaba sin consumidor efectivo.
La VM ya corria la forma correcta; un deploy desde el repo la regresaba.

Repro con el parser real de Dramatiq 2.2.1::

    make_argument_parser().parse_args(
        ["app.workers.dramatiq_app", "-Q", "yahoo", "-Q", "yahoo-news"]
    ).queues == ["yahoo-news"]

La forma correcta es UN solo ``-Q`` con todos los valores (``nargs="*"``):
``-Q yahoo yahoo-news``. Este test parsea cada comando Dramatiq de los
compose con el parser real de la version instalada y exige:

1. Ningun comando repite ``-Q``/``--queues``.
2. Las colas efectivas de ``worker-yahoo`` son exactamente ``yahoo`` +
   ``yahoo-news`` (drenaje efimero de #3763).
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


def _comandos_dramatiq() -> dict[str, list[str]]:
    """Servicio -> comando con la interpolacion ${VAR:-def} ya resuelta."""
    comandos: dict[str, list[str]] = {}
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
            comandos[f"{path.name}:{nombre}"] = resuelto
    return comandos


def test_ningun_comando_repite_la_flag_de_colas():
    repetidos = {
        nombre: comando
        for nombre, comando in _comandos_dramatiq().items()
        if sum(1 for parte in comando if parte in ("-Q", "--queues")) > 1
    }
    assert not repetidos, (
        "argparse conserva solo el ultimo -Q; unifica los valores en uno: "
        f"{sorted(repetidos)}"
    )


def test_colas_efectivas_con_el_parser_real():
    from dramatiq.cli import make_argument_parser

    efectivas: dict[str, list[str] | None] = {}
    for nombre, comando in _comandos_dramatiq().items():
        args = make_argument_parser().parse_args(comando[1:])
        efectivas[nombre] = args.queues
    yahoo = efectivas["docker-compose.prod.yml:worker-yahoo"]
    assert sorted(yahoo or []) == ["yahoo", "yahoo-news"], yahoo
