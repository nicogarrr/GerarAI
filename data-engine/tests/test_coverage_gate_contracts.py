"""Tests del gate de cobertura, no de la cobertura real.

Este fichero no mide nada: testa las CONTRATOS de
`scripts/run_coverage_gate.py`. Si el gate esta roto, aqui sale rojo antes de
que CI se entere, y sin necesidad de correr los 2585 tests.

Lo que se fija:
  1. los umbrales salen de coverage_baseline.json, no estan hardcodeados;
  2. una caida por paquete falla, con el paquete y los puntos en el mensaje;
  3. una subida pasa, y `--update-baseline` la convierte en la nueva linea base;
  4. baseline ausente o corrupto => fail-closed, nunca "lo dejo pasar";
  5. paquete nuevo sin declarar => fail-closed (o `exempt`, si se declara asi);
  6. el informe de salida es una lista legible de paquetes y puntos.

El modulo del gate se carga por ruta (scripts/ no es paquete) para no depender
de que `scripts` llegue a sys.path.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ENGINE_ROOT / "scripts" / "run_coverage_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("_c5_coverage_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registrar en sys.modules ANTES de exec_module no es opcional: @dataclass
    # busca sys.modules[cls.__module__] para resolver los defaults de campo y
    # revienta con AttributeError si el modulo no esta registrado.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()
PackageCoverage = gate.PackageCoverage


# --------------------------------------------------------------- fixtures


def _pkg(percent: float, statements: int = 1000) -> PackageCoverage:
    covered = round(statements * percent / 100.0)
    return PackageCoverage(percent=percent, covered=covered, total=statements)


# Declara los mismos numeros que luego se miden, para que un baseline coherente
# de verdad pase el gate sin trucos. app/services 71.0% de 6000 + app/core 55.5%
# de 2000 = 5370/8000 = 67.125%, que es el `total` declarado abajo.
_SERVICES_PCT, _SERVICES_STMTS = 71.0, 6000
_CORE_PCT, _CORE_STMTS = 55.5, 2000
_TOTAL = 100.0 * (4260 + 1110) / (_SERVICES_STMTS + _CORE_STMTS)


def _exempt(*packages: str) -> list[dict[str, str]]:
    return [{"package": name, "reason": f"motivo declarado para {name}"} for name in packages]


def _at_baseline() -> dict[str, PackageCoverage]:
    """Medicion identica a la linea base: debe pasar."""
    return {
        "app/services": _pkg(_SERVICES_PCT, _SERVICES_STMTS),
        "app/core": _pkg(_CORE_PCT, _CORE_STMTS),
    }


def _baseline_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "coverage_baseline.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _raw_baseline_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "coverage_baseline.json"
    path.write_text(text, encoding="utf-8")
    return path


def _valid_payload(**overrides) -> dict:
    payload = {
        "version": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "measurement": {"total": round(_TOTAL, 2), "statements": 8000},
        "policy": {"max_drop_points": 0.0},
        "exempt": [],
        "packages": {
            "app/services": {
                "coverage": _SERVICES_PCT,
                "statements": _SERVICES_STMTS,
                "max_drop_points": 0.0,
            },
            "app/core": {
                "coverage": _CORE_PCT,
                "statements": _CORE_STMTS,
                "max_drop_points": 0.0,
            },
        },
    }
    payload.update(overrides)
    return payload


def _load_from_dict(payload: dict) -> dict:
    """load_baseline() validando desde un dict, escribiendo a disco temporal."""
    with tempfile.TemporaryDirectory() as tmp:
        return gate.load_baseline(_baseline_file(Path(tmp), payload))


_load = _load_from_dict


# ------------------------------------------- 1. umbrales, no hardcodeados


def test_umbral_se_deriva_del_baseline_y_no_del_codigo():
    """Cambia el baseline, cambia el umbral. Si el umbral estuviera en el .py,
    este test no podria moverlo."""
    baseline = _load(_valid_payload())
    result = gate.evaluate(_at_baseline(), baseline)
    assert result.total_min == 67.0  # floor(67.13)

    baseline_bajo = _load(_valid_payload(measurement={"total": 12.0, "statements": 8000}))
    assert gate.evaluate(_at_baseline(), baseline_bajo).total_min == 12.0


def test_el_fuente_del_gate_no_tiene_porcentajes_magico():
    """Defensa estructural: ningun umbral puede Cocerse en el codigo.

    Se admiten los numeros de rounding/format y los sentinelas, pero un
    `fail_under = 63` o un `if total < 70` deben ser impossibles.
    """
    source = GATE_PATH.read_text(encoding="utf-8")
    offenders = re.findall(r"(?:fail_under|umbral|threshold)\s*=\s*(\d+(?:\.\d+)?)", source)
    assert not offenders, f"hay umbrales literales en el codigo del gate: {offenders}"


def test_el_baseline_versionado_del_repo_es_utilizable():
    """El baseline commiteado tiene que pasar la validacion estricta."""
    baseline = gate.load_baseline(ENGINE_ROOT / "coverage_baseline.json")
    assert baseline["packages"], "el baseline del repo declara al menos un paquete"


# ------------------------------------------------- 2. delta negativo => falla


def test_caida_de_un_paquete_falla_con_nombre_y_puntos():
    baseline = _load(_valid_payload())
    measured = _at_baseline()
    measured["app/services"] = _pkg(66.0, _SERVICES_STMTS)
    result = gate.evaluate(measured, baseline)

    assert not result.ok
    regression = [v for v in result.violations if v.kind == "regressed"]
    assert len(regression) == 1
    violation = regression[0]
    assert violation.subject == "app/services"
    # El mensaje tiene que decir el paquete y cuantos puntos, no solo "fail".
    assert "app/services" in violation.message
    assert "-5.00 pt" in violation.message
    assert "66.00%" in violation.message


def test_la_holgura_del_floor_absorbe_el_ruido_sin_dejar_caer():
    """Redondear a la baja regala hasta 1 punto: deliberado y acotado.

    Linea base 71.70 -> minimo 71. Medir 71.00 pasa (ruido de medicion);
    medir 70.90 ya falla, porque 70.90 < 71. El ratchet muerde igual.
    """
    payload = _valid_payload(
        packages={"app/services": {"coverage": 71.7, "statements": 6000, "max_drop_points": 0.0}},
        measurement={"total": 71.7, "statements": 6000},
    )
    baseline = _load(payload)
    assert gate.evaluate({"app/services": _pkg(71.0, 6000)}, baseline).ok
    caido = gate.evaluate({"app/services": _pkg(70.9, 6000)}, baseline)
    assert [v for v in caido.violations if v.kind == "regressed"]


def test_max_drop_points_amplia_la_holgura_de_un_paquete():
    payload = _valid_payload(
        packages={
            "app/services": {"coverage": 71.0, "statements": 6000, "max_drop_points": 2.0},
        },
        measurement={"total": 71.0, "statements": 6000},
    )
    baseline = _load(payload)
    # floor(71) - 2 = 69 -> 69.5 todavia pasa
    result = gate.evaluate({"app/services": _pkg(69.5, 6000)}, baseline)
    assert not [v for v in result.violations if v.kind == "regressed"]
    # 68.5 ya no
    result = gate.evaluate({"app/services": _pkg(68.5, 6000)}, baseline)
    assert [v for v in result.violations if v.kind == "regressed"]


def test_caida_global_falla_aunque_los_paquetes_esten_bien():
    """El total no se fia solo de los paquetes: detecta un baseline incoherente.

    Aqui el `total` del baseline (90) no cuadra con la media ponderada de sus
    propios paquetes (67.13). Todos los paquetes se miden exactamente en su linea
    base, asi que por paquete no hay nada que reprochar, pero el agregado no
    puede fingir que esta a 90. Es la red que caza un baseline editado a mano.
    """
    baseline = _load(_valid_payload(measurement={"total": 90.0, "statements": 8000}))
    result = gate.evaluate(_at_baseline(), baseline)
    assert not [v for v in result.violations if v.kind == "regressed"]
    assert any(v.kind == "global" for v in result.violations), [v.message for v in result.violations]


# ------------------------------ 3. delta positivo: pasa y actualiza el base


def test_subida_no_falla():
    baseline = _load(_valid_payload())
    measured = {
        "app/services": _pkg(88.0, _SERVICES_STMTS),
        "app/core": _pkg(74.0, _CORE_STMTS),
    }
    result = gate.evaluate(measured, baseline)
    assert result.ok, [v.message for v in result.violations]


def test_update_baseline_promociona_la_subida_y_el_gate_vuelve_a_pasar():
    """--update-baseline deja la subida como nueva linea base."""
    measured = {
        "app/services": _pkg(88.0, 6100),
        "app/core": _pkg(74.0, 2100),
    }
    payload = gate.render_baseline(measured, 0.0, [])
    total = 100.0 * sum(p.covered for p in measured.values()) / sum(p.total for p in measured.values())

    refreshed = _load(payload)
    result = gate.evaluate(measured, refreshed)
    assert result.ok, [v.message for v in result.violations]

    # Y la linea base guardada es la nueva, no la vieja.
    assert payload["packages"]["app/services"]["coverage"] == 88.0
    assert payload["measurement"]["total"] == pytest.approx(round(total, 2))
    assert payload["version"] == gate.BASELINE_VERSION


def test_baseline_guardado_y_total_gateado_no_pueden_separarse():
    """El total guardado usa la MISMA regla que el gate: sin exentos.

    Si divergieran, el gate compararia 84.07% contra un 81.49% guardado y
    'pasaria' sin que nadie supiera porque. Este test cierra esa puerta.
    """
    measured = dict(_at_baseline())
    measured["app/workers"] = _pkg(0.0, 5000)
    payload = gate.render_baseline(measured, 0.0, _exempt("app/workers"))
    baseline = _load(payload)

    assert payload["measurement"]["total"] == pytest.approx(_TOTAL, abs=0.01)
    result = gate.evaluate(measured, baseline)
    assert result.total == pytest.approx(payload["measurement"]["total"], abs=0.01)
    # Y el titular sin exentos se guarda aparte, para que no se pueda inflar.
    including = 100.0 * sum(p.covered for p in measured.values()) / sum(
        p.total for p in measured.values()
    )
    assert payload["measurement"]["total_including_exempt"] == pytest.approx(
        round(including, 2), abs=0.01
    )


def test_update_baseline_conserva_los_exempt():
    measured = _at_baseline()
    payload = gate.render_baseline(measured, 0.0, _exempt("app/llm"))
    assert [item["package"] for item in payload["exempt"]] == ["app/llm"]
    assert payload["exempt"][0]["reason"]


def test_una_exencion_sin_motivo_falla_cerrado():
    """Exentarse sin escribir por que es un hueco silencioso."""
    with pytest.raises(gate.GateConfigError, match="motivo escrito"):
        _load_from_dict(_valid_payload(exempt=[{"package": "app/llm"}]))
    with pytest.raises(gate.GateConfigError, match="motivo escrito"):
        _load_from_dict(_valid_payload(exempt=[{"package": "app/llm", "reason": "   "}]))
    with pytest.raises(gate.GateConfigError, match="'package' y 'reason'"):
        _load_from_dict(_valid_payload(exempt=["app/llm"]))


# ----------------------------------------------- 4. fail-closed en baseline


def test_baseline_ausente_falla_cerrado(tmp_path):
    with pytest.raises(gate.GateConfigError, match="no existe el baseline"):
        gate.load_baseline(tmp_path / "no-existe.json")


def test_baseline_corrupto_falla_cerrado(tmp_path):
    """JSON roto de verdad (no un JSON valido con el tipo equivocado)."""
    with pytest.raises(gate.GateConfigError, match="no se puede leer"):
        gate.load_baseline(_raw_baseline_file(tmp_path, "{no es json"))


def test_baseline_que_no_es_objeto_falla_cerrado(tmp_path):
    with pytest.raises(gate.GateConfigError, match="objeto JSON"):
        gate.load_baseline(_raw_baseline_file(tmp_path, '["una", "lista"]'))


@pytest.mark.parametrize(
    ("payload", "motivo"),
    [
        ({"version": 1}, "objeto 'measurement'"),
        ({"version": 99, "measurement": {}, "policy": {}, "packages": {}}, "version de baseline"),
        (_valid_payload(packages={}), "esta vacio"),
    ],
)
def test_baseline_corrupto_falla_cerrado(payload, motivo):
    with pytest.raises(gate.GateConfigError, match=motivo):
        _load_from_dict(payload)


@pytest.mark.parametrize(
    ("packages", "motivo"),
    [
        ({"app/services": {"statements": 10}}, "falta 'coverage'"),
        ({"app/services": {"coverage": "alta"}}, "se esperaba un numero"),
        ({"app/services": {"coverage": 150.0}}, "fuera de rango"),
        ({"app/services": {"coverage": 10.0, "coverage_pct": 10.0}}, "claves desconocidas"),
    ],
)
def test_entrada_de_baseline_invalida_falla_cerrado(packages, motivo):
    with pytest.raises(gate.GateConfigError, match=motivo):
        _load_from_dict(_valid_payload(packages=packages))


def test_clave_desconocida_en_el_baseline_falla_cerrado():
    """Un typo en 'packages' no puede pasar por cobertura legitima."""
    payload = _valid_payload()
    payload["packges"] = payload.pop("packages")
    with pytest.raises(gate.GateConfigError, match="claves desconocidas"):
        _load_from_dict(payload)


# --------------------------------------------- 5. paquete nuevo => fail-closed


def test_paquete_nuevo_sin_baseline_se_rechaza():
    baseline = _load(_valid_payload())
    measured = dict(_at_baseline())
    measured["app/workers"] = _pkg(99.0)
    result = gate.evaluate(measured, baseline)

    assert not result.ok
    undeclared = [v for v in result.violations if v.kind == "undeclared"]
    assert len(undeclared) == 1
    assert undeclared[0].subject == "app/workers"
    assert "exempt" in undeclared[0].message


def test_paquete_nuevo_explicitamente_exempt_pasa():
    """Declarar `exempt` es la via de escape, y es explicita y versionada.

    El paquete exento tampoco cuenta para el agregado: si contara, un paquete al
    0% marcado como exempt seguiria tumbando el total y el gate no dejaria de
    quejarse nunca, que es justo lo que `exempt` debe evitar.
    """
    baseline = _load(_valid_payload(exempt=_exempt("app/workers")))
    measured = dict(_at_baseline())
    measured["app/workers"] = _pkg(0.0, 5000)
    result = gate.evaluate(measured, baseline)
    assert result.ok, [v.message for v in result.violations]
    assert ("app/workers", None, 0.0, None, None, "exempt") in result.rows
    # Y el agregado no se ha enterado del paquete exento.
    assert result.total == pytest.approx(_TOTAL, abs=0.01)
    # Pero el informe dice cuanto seria si se gateara tambien.
    including = 100.0 * sum(p.covered for p in measured.values()) / sum(
        p.total for p in measured.values()
    )
    assert result.total_including_exempt == pytest.approx(including, abs=0.01)
    text = gate.format_report(result, title="t", exempt=baseline.get("exempt", []))
    assert f"{result.total_including_exempt:.2f}" in text


def test_paquete_del_baseline_que_no_se_mide_falla_cerrado():
    """Paquete borrado o medicion rota: en los dos casos hay que decidir."""
    baseline = _load(_valid_payload())
    result = gate.evaluate({"app/services": _pkg(_SERVICES_PCT, _SERVICES_STMTS)}, baseline)
    assert not result.ok
    stale = [v for v in result.violations if v.kind == "stale"]
    assert stale and stale[0].subject == "app/core"
    assert "--update-baseline" in stale[0].message


def test_informe_sin_ficheros_falla_cerrado():
    with pytest.raises(gate.GateConfigError, match="clave 'files'"):
        gate.aggregate_by_package({"totals": {}})


def test_fichero_sin_summary_falla_cerrado():
    with pytest.raises(gate.GateConfigError, match="summary"):
        gate.aggregate_by_package({"files": {"app/core/config.py": {}}})


# ------------------------------------------- 6. agregacion y atribucion


def test_package_of_gana_el_prefijo_mas_largo():
    assert gate.package_of("app/valuation/engines/dcf.py") == "app/valuation/engines"
    assert gate.package_of("app/valuation/wacc.py") == "app/valuation"
    assert gate.package_of("app/api/routes/market.py") == "app/api/routes"
    assert gate.package_of("app/api/router.py") == "app/api"
    assert gate.package_of("alembic/versions/0031_x.py") == "alembic"
    assert gate.package_of("app/services\\deep\\mod.py") == "app/services"


def test_package_of_manda_a_other_lo_desconocido():
    """Lo que no casa con ningun prefijo acaba en `other`, que el gate marca."""
    assert gate.package_of("evals/gates.py") == gate.CATCH_ALL
    assert gate.package_of("scripts/run_coverage_gate.py") == gate.CATCH_ALL


def test_aggregate_pondera_por_sentencias_no_por_media_de_porcentajes():
    """Un fichero de 3 lineas al 100 % no debe igualar a uno de 20 000 al 10 %."""
    report = {
        "files": {
            "app/services/tiny.py": {
                "summary": {"covered_lines": 3, "num_statements": 3}
            },
            "app/services/huge.py": {
                "summary": {"covered_lines": 2000, "num_statements": 20000}
            },
        }
    }
    packages = gate.aggregate_by_package(report)
    bucket = packages["app/services"]
    assert bucket.total == 20003
    # Media de porcentajes: (100 + 10) / 2 = 55. Ponderado: ~10 %.
    assert bucket.percent == pytest.approx(100.0 * 2003 / 20003, abs=0.01)


def test_aggregate_normaliza_barras_windows_y_dot_slash():
    report = {
        "files": {
            "./app\\core\\config.py": {"summary": {"covered_lines": 5, "num_statements": 10}}
        }
    }
    assert "app/core" in gate.aggregate_by_package(report)


# ------------------------------------------------- 7. formato del informe


def test_format_report_es_una_lista_legible_de_paquetes_y_puntos():
    baseline = _load(_valid_payload())
    measured = _at_baseline()
    measured["app/services"] = _pkg(66.0, _SERVICES_STMTS)
    result = gate.evaluate(measured, baseline)
    text = gate.format_report(result, title="Informe de prueba")

    for expected in (
        "paquete",
        "app/services",
        "app/core",
        "TOTAL",
        "base",
        "actual",
        "delta",
        "minimo",
    ):
        assert expected in text, f"falta {expected!r} en el informe"
    # Los puntos tienen que ser legibles, con signo y con 2 decimales.
    assert "-5.00" in text
    assert re.search(r"app/services\s+71\.00\s+66\.00\s+-5\.00\s+71\.00", text), text
    assert "GATE FALLIDO" in text
    assert "regressed" in text


def test_format_report_anuncia_paso_cuando_no_hay_violaciones():
    baseline = _load(_valid_payload())
    result = gate.evaluate(_at_baseline(), baseline)
    text = gate.format_report(result, title="Informe de prueba")
    assert "GATE OK" in text
    assert "PASS" in text


def test_format_report_marca_paquetes_sin_baseline_y_exempt():
    baseline = _load(_valid_payload(exempt=_exempt("app/workers")))
    measured = dict(_at_baseline())
    measured["app/workers"] = _pkg(12.0)
    measured["app/nuevo"] = _pkg(50.0)
    result = gate.evaluate(measured, baseline)
    text = gate.format_report(
        result, title="Informe de prueba", exempt=baseline.get("exempt", [])
    )
    assert "exempt" in text
    assert "undeclared" in text
    assert "FAIL" in text
    # El motivo de la exencion sale en el informe, no se queda en el JSON.
    assert "motivo declarado para app/workers" in text


# --------------------------- 7. red anti-skips silenciosos del carril de colas


_JUNIT_CON_SKIP = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3" skipped="1">
  <testcase classname="tests.test_queue_watchdog" name="test_mide_profundidad">
    <skipped message="could not import 'fakeredis'">skip</skipped>
  </testcase>
  <testcase classname="tests.test_queue_watchdog" name="test_otro"/>
  <testcase classname="tests.test_provider_lanes" name="test_ajeno">
    <skipped message="skip ajeno al carril">skip</skipped>
  </testcase>
</testsuite>
"""


def test_skip_guard_caza_el_skip_silencioso_del_carril(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(_JUNIT_CON_SKIP, encoding="utf-8")
    failures = gate.skipped_guard_failures(junit)
    assert failures == ["tests.test_queue_watchdog::test_mide_profundidad"]


def test_skip_guard_ignora_skips_fuera_de_la_lista(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0"?>
<testsuite><testcase classname="tests.test_provider_lanes" name="t">
<skipped message="x">s</skipped></testcase></testsuite>""",
        encoding="utf-8",
    )
    assert gate.skipped_guard_failures(junit) == []


def test_skip_guard_falla_cerrado_sin_junit(tmp_path):
    with pytest.raises(gate.GateConfigError):
        gate.skipped_guard_failures(tmp_path / "no-existe.xml")


def test_el_gate_escribe_junit_para_la_red():
    """Sin --junitxml en el comando, la red no tiene de donde leer."""
    cmd = gate._pytest_command(extra=None)
    assert any(arg.startswith("--junitxml=") for arg in cmd)


def test_skip_guard_caza_classname_con_clase(tmp_path):
    """pytest escribe tests.modulo.Clase::test cuando el test vive en una
    clase: el guard no puede depender de que el classname sea el modulo."""
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0"?>
<testsuite><testcase classname="tests.test_queue_watchdog.TestWatchdog" name="t">
<skipped message="x">s</skipped></testcase></testsuite>""",
        encoding="utf-8",
    )
    assert gate.skipped_guard_failures(junit) == ["tests.test_queue_watchdog.TestWatchdog::t"]


def test_skip_guard_no_confunde_modulos_con_prefijo_comun(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0"?>
<testsuite><testcase classname="tests.test_queue_watchdog_extra" name="t">
<skipped message="x">s</skipped></testcase></testsuite>""",
        encoding="utf-8",
    )
    assert gate.skipped_guard_failures(junit) == []


def test_skip_guard_rechaza_xml_que_no_es_junit(tmp_path):
    """Un XML valido pero ajeno (un HTML, un coverage.xml) no puede pasar
    por 'sin skips': la corrida no es fiable y el gate falla."""
    junit = tmp_path / "junit.xml"
    junit.write_text("<html><body>no soy junit</body></html>", encoding="utf-8")
    with pytest.raises(gate.GateConfigError):
        gate.skipped_guard_failures(junit)


def test_skip_guard_acepta_raiz_testsuites(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0"?>
<testsuites><testsuite><testcase classname="tests.test_ingest_load_lab" name="t">
<skipped message="x">s</skipped></testcase></testsuite></testsuites>""",
        encoding="utf-8",
    )
    assert gate.skipped_guard_failures(junit) == ["tests.test_ingest_load_lab::t"]


def test_la_corrida_borra_el_junit_previo(monkeypatch, tmp_path):
    """Sin borrado previo, una corrida muerta dejaria al guard leyendo los
    skips de ayer."""
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")
    monkeypatch.setattr(gate, "JUNIT_REPORT", junit)
    visto = {}

    def fake_call(cmd, cwd=None):
        visto["existia_al_lanzar_pytest"] = junit.exists()
        junit.write_text("<testsuite/>", encoding="utf-8")  # pytest lo reescribe
        return 0

    monkeypatch.setattr("subprocess.call", fake_call)
    assert gate.run_pytest(extra=None) == 0
    assert visto["existia_al_lanzar_pytest"] is False


def test_skip_guard_funciona_con_junit_con_namespace(tmp_path):
    """Un JUnit con namespace ({ns}testcase/{ns}skipped) no esconde skips:
    raiz, testcase y skipped se comparan por nombre local."""
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0"?>
<testsuite xmlns="urn:junit">
  <testcase classname="tests.test_queue_watchdog" name="t">
    <skipped message="x">s</skipped>
  </testcase>
</testsuite>""",
        encoding="utf-8",
    )
    assert gate.skipped_guard_failures(junit) == ["tests.test_queue_watchdog::t"]


def test_los_ficheros_vigilados_por_el_guard_existen_y_siguen_pudiendo_saltar():
    """SKIP_GUARD_FILES es hardcodeada: si un fichero se renombra o deja de
    tener skips opt-in, la red vigila un fantasma y nadie avisa."""
    for rel in gate.SKIP_GUARD_FILES:
        path = ENGINE_ROOT / rel
        assert path.is_file(), f"fichero vigilado inexistente (renombrado?): {rel}"
        assert "importorskip(" in path.read_text(encoding="utf-8"), (
            f"{rel} ya no tiene skips opt-in: sacarlo de SKIP_GUARD_FILES a proposito"
        )
