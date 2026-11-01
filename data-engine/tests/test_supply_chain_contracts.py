"""Contratos de la cadena de suministro de imagenes (tarea E3).

El workflow `.github/workflows/sbom-scan.yml` se audita por *parseo del YAML*, no
por ejecucion: lo que se verifica es que las puertas existen, que estan donde
tienen que estar y que no se pueden desactivar sin que un test se ponga rojo.

La segunda mitad del fichero mete informes sinteticos en
`scripts.security.gate_image_scan` (el modulo que decide rojo/verde en el
workflow) y comprueba la politica:

    CVE CRITICAL con fix .... rojo
    secret (cualquier sev) . rojo
    misconfig HIGH/CRIT .... rojo
    HIGH/MEDIUM ............ se reportan, no bloquean
    escaner que no corrio ... rojo (fail-closed)
    excepcion caducada ..... rojo (no se ignora en silencio)

Y la tercera mitad comprueba que los dos `.dockerignore` dejan fuera el `.env`,
el `.venv` y `node_modules` del contexto de build, que es donde un secreto se
convierte en un secreto *publicado* (esta en la historia de la imagen aunque
despues se borre el fichero).
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.security.dockerignore import (
    DEFAULT_FORBIDDEN_DIRS,
    DEFAULT_FORBIDDEN_GLOBS,
    is_excluded,
    leaked,
    read_patterns,
)
from scripts.security.gate_image_scan import (
    CRITICAL,
    GateError,
    evaluate,
    load_policy,
    load_report,
    main,
)

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "sbom-scan.yml"
POLICY = REPO / "scripts" / "security" / "trivy-policy.yaml"
DOCKERIGNORE_ROOT = REPO / ".dockerignore"
DOCKERIGNORE_ENGINE = REPO / "data-engine" / ".dockerignore"

EXPECTED_IMAGES = {
    ("frontend-prod", ".", "Dockerfile"),
    ("frontend-dev", ".", "Dockerfile.dev"),
    ("backend-prod", "data-engine", "data-engine/Dockerfile.prod"),
    ("backend-dev", "data-engine", "data-engine/Dockerfile"),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job(name: str) -> dict:
    return _workflow()["jobs"][name]


def _steps(name: str) -> list[dict]:
    return _job(name)["steps"]


def _matrix(name: str) -> set[tuple[str, str, str]]:
    entries = _job(name)["strategy"]["matrix"]["include"]
    return {(entry["name"], entry["context"], entry["file"]) for entry in entries}


def _using(steps: list[dict], action: str) -> list[dict]:
    return [step for step in steps if str(step.get("uses", "")).startswith(action)]


def _vulns(*findings: dict) -> dict:
    return {"Results": [{"Target": "cavaai/backend-prod (python)", "Vulnerabilities": list(findings)}]}


def _secret_report(*findings: dict) -> dict:
    return {"Results": [{"Target": "cavaai/backend-prod (python)", "Secrets": list(findings)}]}


def _misconfigs(*findings: dict) -> dict:
    return {"Results": [{"Target": "Dockerfile", "Misconfigurations": list(findings)}]}


def _cve(severity: str, fixed: str = "", identifier: str = "CVE-2026-0001") -> dict:
    return {
        "VulnerabilityID": identifier,
        "PkgName": "libssl3",
        "InstalledVersion": "3.1.4-r0",
        "FixedVersion": fixed,
        "Severity": severity,
        "Title": "algo",
    }


def _secret(severity: str = "LOW") -> dict:
    return {"RuleID": "generic-api-key", "Category": "General", "Severity": severity, "Title": "key"}


def _misconfig(severity: str, identifier: str = "DS-0002") -> dict:
    return {"ID": identifier, "AVDID": "AVD-DS-0002", "Severity": severity, "Title": "algo"}


def _reports(tmp_path: Path, **payloads: dict) -> list:
    """Materializa informes trivy en disco y los carga con el cargador real."""
    loaded = []
    kinds = {
        "vuln": ("vulnerability", "trivy"),
        "secret": ("secret", "trivy"),
        "misconfig": ("misconfig", "trivy"),
        "second": ("vulnerability", "anchore-scan"),
    }
    for slot, payload in payloads.items():
        path = tmp_path / f"{slot}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        kind, engine = kinds[slot]
        loaded.append(load_report(path, kind, engine))
    return loaded


def _gate(reports: list, *, build_result: str = "success", exceptions: list | None = None) -> Any:
    return evaluate(
        image="backend-prod",
        image_ref="cavaai/backend-prod:test",
        build_result=build_result,
        reports=reports,
        exceptions=exceptions or [],
        policy_errors=[],
    )


# ---------------------------------------------------------------------------
# (a) el workflow construye las 4 imagenes
# ---------------------------------------------------------------------------


def test_el_workflow_construye_las_cuatro_imagenes():
    assert _matrix("build") == EXPECTED_IMAGES


def test_toda_clave_matrix_usada_existe_en_el_include():
    """Una expresion `matrix.X` sin clave X en el include se evalua a vacio:
    tags y nombres en blanco y el build de las imagenes roto sin avisar."""
    import re

    text = WORKFLOW.read_text(encoding="utf-8")
    for job in ("build", "sbom", "scan"):
        keys = set(_job(job)["strategy"]["matrix"]["include"][0])
        for entry in _job(job)["strategy"]["matrix"]["include"]:
            assert set(entry) == keys, f"{job}: entradas con claves distintas"
    used = set(re.findall(r"matrix\.([A-Za-z_][A-Za-z0-9_]*)", text))
    assert used, "el workflow no usa la matriz"
    for job in ("build", "sbom", "scan"):
        declared = set(_job(job)["strategy"]["matrix"]["include"][0])
        job_text = yaml.safe_dump(_job(job))
        job_used = set(re.findall(r"matrix\.([A-Za-z_][A-Za-z0-9_]*)", job_text))
        assert job_used <= declared, f"{job}: matrix.{sorted(job_used - declared)} no existe en el include"


def test_las_tres_matrices_declaran_las_mismas_imagenes():
    """Una imagen que se construye y no se escanea es una imagen sin escaneo."""
    assert _matrix("sbom") == _matrix("build")
    assert _matrix("scan") == _matrix("build")


def test_el_build_no_depende_de_ningun_secreto_externo():
    """Sin secrets de Vercel ni Docker Hub: GITHUB_TOKEN ya viene siempre."""
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in texto
    for step in _steps("build") + _steps("sbom") + _steps("engine2") + _steps("scan"):
        assert "secrets." not in json.dumps(step)


def test_el_build_no_fija_push_a_ningun_registry():
    """Sin registry no hay attestations de buildx, pero tampoco se depende de uno."""
    for step in _using(_steps("build"), "docker/build-push-action"):
        with_ = step.get("with", {})
        assert with_.get("push") is False
        assert with_.get("load") is True


# ---------------------------------------------------------------------------
# (b) los SBOM se suben aunque el build falle
# ---------------------------------------------------------------------------


def test_el_job_sbom_corre_aunque_el_build_falle():
    assert "always()" in str(_job("sbom").get("if"))
    assert "always()" in str(_job("scan").get("if"))


def test_toda_subida_de_sbom_ocurre_siempre():
    uploads = _using(_steps("sbom"), "actions/upload-artifact")
    assert len(uploads) >= 2, "se esperan CycloneDX y SPDX"
    for step in uploads:
        assert "always()" in str(step.get("if")), f"subida sin if: always(): {step.get('name')}"


def test_el_sbom_se_genera_en_cyclonedx_y_spdx():
    formats = {step["with"]["format"] for step in _using(_steps("sbom"), "anchore/sbom-action")}
    assert formats == {"cyclonedx-json", "spdx-json"}


def test_la_subida_de_sbom_no_depende_de_la_subida_interna_de_la_action():
    """Si la action falla, su subida tampoco existe: por eso la hacemos nosotros."""
    for step in _using(_steps("sbom"), "anchore/sbom-action"):
        assert step["with"]["upload-artifact"] is False


# ---------------------------------------------------------------------------
# (c)(d)(e)(f) las puertas
# ---------------------------------------------------------------------------


def test_la_puerta_corre_siempre_y_es_el_unico_veredicto():
    gates = [step for step in _steps("scan") if "gate_image_scan.py" in str(step.get("run", ""))]
    assert len(gates) == 1, "un unico punto de decision"
    assert "always()" in str(gates[0].get("if"))


def test_ningun_paso_tiene_continue_on_error():
    for job in ("build", "sbom", "scan"):
        for step in _steps(job):
            assert not step.get("continue-on-error"), f"{job}: {step.get('name')}"


def test_los_escáneres_no_deciden_el_veredicto_por_su_cuenta():
    """exit-code != 0 en trivy o fail-build en anchore = puerta que se puede
    desactivar desde el YAML, que es justo lo que este workflow no permite."""
    for step in _using(_steps("scan"), "aquasecurity/trivy-action"):
        assert str(step["with"]["exit-code"]) == "0", step.get("name")
    for step in _using(_steps("engine2"), "anchore/scan-action"):
        assert step["with"]["fail-build"] is False


def test_se_escanean_vulnerabilidades_secrets_y_misconfiguration():
    scanners = {
        str(step["with"]["scanners"])
        for step in _using(_steps("scan"), "aquasecurity/trivy-action")
    }
    assert any("vuln" in entry for entry in scanners)
    assert any("secret" in entry for entry in scanners)
    assert any("misconfig" in entry for entry in scanners)


def test_hay_dos_motores_independientes():
    trivy = _using(_steps("scan"), "aquasecurity/trivy-action")
    anchore = _using(_steps("engine2"), "anchore/scan-action")
    assert trivy and anchore
    # el motor 2 consume el SBOM del job sbom, no la imagen: dos motores sobre el
    # mismo contenido
    assert anchore[0]["with"]["sbom"].endswith(".cdx.json")
    downloads = _using(_steps("engine2"), "actions/download-artifact")
    assert any("sbom-" in str(step["with"]["name"]) for step in downloads)


def anchore_sbom_apunta_a_la_copia_limpia() -> bool:
    anchore = _using(_steps("engine2"), "anchore/scan-action")
    return bool(anchore) and str(anchore[0]["with"]["sbom"]).endswith(".grype.cdx.json")


def test_el_motor_2_corre_en_su_propio_job_y_su_caida_es_rojo_para_el_gate():
    """grype dentro del job scan mato el runner de backend-prod (4 intentos).
    Vive en el job engine2; si ese job muere no sube artefacto y el gate recibe
    "missing", que es distinto de success (escaneo incompleto, rojo)."""
    workflow = _workflow()
    assert "engine2" in workflow["jobs"]
    assert "engine2" in workflow["jobs"]["scan"]["needs"]
    assert not _using(_steps("scan"), "anchore/scan-action")
    recogida = next(step for step in _steps("scan") if step.get("id") == "engine2_result")
    assert "status=missing" in str(recogida["run"])
    assert "steps.engine2_result.outputs.status" in str(_gate_step()["run"])
    # grype se cuelga con el componente machine-learning-model de backend-prod
    # (reproducido): la copia que lee grype se limpia antes del escaneo.
    limpieza = next(step for step in _steps("engine2") if "machine-learning-model" in str(step.get("run", "")))
    assert ".grype.cdx.json" in str(limpieza["run"])
    assert anchore_sbom_apunta_a_la_copia_limpia()
    subida = _using(_steps("engine2"), "actions/upload-artifact")
    assert subida and str(subida[0].get("if", "")).strip() in {"${{ always() }}", "always()"}


def test_la_misconfiguration_se_evalua_sobre_los_dockerfiles_y_el_compose():
    for step in _using(_steps("scan"), "aquasecurity/trivy-action"):
        if "misconfig" in str(step["with"]["scanners"]):
            assert step["with"]["scan-type"] == "config"
            assert step["with"]["scan-ref"] == "."


def test_la_puerta_recibe_el_resultado_del_build_y_el_outcome_de_cada_escaner():
    """fail-closed: "no lo he podido comprobar" tiene que llegar al gate."""
    run = str(_gate_step()["run"])
    # El resultado del build es POR IMAGEN: needs.build.result es el
    # agregado de la matriz y una imagen rota marcaba las cuatro
    # (30-oct-2026, run 41005146082). El paso build_result lo deriva del
    # artefacto digest-<imagen>, que solo existe si ESE build fue bien. Si no
    # dejara salida, el gate recibiria "" (!= "success") y saldria ROJO:
    # vacio nunca se lee como "success".
    assert '--build-result "${{ steps.build_result.outputs.result }}"' in run
    descarga_digest = [
        step
        for step in _steps("scan")
        if "download-artifact" in str(step.get("uses", ""))
        and str(step.get("with", {}).get("pattern", "")) == "digest-${{ matrix.name }}"
    ]
    assert descarga_digest, "el scan deriva el build de su propia imagen del artefacto digest"
    paso_resultado = next(step for step in _steps("scan") if step.get("id") == "build_result")
    assert 'digests/${{ matrix.name }}.tsv' in str(paso_resultado["run"])
    fuentes = {
        "vuln": "steps.trivy_vuln.outcome",
        "secret": "steps.trivy_secret.outcome",
        "misconfig": "steps.trivy_misconfig.outcome",
        "second": "steps.engine2_result.outputs.status",
    }
    for slot, fuente in fuentes.items():
        assert f'--{slot}-status "${{{{ {fuente} || \'skipped\' }}}}"' in run
        assert f"--{slot}-report" in run


def _gate_step() -> dict:
    return next(step for step in _steps("scan") if "gate_image_scan.py" in str(step.get("run", "")))


def test_triggers_concurrency_y_timeouts():
    workflow = _workflow()
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers
    # La evidencia publicada (SBOMs e informes de escaneo) no se cancela en
    # push: cancel solo en pull_request, mismo criterio que coverage.yml y
    # llm-evals.yml (FIX-3.6).
    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    for job in ("build", "sbom", "scan"):
        timeout = _job(job)["timeout-minutes"]
        assert 20 <= timeout <= 60, f"{job}: {timeout} min no es realista para 4 imagenes"


def test_la_politica_de_excepciones_es_un_fichero_versionado():
    assert POLICY.is_file()
    assert "scripts/security/trivy-policy.yaml" in _gate_step()["run"]
    for job in ("build", "sbom", "scan"):
        for step in _steps(job):
            # ni `.trivyignore` ni un `--ignore`/`severity` colgado del YAML: la
            # unica lista de excepciones es el fichero con ticket y caducidad.
            with_ = step.get("with", {})
            assert "trivyignores" not in with_
            assert not any("--ignore" in str(value) for value in with_.values())
    assert not (REPO / ".trivyignore").exists()


# ---------------------------------------------------------------------------
# (c) CVE CRITICAL con fix -> rojo
# ---------------------------------------------------------------------------


def test_cve_critical_con_fix_es_rojo(tmp_path):
    reports = _reports(tmp_path, vuln=_vulns(_cve(CRITICAL, fixed="3.1.5-r0")))
    gate = _gate(reports)
    assert not gate.passed
    assert "CVE-2026-0001" in " ".join(gate.blocks)


def test_cve_critical_sin_fix_no_rojo_pero_se_reporta(tmp_path):
    """Sin parche no hay nada que arreglar hoy: se reporta, no se bloquea."""
    reports = _reports(tmp_path, vuln=_vulns(_cve(CRITICAL, fixed="")))
    gate = _gate(reports)
    assert gate.passed
    assert gate.counts["trivy:vulnerability:CRITICAL"] == 1
    assert any("CRITICAL=1" in note for note in gate.notes)


def test_cve_high_no_rojo_pero_se_reporta(tmp_path):
    reports = _reports(tmp_path, vuln=_vulns(_cve("HIGH", fixed="3.1.5-r0")))
    gate = _gate(reports)
    assert gate.passed
    assert gate.counts["trivy:vulnerability:HIGH"] == 1


def test_cve_alto_se_reporta_en_el_log_del_job(tmp_path):
    """El numero se ve en el run: sin eso, 'no bloquea' se lee como 'no se ve'."""
    reports = _reports(tmp_path, vuln=_vulns(_cve("HIGH", fixed="3.1.5-r0")))
    gate = _gate(reports)
    assert gate.passed
    assert any("HIGH=1" in note for note in gate.notes)


# ---------------------------------------------------------------------------
# (d) secret -> rojo en cualquier severidad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("severity", ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"])
def test_un_secret_rojo_a_cualquier_severidad(tmp_path, severity):
    reports = _reports(tmp_path, secret=_secret_report(_secret(severity)))
    gate = _gate(reports)
    assert not gate.passed, f"un secret {severity} no puede pasar"
    assert "generic-api-key" in " ".join(gate.blocks)


# ---------------------------------------------------------------------------
# misconfiguration -> rojo en HIGH/CRITICAL
# ---------------------------------------------------------------------------


def test_misconfig_alta_es_rojo(tmp_path):
    reports = _reports(tmp_path, misconfig=_misconfigs(_misconfig("HIGH")))
    assert not _gate(reports).passed


def test_misconfig_critica_es_rojo(tmp_path):
    reports = _reports(tmp_path, misconfig=_misconfigs(_misconfig("CRITICAL")))
    assert not _gate(reports).passed


def test_misconfig_media_se_reporta_pero_no_rojo(tmp_path):
    reports = _reports(tmp_path, misconfig=_misconfigs(_misconfig("MEDIUM")))
    gate = _gate(reports)
    assert gate.passed
    assert any("MEDIUM=1" in note for note in gate.notes)


# ---------------------------------------------------------------------------
# (e) fail-closed
# ---------------------------------------------------------------------------


def test_build_roto_es_rojo_aunque_no_haya_hallazgos(tmp_path):
    reports = _reports(tmp_path, vuln=_vulns(), secret=_secret_report(), misconfig=_misconfigs())
    gate = _gate(reports, build_result="failure")
    assert not gate.passed
    assert any("fail-closed" in error for error in gate.errors)


def test_build_cancelado_es_rojo(tmp_path):
    reports = _reports(tmp_path, vuln=_vulns(), secret=_secret_report(), misconfig=_misconfigs())
    assert not _gate(reports, build_result="cancelled").passed


def test_informe_ausente_es_rojo(tmp_path):
    with pytest.raises(GateError):
        load_report(tmp_path / "no-existe.json", "vulnerability", "trivy")


def test_informe_corrupto_es_rojo(tmp_path):
    path = tmp_path / "roto.json"
    path.write_text("{no json", encoding="utf-8")
    with pytest.raises(GateError):
        load_report(path, "vulnerability", "trivy")


def test_la_cli_sale_en_rojo_si_falta_un_informe(tmp_path, capsys):
    """El camino que de verdad ejecuta el workflow: la CLI, no la funcion."""
    exit_code = main(
        [
            "--image", "frontend-dev",
            "--build-result", "success",
            "--policy", str(POLICY),
            "--vuln-report", str(_write(tmp_path / "vuln.json", _vulns(_cve("LOW")))),
            "--misconfig-report", str(_write(tmp_path / "mis.json", _misconfigs())),
        ]
    )
    assert exit_code == 1
    assert "ROJO" in capsys.readouterr().out


def _write(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_la_cli_sale_en_verde_solo_con_los_cuatro_informes_y_sin_hallazgos(tmp_path, capsys):
    exit_code = main(
        [
            "--image", "frontend-dev",
            "--build-result", "success",
            "--policy", str(POLICY),
            "--vuln-report", str(_write(tmp_path / "vuln.json", _vulns(_cve("MEDIUM")))),
            "--secret-report", str(_write(tmp_path / "sec.json", _secret_report())),
            "--misconfig-report", str(_write(tmp_path / "mis.json", _misconfigs(_misconfig("LOW")))),
            "--second-report", str(_write(tmp_path / "second.json", {"matches": []})),
            "--summary", str(tmp_path / "summary.json"),
        ]
    )
    assert exit_code == 0
    assert "VERDE" in capsys.readouterr().out
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["passed"] is True


# ---------------------------------------------------------------------------
# (g) las excepciones caducan
# ---------------------------------------------------------------------------


def _write_policy(path: Path, exceptions: list[dict]) -> Path:
    path.write_text(yaml.safe_dump({"version": 1, "exceptions": exceptions}), encoding="utf-8")
    return path


_ENTRY = {
    "id": "CVE-2026-0001",
    "scope": "vulnerability",
    "targets": ["backend-prod"],
    "reason": "sin ruta de codigo afectada, upstream avisado",
    "ticket": "SEC-1",
    "expires": "2099-12-31",
}


def test_una_excepcion_valida_cubre_su_hallazgo(tmp_path):
    reports = _reports(tmp_path, vuln=_vulns(_cve(CRITICAL, fixed="3.1.5-r0")))
    entries, errors = load_policy(_write_policy(tmp_path / "p.yaml", [_ENTRY]), date(2026, 10, 2))
    assert not errors
    gate = _gate(reports, exceptions=entries)
    assert gate.passed
    assert any("trivy-policy.yaml" in note for note in gate.notes)


def test_una_excepcion_no_cubre_otra_imagen(tmp_path):
    reports = _reports(tmp_path, vuln=_vulns(_cve(CRITICAL, fixed="3.1.5-r0")))
    entries, errors = load_policy(_write_policy(tmp_path / "p.yaml", [_ENTRY]), date(2026, 10, 2))
    assert not errors
    gate = evaluate(
        image="backend-dev",
        build_result="success",
        reports=reports,
        exceptions=entries,
        policy_errors=[],
    )
    assert not gate.passed


def test_una_excepcion_vencida_es_rojo(tmp_path):
    vencida = {**_ENTRY, "expires": (date.today() - timedelta(days=1)).isoformat()}
    _, errors = load_policy(_write_policy(tmp_path / "p.yaml", [vencida]), date.today())
    assert errors and "caducada" in errors[0]
    gate = evaluate(
        image="backend-prod",
        build_result="success",
        reports=[],
        exceptions=[],
        policy_errors=errors,
    )
    assert not gate.passed


def test_una_excepcion_sin_fecha_es_rojo(tmp_path):
    sin_fecha = {key: value for key, value in _ENTRY.items() if key != "expires"}
    _, errors = load_policy(_write_policy(tmp_path / "p.yaml", [sin_fecha]), date.today())
    assert errors and "expires" in errors[0]


@pytest.mark.parametrize("campo", ["reason", "ticket", "id", "scope"])
def test_una_excepcion_sin_motivo_ticket_o_id_es_rojo(tmp_path, campo):
    entrada = {key: value for key, value in _ENTRY.items() if key != campo}
    _, errors = load_policy(_write_policy(tmp_path / "p.yaml", [entrada]), date.today())
    assert errors and campo in errors[0]


def test_una_excepcion_con_scope_inventado_es_rojo(tmp_path):
    _, errors = load_policy(
        _write_policy(tmp_path / "p.yaml", [{**_ENTRY, "scope": "todo"}]), date.today()
    )
    assert errors and "scope" in errors[0]


def test_la_politica_versionada_cumple_sus_propias_reglas():
    """El fichero real de excepciones tiene que pasar la misma politica."""
    entries, errors = load_policy(POLICY, date.today())
    assert not errors, errors
    assert isinstance(entries, list)
    for entry in entries:
        assert entry.reason and entry.ticket and entry.expires
        assert entry.expires >= date.today()


def test_la_politica_no_puede_faltar(tmp_path):
    with pytest.raises(GateError):
        load_policy(tmp_path / "no-existe.yaml", date.today())


def test_la_excepcion_esta_versionada_y_no_inline():
    """Mismo contrato por el otro lado: el fichero existe y esta en git-ready."""
    assert POLICY.is_file()
    assert not list(REPO.glob("**/.trivyignore"))


# ---------------------------------------------------------------------------
# los .dockerignore no dejan pasar .env / .venv / node_modules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [".env", ".env.production", ".env.local", ".venv", ".venv/bin/activate"],
)
def test_el_contexto_raiz_no_lleva_env_ni_venv(path):
    assert is_excluded(path, read_patterns(DOCKERIGNORE_ROOT)), f"{path} entraria en la imagen"


@pytest.mark.parametrize("path", [
    "node_modules/react/index.js", "node_modules/.package-lock.json",
    "qa-e2e/node_modules/react/index.js", "nested/app/node_modules/.package-lock.json",
])
def test_el_contexto_raiz_no_lleva_node_modules(path):
    assert is_excluded(path, read_patterns(DOCKERIGNORE_ROOT)), f"{path} entraria en la imagen"


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        ".venv",
        ".venv/lib/python3.12/site-packages/uvicorn/__init__.py",
        "data/",
        "data/x.duckdb",
        "storage/analytics.duckdb",
    ],
)
def test_el_contexto_data_engine_no_lleva_env_ni_venv_ni_datos(path):
    assert is_excluded(path, read_patterns(DOCKERIGNORE_ENGINE)), f"{path} entraria en la imagen"


@pytest.mark.xfail(
    reason=(
        "Hallazgo de la auditoria E3: `COPY . .` en data-engine/Dockerfile.prod mete "
        "tests/ y evals/ (321 ficheros de test) en la imagen de produccion. El "
        ".dockerignore es compartido con el compose de desarrollo, que monta el "
        "arbol por volumen, asi que excluir tests/ no rompe el desarrollo. "
        "Arreglo en el PR de Dockerfiles (propiedad compartida)."
    ),
    strict=False,
)
def test_los_tests_no_deberian_entrar_en_la_imagen_de_produccion():
    assert is_excluded("tests/test_main.py", read_patterns(DOCKERIGNORE_ENGINE))


def test_no_hay_fugas_en_los_contextos_reales():
    """Recorre los dos contextos con los .dockerignore reales."""
    for contexto in (REPO, REPO / "data-engine"):
        fugas = leaked(contexto, DEFAULT_FORBIDDEN_DIRS, DEFAULT_FORBIDDEN_GLOBS)
        pyc = [path for path in fugas if "__pycache__" in path]
        resto = [path for path in fugas if "__pycache__" not in path]
        assert not resto, f"{contexto.name}: {resto[:10]}"
        # Los .pyc anidados si se cuelan (ver test de abajo): son ruido, no secretos.
        assert all(path.endswith(".pyc") for path in pyc)


@pytest.mark.xfail(
    reason=(
        "Hallazgo de la auditoria E3: `.env`, `.env.*`, `__pycache__`, `*.db` y "
        "`*.py[cod]` en los .dockerignore son patrones anclados a la raiz del "
        "contexto: NO son globs recursivos. Verificado contra el demonio, un "
        "`sub/.env.production` si entra en el contexto. Arreglado en el PR de "
        "Dockerfiles (propiedad compartida)."
    ),
    strict=False,
)
def test_un_env_anidado_tampoco_deberia_entrar():
    assert is_excluded("sub/.env.production", read_patterns(DOCKERIGNORE_ENGINE))


def test_los_ficheros_de_ejemplo_de_secretos_siguen_dentro_del_contexto():
    """`.env*` esta excluido pero `*.env.example` se re-incluye a proposito (los
    ejemplos se versionan y los lee el compose). Se deja constancia de que esa
    excepcion es intencionada y no una forgot."""
    patterns = read_patterns(DOCKERIGNORE_ROOT)
    assert is_excluded(".env.production", patterns)
    assert not is_excluded("docker.env.example", patterns)


def test_el_auditor_de_contexto_replica_al_demonio(tmp_path):
    """El auditor tiene que reproducir la semantica real de docker, que se
    midio en la auditoria E3 con un contexto de prueba y `find` dentro de la
    imagen construida. Aqui se fija el caso que mas se presta a inventarse: un
    patron sin `/` casa en la raiz, no en todo el arbol."""
    (tmp_path / ".dockerignore").write_text("*.log\nnode_modules\n", encoding="utf-8")
    patterns = read_patterns(tmp_path / ".dockerignore")
    assert is_excluded("trace.log", patterns)
    assert not is_excluded("sub/trace.log", patterns), "docker no globa en subdirectorios"


def test_el_auditor_de_contexto_no_da_falsas_alarmas(tmp_path):
    """Si algo SI esta excluido, el auditor no lo reporta: si no, cada run
    pararia para senalar una fuga que ya esta controlada."""
    (tmp_path / ".dockerignore").write_text("node_modules\n.env\n.env.*\n*.log\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.js").write_text("x\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / ".env.production.local").write_text("SECRET=1\n", encoding="utf-8")
    assert leaked(tmp_path, DEFAULT_FORBIDDEN_DIRS, DEFAULT_FORBIDDEN_GLOBS) == []

def test_una_excepcion_con_paths_solo_cubre_ese_fichero(tmp_path):
    entry = {
        "id": "DS-0002",
        "scope": "misconfig",
        "paths": ["docker/minio/Dockerfile"],
        "reason": "volumen existente",
        "ticket": "T-1",
        "expires": "2099-12-31",
    }
    entries, errors = load_policy(_write_policy(tmp_path / "p.yaml", [entry]), date(2026, 10, 2))
    assert not errors

    def _payload(target: str) -> dict:
        return {"Results": [{"Target": target, "Misconfigurations": [_misconfig("HIGH")]}]}

    cubierto = _gate(_reports(tmp_path, misconfig=_payload("docker/minio/Dockerfile")), exceptions=entries)
    assert cubierto.passed
    otro = _gate(_reports(tmp_path, misconfig=_payload("Dockerfile.dev")), exceptions=entries)
    assert not otro.passed


@pytest.mark.parametrize("path", [
    "node_modules/pkg/index.js", "one/node_modules/pkg/index.js",
    "one/two/three/node_modules/pkg/index.js",
])
def test_recursive_dependency_glob_covers_zero_or_many_directories(path):
    from scripts.security.dockerignore import parse_patterns

    assert is_excluded(path, parse_patterns("**/node_modules"))
    assert not is_excluded(path.replace("node_modules", "my_node_modules"), parse_patterns("**/node_modules"))


def test_single_star_does_not_cross_directories():
    from scripts.security.dockerignore import parse_patterns

    assert is_excluded("one/file.js", parse_patterns("*/file.js"))
    assert not is_excluded("one/two/file.js", parse_patterns("*/file.js"))
# ---------------------------------------------------------------------------
# los imports relativos / @/ del build de Next apuntan a ficheros del contexto
# ---------------------------------------------------------------------------
#
# npm run build (= next build) typechequea **/*.ts (tsconfig) DENTRO de la
# imagen frontend-prod del SBOM. playwright.config.ts importa
# ./e2e/fixtures/e2e-env y tests/unit/e2e/e2e-env-config.test.ts importa
# ../../../e2e/fixtures/e2e-env, y el .dockerignore dejaba e2e/fixtures/ fuera
# del contexto: TS2307 solo en docker, con el repo en verde (medido 2026-10-30,
# run 41144668084, Build frontend-prod). Es la segunda vez: warmup-routes.ts
# cayo por lo mismo. Regla: todo import relativo o de alias @/ desde un
# .ts/.tsx que SI entra en el contexto tiene que resolverse a un fichero que
# TAMBIEN entra.

_PATRON_IMPORT_TS = re.compile(r"(?:\bfrom|\bimport|\brequire)\s*\(?\s*['\"](\.[^'\"]+|@/[^'\"]+)['\"]")
_EXTENSIONES_MODULO_TS = ("", ".ts", ".tsx", ".d.ts", ".js", ".jsx", ".json")


def _ficheros_ts_del_contexto() -> list[str]:
    """.ts/.tsx que entran en el contexto de build de la raiz (misma poda que
    el demonio: un directorio excluido no se recorre)."""
    patterns = read_patterns(DOCKERIGNORE_ROOT)
    ficheros: list[str] = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        relative = Path(dirpath).relative_to(REPO)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not is_excluded((relative / name).as_posix(), patterns)
        )
        for name in sorted(filenames):
            if name.endswith((".ts", ".tsx")):
                path = (relative / name).as_posix()
                if not is_excluded(path, patterns):
                    ficheros.append(path)
    return ficheros


def _resuelve_modulo_ts(base: Path) -> Path | None:
    """Resolucion de modulo de TS para imports relativos, sobre el repo."""
    for ext in _EXTENSIONES_MODULO_TS:
        candidato = Path(str(base) + ext)
        if candidato.is_file():
            return candidato
    if base.is_dir():
        for ext in _EXTENSIONES_MODULO_TS[1:]:
            candidato = base / f"index{ext}"
            if candidato.is_file():
                return candidato
    return None


def test_los_imports_del_build_apuntan_a_ficheros_del_contexto():
    patterns = read_patterns(DOCKERIGNORE_ROOT)
    rotos: list[str] = []
    for fichero in _ficheros_ts_del_contexto():
        texto = (REPO / fichero).read_text(encoding="utf-8", errors="replace")
        for espec in _PATRON_IMPORT_TS.findall(texto):
            if espec.startswith("@/"):
                base = REPO / espec[2:]
            else:
                base = (REPO / fichero).parent / espec
            resuelto = _resuelve_modulo_ts(base)
            if resuelto is None:
                # No existe ni en el repo: eso lo pillan tsc y el CI de frontend.
                continue
            rel = resuelto.relative_to(REPO).as_posix()
            if is_excluded(rel, patterns):
                rotos.append(f"{fichero} importa '{espec}' -> {rel} queda FUERA del contexto de build")
    assert not rotos, "\n".join(rotos[:10])


def test_todo_dockerfile_con_npm_ci_copia_antes_el_prepare():
    # package.json declara "prepare": "node scripts/install-hooks.mjs": npm ci lo
    # ejecuta siempre, tambien en Docker. Si el Dockerfile no copia ese script
    # antes del `RUN npm ci`, el build falla con "Cannot find module" (le paso a
    # frontend-dev cuando el prepare aterrizo: prod lo tenia y dev no).
    rotos: list[str] = []
    for dockerfile in (REPO / "Dockerfile", REPO / "Dockerfile.dev"):
        lineas = dockerfile.read_text(encoding="utf-8").splitlines()
        for i, linea in enumerate(lineas):
            if re.match(r"\s*RUN\s+npm ci\b", linea):
                antes = "\n".join(lineas[:i])
                if "scripts/install-hooks.mjs" not in antes:
                    rotos.append(f"{dockerfile.name}: `RUN npm ci` (linea {i + 1}) sin copiar antes scripts/install-hooks.mjs")
    assert not rotos, "\n".join(rotos)
