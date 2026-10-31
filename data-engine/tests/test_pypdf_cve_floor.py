"""Suelo de version de pypdf: 6.21.4 (siete CVE DoS, todas parcheadas).

Alertas Dependabot #30-#36 (CVE-2026-119203 a CVE-2026-119209): bucles
infinitos y consumo de memoria analizando PDFs manipulados (xref, page
tree, page labels, modo estricto, cifrados). Alcanzable: el usuario sube
PDFs (knowledge, ingesta de fuentes) y el pipeline los parsea con pypdf
(carril clasico de parse_pdf_two_lane). El freno de tiempo/memoria del
worker acota el dano, pero la correccion es la version parcheada.

Este guard es ROJO con pypdf < 6.21.3 (tres CVE sin parche) y exige la
6.21.4 para cubrir las siete. Si una futura version de pypdf rompe el
pipeline, bajar por debajo del suelo vuelve a poner el test en rojo.
"""

from __future__ import annotations

import pathlib
from importlib.metadata import version


def _as_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_pypdf_floor_6_21_4() -> None:
    installed = _as_tuple(version("pypdf"))
    assert installed >= (6, 21, 4), (
        f"pypdf {version('pypdf')} < 6.21.4: CVE-2026-119203..209 (DoS) sin parche"
    )

_DECLARED_FLOOR = "pypdf>=6.21.4,<7"


def test_declared_floor_matches_lock() -> None:
    """pyproject y requirements declaran el mismo suelo que resuelve uv.lock.

    El Docker de prod instala con pip desde requirements.txt: un suelo flojo
    ahi dejaria prod en una pypdf vulnerable aunque uv.lock este parcheado
    (objecion del piloto a #3754).
    """
    root = __file__.rsplit("/tests/", 1)[0]
    pyproject = (pathlib.Path(root) / "pyproject.toml").read_text()
    requirements = (pathlib.Path(root) / "requirements.txt").read_text()
    assert _DECLARED_FLOOR in pyproject, "pyproject.toml sin el suelo pypdf>=6.21.4,<7"
    assert _DECLARED_FLOOR in requirements, "requirements.txt sin el suelo pypdf>=6.21.4,<7 (regenerar con scripts/sync_requirements.py --write)"

