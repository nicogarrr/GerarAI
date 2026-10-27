"""Toda action de terceros en los workflows va fijada por SHA completo.

Revisión GerarAI, hallazgo B1: convivían refs por tag (`actions/checkout@v7`) con refs por
SHA. Un tag es mutable: si alguien compromete la action y mueve el tag, el CI ejecuta su
código con el token del repo. Dependabot (ecosistema github-actions) sigue actualizando
los SHA y el comentario `# vX` con la versión.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _workflow_files() -> list[Path]:
    gh = REPO_ROOT / ".github"
    return sorted([*gh.glob("workflows/*.yml"), *gh.glob("workflows/*.yaml"), *gh.glob("actions/**/*.yml")])


def test_hay_workflows():
    assert _workflow_files()


def test_actions_fijadas_por_sha():
    sueltas: list[str] = []
    for path in _workflow_files():
        for ref in _USES.findall(path.read_text(encoding="utf-8")):
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            if not _PINNED.match(ref):
                sueltas.append(f"{path.relative_to(REPO_ROOT)}: {ref}")
    assert sueltas == [], "actions sin fijar por SHA:\n" + "\n".join(sueltas)
