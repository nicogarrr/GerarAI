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

from importlib.metadata import version


def _as_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_pypdf_floor_6_21_4() -> None:
    installed = _as_tuple(version("pypdf"))
    assert installed >= (6, 21, 4), (
        f"pypdf {version('pypdf')} < 6.21.4: CVE-2026-119203..209 (DoS) sin parche"
    )
