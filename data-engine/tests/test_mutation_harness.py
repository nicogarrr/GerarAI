"""Arnes de mutacion (``scripts/mutation/run_mutmut.py``): tramos por lineas.

``compute_report`` (~530 lineas) genera >1.100 mutantes y mutmut escribe una
copia de la funcion entera por mutante: sin acotar por lineas la pasada no
termina. Se fija que los tramos cubren el fichero sin huecos y que el runner
acotado solo deja mutar el tramo pedido.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mutation" / "run_mutmut.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("run_mutmut_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ficheros_de_test_de_targets_existen(harness):
    root = SCRIPT.parents[2]
    for name, (src, tests) in harness.TARGETS.items():
        assert (root / src).is_file(), name
        for test in tests:
            assert (root / test).is_file(), f"{name}: {test}"


SAMPLE = """\
import os

CONST = 1


def uno(x):
    if x > 1:
        y = 2
    elif x < 0:
        y = 3
    else:
        y = 4
    return y


@decorador
def dos(x):
    return x + 1


class Tres:
    def metodo(self):
        a = 1
        b = 2
        return a + b
"""


def test_statement_chunks_contiguos_desde_la_primera_def(harness, tmp_path):
    path = tmp_path / "mod.py"
    path.write_text(SAMPLE, encoding="utf-8")
    lines = SAMPLE.splitlines()
    for size in (1, 3, 5, 100):
        chunks = harness.statement_chunks(path, size)
        assert chunks[0][0] == 6  # def uno: imports y constantes fuera
        assert chunks[-1][1] == len(lines)
        for (_a, end), (start, _b) in zip(chunks, chunks[1:]):
            assert start == end + 1  # sin huecos ni solapes
        for start, _end in chunks:
            text = lines[start - 1].lstrip()
            assert not text.startswith("elif")
            assert not text.startswith("def dos")  # el decorador va con su funcion
    assert harness.statement_chunks(path, 100) == [(6, len(lines))]


def test_runner_acotado_solo_deja_mutar_el_tramo(harness, tmp_path, monkeypatch):
    libcst = pytest.importorskip("libcst")
    pytest.importorskip("mutmut")
    from mutmut.mutation import file_mutation, pragma_handling

    monkeypatch.setattr(pragma_handling, "get_ignored_lines", pragma_handling.get_ignored_lines)
    monkeypatch.setattr(file_mutation, "get_ignored_lines", file_mutation.get_ignored_lines)
    # Sin configuracion de mutmut en el repo: los patrones globales no aplican.
    monkeypatch.setattr(pragma_handling, "get_lines_ignored_by_pattern", lambda source: set())
    runner = harness._write_scoped_runner(tmp_path, "app/services/mod.py", 7, 13)
    code = runner.read_text(encoding="utf-8").replace(
        "from mutmut.__main__ import cli  # noqa: E402\n\nsys.exit(cli())\n", ""
    )
    exec(compile(code, str(runner), "exec"), {"__name__": "scoped_runner"})
    assert file_mutation.get_ignored_lines is pragma_handling.get_ignored_lines

    wrapper = libcst.MetadataWrapper(libcst.parse_module(SAMPLE))
    total = len(SAMPLE.splitlines()) + 1
    ignored = pragma_handling.get_ignored_lines("/x/app/services/mod.py", SAMPLE, wrapper)
    assert ignored.no_mutate_lines == {n for n in range(1, total + 1) if n < 7 or n > 13}
    # Otro fichero: sin recorte.
    other = pragma_handling.get_ignored_lines("app/services/otro.py", SAMPLE, wrapper)
    assert not (other.no_mutate_lines & set(range(1, total + 1)))
    assert sys.modules.get("scoped_runner") is None
