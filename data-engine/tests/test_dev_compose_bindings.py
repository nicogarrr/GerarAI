"""El compose de desarrollo no debe publicar bases de datos en todas las interfaces.

Revisión GerarAI, hallazgo M4: con contraseñas de desarrollo públicas (example, portfolio,
portfoliosecret), un puerto publicado como "5432:5432" escucha en 0.0.0.0 y cualquier
equipo de la red puede entrar. Cada puerto debe ir prefijado por un host que por defecto
sea 127.0.0.1.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
_DEFAULT_HOST = re.compile(r"^\$\{GERARAI_BIND_HOST:-127\.0\.0\.1\}:\d+:\d+$")


def _published_ports() -> list[tuple[str, str]]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for name, svc in (data.get("services") or {}).items():
        for port in svc.get("ports") or []:
            out.append((name, str(port)))
    return out


def test_dev_compose_publica_puertos():
    assert _published_ports(), "el compose de desarrollo debería publicar algún puerto"


def test_dev_compose_solo_escucha_en_localhost_por_defecto():
    expuestos = [(svc, port) for svc, port in _published_ports() if not _DEFAULT_HOST.match(port)]
    assert expuestos == [], f"puertos publicados sin 127.0.0.1 por defecto: {expuestos}"
