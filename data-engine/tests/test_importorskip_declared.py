"""Guard anti-skips silenciosos (generalización de #4975).

El hueco de queue_watchdog (39,4% en CI) nació de un importorskip de un
paquete NO declarado en el extra test: fuera del venv local el test se
saltaba sin ruido. Esta guardia recorre todos los pytest.importorskip de
tests/ y exige que cada módulo sea:

  1. interno (app.*), o
  2. de un paquete declarado en [project].dependencies o en un extra de
     [project.optional-dependencies] (el lock lo instala siempre), o
  3. una excepción explícita y razonada (workflow aparte que lo instala).

Un importorskip nuevo que no encaje en ninguna de las tres falla aquí con
el fichero y el módulo, antes de que el skip silencioso llegue a CI.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]

# Módulo (top-level) -> distribución PyPI cuando no coinciden (vacío hoy:
# todos los importorskip actuales casan por identidad). Si la guardia falla
# con un módulo cuya distribución se llama distinto (p.ej. yaml -> pyyaml),
# la entrada va AQUÍ, no en ALLOWED_UNDECLARED.
MODULE_TO_DIST: dict[str, str] = {}

# Excepciones razonadas: paquetes instalados por un workflow aparte, no por
# el extra test. Cada entrada dice dónde se instala; si ese workflow cambia,
# esta tabla se revisa a propósito.
ALLOWED_UNDECLARED = {
    "schemathesis": "api-fuzz.yml lo instala con `uv run --with`",
    "mutmut": "mutation.yml lo instala",
    "libcst": "mutation.yml lo instala",
}

# Nombre de módulo entre comillas: "fakeredis", "uvicorn.logging". Prosa como
# `"importorskip(" in path...` no casa: el primer caracter sería un espacio.
_IMPORTORSKIP = re.compile(r"""importorskip\(\s*["']([A-Za-z_][\w.]*)["']""")


def _declared_distributions() -> set[str]:
    pyproject = tomllib.loads((ENGINE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    reqs = list(pyproject["project"].get("dependencies", []))
    for extra in pyproject["project"].get("optional-dependencies", {}).values():
        reqs.extend(extra)
    names = set()
    for req in reqs:
        name = re.split(r"[>=<~!;\[ ]", req, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def _importorskip_targets() -> dict[str, list[str]]:
    """Módulo -> ficheros de tests/ que lo importan con importorskip."""
    targets: dict[str, list[str]] = {}
    for path in sorted(ENGINE_ROOT.glob("tests/**/*.py")):
        for module in _IMPORTORSKIP.findall(path.read_text(encoding="utf-8")):
            targets.setdefault(module, []).append(str(path.relative_to(ENGINE_ROOT)))
    return targets


def test_todo_importorskip_es_interno_declarado_o_excepcion_razonada():
    declared = _declared_distributions()
    offenders = []
    for module, files in sorted(_importorskip_targets().items()):
        if module.startswith("app."):
            continue  # módulo interno: el skip es por wiring, no por paquete
        top = module.split(".")[0]
        dist = MODULE_TO_DIST.get(top, top).lower().replace("_", "-")
        if dist in declared:
            continue
        if top in ALLOWED_UNDECLARED or module in ALLOWED_UNDECLARED:
            continue
        offenders.append(f"{module} (en {', '.join(files)})")
    assert not offenders, (
        "importorskip de paquetes NO declarados en pyproject ni excepcionados "
        "(skip silencioso fuera de venvs completos): " + "; ".join(offenders)
    )


def test_las_excepciones_siguen_usandose():
    """Una excepción sin importorskip vivo es deuda invisible: fuera."""
    targets = _importorskip_targets()
    for module, reason in ALLOWED_UNDECLARED.items():
        assert any(t == module or t.startswith(module + ".") for t in targets), (
            f"excepción muerta: {module} ({reason})"
        )


def test_la_tabla_de_mapeo_modulo_dist_sigue_usandose():
    targets = _importorskip_targets()
    tops = {m.split(".")[0] for m in targets}
    for module in MODULE_TO_DIST:
        assert module in tops, f"mapeo muerto: {module} -> {MODULE_TO_DIST[module]}"
