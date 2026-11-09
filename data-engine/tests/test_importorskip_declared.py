"""Guard anti-skips silenciosos (generalización de #4975; endurecida tras las
salvedades del auditor de #5007).

El hueco de queue_watchdog (39,4% en CI) nació de un importorskip de un
paquete NO declarado en el extra test: fuera del venv local el test se
saltaba sin ruido. Esta guardia recorre todos los pytest.importorskip de
tests/ y exige que cada módulo sea:

  1. interno (app.*), o
  2. de un paquete instalado por los jobs que corren pytest
     ([project].dependencies + los extras que sincronizan ci.yml y
     coverage.yml: `uv sync --frozen --extra test --extra dev`), o
  3. una excepción explícita y razonada (workflow aparte que lo instala).

Endurecimientos sobre la versión regex:
- AST, no regex: un importorskip con el módulo en una variable o un alias
  (`import pytest as pt`, `from pytest import importorskip as ios`) ya no es
  un bypass silencioso: la guardia lo detecta y exige nombre literal.
- Normalización PEP503 completa (rachas de `-_.` colapsan a `-`): antes
  `zope.interface` declarado no cubría importorskip("zope.interface").
- Solo cuentan los extras que instalan los jobs de tests; un paquete en un
  extra que CI no instala NO cuenta como declarado, y un extra nuevo en
  pyproject obliga a clasificarlo aquí a propósito.
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]

# Módulo -> distribución PyPI cuando no coinciden (vacío hoy: todos los
# importorskip actuales casan por identidad). La clave puede ser el top-level
# (yaml -> pyyaml) o el módulo completo con puntos. OJO: un módulo con puntos
# también se prueba tal cual como distribución (importorskip("zope.interface")
# queda cubierto por la distribución zope.interface, PEP503 zope-interface),
# así que los namespace packages no necesitan entrada aquí. Si la guardia
# falla con un módulo cuya distribución se llama distinto de verdad, la
# entrada va AQUÍ, no en ALLOWED_UNDECLARED.
MODULE_TO_DIST: dict[str, str] = {}

# Excepciones razonadas: paquetes instalados por un workflow aparte, no por
# los extras de los jobs de tests. Cada entrada dice dónde se instala; si ese
# workflow cambia, esta tabla se revisa a propósito.
ALLOWED_UNDECLARED = {
    "schemathesis": "api-fuzz.yml lo instala con `uv run --with`",
    "mutmut": "mutation.yml lo instala",
    "libcst": "mutation.yml lo instala",
}

# Extras que instalan los jobs que corren pytest (ci.yml, coverage.yml e
# ingest-evals.yml sincronizan `--extra test --extra dev`). Un importorskip
# satisfecho SOLO por otro extra se saltaría en CI: no cuenta como declarado.
EXTRAS_DE_LOS_JOBS_DE_TESTS = {"test", "dev"}

# Extras de pyproject que los jobs de tests NO instalan, con la razón (vacío
# hoy). test_un_extra_nuevo_obliga_a_decidir exige toda entrada viva.
EXTRAS_FUERA_DE_LOS_JOBS: dict[str, str] = {}


def _pep503(name: str) -> str:
    """Normalización PEP503: minúsculas y rachas de `-_.` colapsadas a `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _importorskip_en(path: Path) -> tuple[list[str], list[str]]:
    """(módulos con nombre literal, llamadas con nombre NO literal).

    AST, no regex: `pytest.importorskip(MODULO)` o cualquier alias de pytest/
    importorskip queda registrado como llamada no literal (la guardia no
    puede verificarla y la exige literal). Las ubicaciones fuera de
    ENGINE_ROOT (tests unitarios con tmp_path) se reportan con su ruta tal
    cual.
    """
    # utf-8-sig: hay tests con BOM (test_money_path_contracts.py) y ast.parse
    # rechaza el U+FEFF inicial.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    pytest_names = {"pytest"}
    direct_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pytest":
                    pytest_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
            for alias in node.names:
                if alias.name == "importorskip":
                    direct_names.add(alias.asname or alias.name)
    literal: list[str] = []
    nonliteral: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        es_importorskip = (
            isinstance(func, ast.Attribute)
            and func.attr == "importorskip"
            and isinstance(func.value, ast.Name)
            and func.value.id in pytest_names
        ) or (isinstance(func, ast.Name) and func.id in direct_names)
        if not es_importorskip:
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            literal.append(node.args[0].value)
            continue
        try:
            donde = str(path.relative_to(ENGINE_ROOT))
        except ValueError:
            donde = str(path)
        arg = ast.unparse(node.args[0]) if node.args else "(sin argumentos)"
        nonliteral.append(f"{donde}:{node.lineno} -> importorskip({arg})")
    return literal, nonliteral


def _declared_distributions(pyproject_text: str | None = None) -> set[str]:
    """Distribuciones instaladas por los jobs de tests, normalizadas PEP503:
    [project].dependencies + SOLO los extras de EXTRAS_DE_LOS_JOBS_DE_TESTS."""
    text = (
        pyproject_text
        if pyproject_text is not None
        else (ENGINE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads(text)
    reqs = list(pyproject["project"].get("dependencies", []))
    for extra, deps in pyproject["project"].get("optional-dependencies", {}).items():
        if extra in EXTRAS_DE_LOS_JOBS_DE_TESTS:
            reqs.extend(deps)
    names = set()
    for req in reqs:
        name = re.split(r"[>=<~!;\[ ]", req, maxsplit=1)[0].strip()
        if name:
            names.add(_pep503(name))
    return names


def _importorskip_targets() -> dict[str, list[str]]:
    """Módulo -> ficheros de tests/ que lo importan con importorskip literal."""
    targets: dict[str, list[str]] = {}
    for path in sorted(ENGINE_ROOT.glob("tests/**/*.py")):
        literal, _ = _importorskip_en(path)
        for module in literal:
            targets.setdefault(module, []).append(str(path.relative_to(ENGINE_ROOT)))
    return targets


def _esta_cubierto(module: str, declared: set[str]) -> bool:
    """El módulo de un importorskip está cubierto si es interno, si alguna de
    sus candidatas a distribución está instalada por los jobs de tests o si
    es una excepción razonada. Candidatas: el módulo completo y su top-level,
    ambos tras MODULE_TO_DIST y normalizados PEP503 — así
    importorskip("zope.interface") queda cubierto por la distribución
    zope.interface sin falso positivo (hallazgo del auditor de #5035).
    """
    if module.startswith("app."):
        return True  # módulo interno: el skip es por wiring, no por paquete
    top = module.split(".")[0]
    candidatos = {
        _pep503(MODULE_TO_DIST.get(module, module)),
        _pep503(MODULE_TO_DIST.get(top, top)),
    }
    if candidatos & declared:
        return True
    return top in ALLOWED_UNDECLARED or module in ALLOWED_UNDECLARED


def test_todo_importorskip_es_interno_declarado_o_excepcion_razonada():
    declared = _declared_distributions()
    offenders = []
    for module, files in sorted(_importorskip_targets().items()):
        if _esta_cubierto(module, declared):
            continue
        offenders.append(f"{module} (en {', '.join(files)})")
    assert not offenders, (
        "importorskip de paquetes NO instalados por los jobs de tests ni "
        "excepcionados (skip silencioso fuera de venvs completos): "
        + "; ".join(offenders)
    )


def test_importorskip_siempre_con_nombre_literal():
    """La guardia solo puede verificar literales: un alias o variable la
    dejaría ciega, así que se exige `importorskip("nombre")` siempre."""
    hallazgos = []
    for path in sorted(ENGINE_ROOT.glob("tests/**/*.py")):
        _, nonliteral = _importorskip_en(path)
        hallazgos.extend(nonliteral)
    assert not hallazgos, (
        "importorskip con el módulo NO literal (la guardia no puede "
        "verificarlo; usa un string literal): " + "; ".join(hallazgos)
    )


def test_un_extra_nuevo_obliga_a_decidir_si_lo_instalan_los_jobs():
    """Un extra sin clasificar convertiría cualquier importorskip suyo en un
    skip silencioso en CI: se decide aquí, no por accidente."""
    pyproject = tomllib.loads((ENGINE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"].get("optional-dependencies", {})
    for extra in extras:
        assert extra in EXTRAS_DE_LOS_JOBS_DE_TESTS or extra in EXTRAS_FUERA_DE_LOS_JOBS, (
            f"extra '{extra}' sin clasificar: o lo instalan los jobs de tests "
            "(EXTRAS_DE_LOS_JOBS_DE_TESTS) o se razona en EXTRAS_FUERA_DE_LOS_JOBS"
        )
    for extra in EXTRAS_FUERA_DE_LOS_JOBS:
        assert extra in extras, (
            f"EXTRAS_FUERA_DE_LOS_JOBS muerto: '{extra}' ya no existe en pyproject"
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
        assert module in targets or module in tops, (
            f"mapeo muerto: {module} -> {MODULE_TO_DIST[module]}"
        )


def test_modulo_con_puntos_cubierto_por_su_distribucion_pep503():
    """El caso del auditor: importorskip("zope.interface") con la
    distribución zope.interface declarada (PEP503: zope-interface) NO es un
    falso positivo; sin la candidata de módulo completo lo sería."""
    assert _esta_cubierto("zope.interface", {"zope-interface"})
    assert not _esta_cubierto("zope.interface", {"otra-cosa"})
    # El mapeo explícito por módulo completo también cubre.
    MODULE_TO_DIST["uvicorn.logging"] = "uvicorn"
    try:
        assert _esta_cubierto("uvicorn.logging", {"uvicorn"})
    finally:
        del MODULE_TO_DIST["uvicorn.logging"]


def test_normalizacion_pep503():
    assert _pep503("Foo_Bar.Baz") == "foo-bar-baz"
    assert _pep503("zope.interface") == "zope-interface"
    assert _pep503("fakeredis") == "fakeredis"


def test_un_paquete_solo_en_un_extra_no_instalado_no_cuenta_como_declarado():
    sintetico = """
[project]
name = "x"
dependencies = ["redis>=5"]
[project.optional-dependencies]
test = ["fakeredis>=2"]
fuzz = ["schemathesis>=3"]
"""
    declared = _declared_distributions(sintetico)
    assert "redis" in declared
    assert "fakeredis" in declared
    assert "schemathesis" not in declared  # su extra no lo instalan los jobs


def test_el_walker_ast_pilla_alias_y_no_literales(tmp_path):
    """El bypass de la versión regex (alias + variable) ahora se detecta."""
    archivo = tmp_path / "test_ejemplo.py"
    archivo.write_text(
        "import pytest as pt\n"
        "from pytest import importorskip as ios\n"
        "MOD = 'fakeredis'\n"
        "pt.importorskip(MOD)\n"
        "ios('redis')\n",
        encoding="utf-8",
    )
    literal, nonliteral = _importorskip_en(archivo)
    assert literal == ["redis"]
    assert len(nonliteral) == 1 and "importorskip(MOD)" in nonliteral[0]
