"""Contrato del A/B de carga Postgres (scripts/backup/pg_load_ab.py).

Sin docker en el test: el plan de carga, el parseo de topes y el muestreo de
memoria se prueban puros; el ciclo completo lo ejecuta el piloto en la VM.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup import pg_load_ab  # noqa: E402
from scripts.backup._kit import FailClosedError  # noqa: E402
from scripts.backup.disaster_drill import DrillEnvironment  # noqa: E402


def _tables() -> list[pg_load_ab.TableInfo]:
    return [
        pg_load_ab.TableInfo("alpha", "id", "name", 1000),
        pg_load_ab.TableInfo("beta", "id", None, 10),
        pg_load_ab.TableInfo("gamma", "code", "label", 0),
    ]


# --- topes -----------------------------------------------------------------


def test_parse_caps_acepta_los_topes_del_ab():
    assert pg_load_ab.parse_caps("896m,4g,6g,8g") == ["896m", "4g", "6g", "8g"]


def test_parse_caps_normaliza_mayusculas_y_espacios():
    assert pg_load_ab.parse_caps(" 896M , 4G ") == ["896m", "4g"]


@pytest.mark.parametrize("bad", ["", "1t", "mb", "-5g", "896", "4 g,x"])
def test_parse_caps_rechaza_formatos_invalidos(bad):
    with pytest.raises(FailClosedError):
        pg_load_ab.parse_caps(bad)


# --- plan de carga: determinismo (la MISMA carga en cada tope) --------------


def test_plan_determinista_misma_semilla_mismo_plan():
    plan_a = pg_load_ab.build_plan(_tables(), rounds=2, seed=42)
    plan_b = pg_load_ab.build_plan(_tables(), rounds=2, seed=42)
    assert plan_a == plan_b


def test_plan_cambia_con_la_semilla():
    plan_a = pg_load_ab.build_plan(_tables(), rounds=2, seed=42)
    plan_b = pg_load_ab.build_plan(_tables(), rounds=2, seed=7)
    assert plan_a != plan_b


def test_plan_cubre_plantillas_y_respeta_tablas_sin_texto():
    plan = pg_load_ab.build_plan(_tables(), rounds=1, seed=42)
    por_tabla = {}
    for step in plan:
        por_tabla.setdefault(step.table, set()).add(step.template)
    # beta no tiene columna de texto: sin consulta sort, pero count y window si
    assert por_tabla["beta"] == {"count", "window"}
    assert por_tabla["alpha"] == {"count", "window", "sort"}
    # 1 ronda: alpha 3 + beta 2 + gamma 3
    assert len(plan) == 8


def test_plan_escapa_identificadores():
    tables = [pg_load_ab.TableInfo('ta"ble', 'co"l', None, 5)]
    plan = pg_load_ab.build_plan(tables, rounds=1, seed=1)
    for step in plan:
        assert '""' in step.sql or step.template == "count"
    assert 'FROM "ta""ble"' in plan[0].sql


def test_plan_vacio_es_fail_closed():
    with pytest.raises(FailClosedError):
        pg_load_ab.build_plan([], rounds=1, seed=1)


# --- memoria ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("123.4MiB / 896MiB", int(123.4 * 1024**2)),
        ("1.5GiB / 4GiB", int(1.5 * 1024**3)),
        ("900MB / 1GB", 900 * 1000**2),
        ("0B / 896MiB", 0),
        ("no-parseable", 0),
    ],
)
def test_parse_mem_usage(text, expected):
    assert pg_load_ab._parse_mem_usage(text) == expected


def test_percentile():
    assert pg_load_ab._percentile([1.0, 2.0, 3.0, 4.0], 50) == 3.0  # mediana alta: round(1.5)=2
    assert pg_load_ab._percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert pg_load_ab._percentile([], 95) == 0.0


# --- tope en el entorno del drill --------------------------------------------


def test_drill_sin_tope_no_pasa_memory():
    drill = DrillEnvironment(workdir=Path("/tmp/x"))
    options = drill._pg_options("vol")
    assert "--memory" not in options


def test_drill_con_tope_pasa_memory_y_swap_igual():
    drill = DrillEnvironment(workdir=Path("/tmp/x"), pg_memory="896m")
    options = drill._pg_options("vol")
    idx = options.index("--memory")
    assert options[idx + 1] == "896m"
    idx_swap = options.index("--memory-swap")
    assert options[idx_swap + 1] == "896m"


# --- informe ------------------------------------------------------------------


def test_estado_contenedor_interpreta_oom(monkeypatch):
    class R:
        stdout = "true running"

    monkeypatch.setattr(pg_load_ab, "run", lambda *a, **k: R())
    state = pg_load_ab.container_state("cualquiera")
    assert state == {"oom_killed": True, "status": "running"}


def test_parser_por_defecto_es_la_matriz_del_ab():
    args = pg_load_ab.build_parser().parse_args([])
    assert args.caps == "896m,4g,6g,8g"
    assert args.seed == 42
    assert args.external is False
