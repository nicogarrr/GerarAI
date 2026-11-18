"""Fail-closed pip-audit gate with bounded retries for PyPI read timeouts only."""

import json
from datetime import date
import re
import subprocess
import sys
import time
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "data-engine" / "pyproject.toml"


def _version_tuple(text):
    return tuple(int(part) for part in text.strip().split("."))


def _satisfies_requires_python(version_info, specifier):
    """Minimal comparator for the project's own requires-python forms
    (>=, >, <=, <, ==, != over numeric tuples). Anything else raises:
    an unknown constraint must not silently disable the guard."""
    operators = (
        (">=", lambda a, b: a >= b),
        ("<=", lambda a, b: a <= b),
        ("!=", lambda a, b: a != b),
        ("==", lambda a, b: a == b),
        (">", lambda a, b: a > b),
        ("<", lambda a, b: a < b),
    )
    current = tuple(version_info)[:3]
    for clause in specifier.split(","):
        clause = clause.strip()
        for symbol, compare in operators:
            if clause.startswith(symbol):
                if not compare(current, _version_tuple(clause[len(symbol):])):
                    return False
                break
        else:
            raise ValueError(f"requires-python clause not understood: {clause!r}")
    return True


def check_interpreter(pyproject=_PYPROJECT, version_info=sys.version_info, stderr=None):
    """The gate audits a FRESH resolution of requirements.txt, which depends on
    the interpreter: under a different Python pip resolves different versions
    (measured 18-nov-2026: under 3.10 it resolves an old fastembed chain ->
    pillow 12.3.0 with ~40 advisories that are NOT the deployed set, while
    under 3.12, the project's requires-python, the resolution is clean).
    Only an interpreter inside the project's requires-python is valid
    evidence; anything else is red, never a misleading green or a false red."""
    if stderr is None:
        stderr = sys.stderr
    try:
        match = re.search(
            r'(?m)^requires-python\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError) as exc:
        # Un pyproject ilegible o con bytes no UTF-8 tampoco es evidencia: rojo.
        print(f"pip-audit: cannot read {pyproject}: {exc}", file=stderr)
        return False
    if not match:
        print(f"pip-audit: no requires-python in {pyproject}", file=stderr)
        return False
    specifier = match.group(1)
    try:
        satisfied = _satisfies_requires_python(version_info, specifier)
    except (ValueError, TypeError) as exc:
        print(f"pip-audit: unparseable requires-python {specifier!r}: {exc}", file=stderr)
        return False
    if not satisfied:
        current = ".".join(str(part) for part in tuple(version_info)[:3])
        print(
            f"pip-audit: interpreter {current} is outside the project requires-python "
            f"{specifier!r}: a requirements resolution under this Python is not valid "
            "evidence. Run the gate with the project's Python.",
            file=stderr,
        )
        return False
    return True


def inspect_report(text, ignored_pins=None):
    """Return clean/vulnerable/invalid. Skipped or partial audits never pass.

    ignored_pins: {name: version} whose advisories are waived ONLY on that
    exact resolved version. A vuln on any other package or version stays red,
    so the waiver dies with the pin instead of covering the next one."""
    try:
        report = json.loads(text)
    except (ValueError, TypeError):
        return "invalid"
    if (
        not isinstance(report, dict)
        or "error" in report
        or not isinstance(report.get("dependencies"), list)
    ):
        return "invalid"
    dependencies = report["dependencies"]
    if not dependencies:
        return "invalid"
    vulnerable = False
    for dep in dependencies:
        if not isinstance(dep, dict) or "skip_reason" in dep:
            return "invalid"
        if not isinstance(dep.get("name"), str) or not dep["name"]:
            return "invalid"
        if not isinstance(dep.get("version"), str) or not dep["version"]:
            return "invalid"
        vulns = dep.get("vulns")
        if not isinstance(vulns, list):
            return "invalid"
        for vuln in vulns:
            if (
                not isinstance(vuln, dict)
                or not isinstance(vuln.get("id"), str)
                or not vuln["id"]
            ):
                return "invalid"
        if vulns and not (ignored_pins or {}).get(dep["name"]) == dep["version"]:
            vulnerable = True
    return "vulnerable" if vulnerable else "clean"


# Explicit CPU wheel versions observed in the requirements audit on 18-Nov-2026.
# These are NOT ignored: their base releases must pass a separate PyPI audit.
CPU_BASE_VERSIONS = {"torch": "2.14.1", "torchvision": "0.29.2"}


def cpu_base_requirements(text):
    try:
        report = json.loads(text)
        dependencies = report["dependencies"]
        pins = []
        normalized = []
        for dep in dependencies:
            name = dep.get("name")
            base = CPU_BASE_VERSIONS.get(name)
            reason = f"Dependency not found on PyPI and could not be audited: {name} ({base}+cpu)"
            if base and dep == {"name": name, "skip_reason": reason}:
                pins.append(f"{name}=={base}")
                normalized.append({"name": name, "version": base, "vulns": []})
            else:
                normalized.append(dep)
        report["dependencies"] = normalized
        if (
            pins
            and len(pins) == len(set(pins))
            and inspect_report(json.dumps(report)) == "clean"
        ):
            return pins
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return []


def is_transport_timeout(result):
    # No report may be discarded, even when stderr also mentions a timeout.
    # Deliberately narrow: unknown failures and resolution errors do not retry.
    return (
        result.returncode != 0
        and not result.stdout.strip()
        and "requests.exceptions.ReadTimeout:" in result.stderr
        and "HTTPSConnectionPool(host='pypi.org', port=443)" in result.stderr
        and "Read timed out." in result.stderr
    )


def run_audit(
    *,
    run=subprocess.run,
    sleep=time.sleep,
    clock=time.monotonic,
    output_dir=Path("pip-audit-logs"),
    budget=600,
    _requirements="data-engine/requirements.txt",
    _base_only=False,
    _pyproject=_PYPROJECT,
    _version_info=sys.version_info,
    _ignored_pins=None,
    _today=date.today,
):
    if not check_interpreter(pyproject=_pyproject, version_info=_version_info):
        return 1
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = clock() + budget
    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        str(_requirements),
        "--format",
        "json",
        "--timeout",
        "30",
    ]
    if _base_only:
        command.extend(["--no-deps", "--disable-pip"])
    for attempt in range(1, 4):
        remaining = deadline - clock()
        if remaining <= 0:
            print("pip-audit: total deadline exhausted", file=sys.stderr)
            return 1
        try:
            result = run(
                command, capture_output=True, text=True, timeout=min(180, remaining)
            )
        except subprocess.TimeoutExpired as exc:
            # A hung process is not proven to be a retryable transport error.
            for label, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
                if isinstance(value, bytes):
                    value = value.decode(errors="replace")
                (output_dir / f"attempt-{attempt}.{label}").write_text(value or "")
            print("pip-audit: process timeout, audit incomplete", file=sys.stderr)
            return 1
        except OSError as exc:
            (output_dir / f"attempt-{attempt}.stderr").write_text(str(exc))
            print("pip-audit: failed to start", file=sys.stderr)
            return 1
        (output_dir / f"attempt-{attempt}.stdout").write_text(result.stdout)
        (output_dir / f"attempt-{attempt}.stderr").write_text(result.stderr)
        print(f"pip-audit attempt {attempt}: exit {result.returncode}")
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        if clock() >= deadline:
            print("pip-audit: total deadline exhausted", file=sys.stderr)
            return 1
        report = inspect_report(result.stdout, ignored_pins=_ignored_pins)
        if report == "clean" and result.returncode == 0:
            if _base_only:
                expected = Path(_requirements).read_text().splitlines()
                actual = [
                    f"{dep['name']}=={dep['version']}"
                    for dep in json.loads(result.stdout)["dependencies"]
                ]
                if sorted(actual) != sorted(expected):
                    return 1
            return 0
        pins = (
            cpu_base_requirements(result.stdout)
            if not _base_only and result.returncode == 0
            else []
        )
        # pip-audit exit codes: 0 limpio, 1 con advisories, 2 error (crash,
        # resolucion rota, CLI mal usada). Un JSON completo NO prueba exito:
        # solo 0 o 1 son evidencia; un 2 con JSON "clean" sigue en rojo.
        if _ignored_pins and report == "clean" and result.returncode in (0, 1):
            if _today() > QA_AGENTS_IGNORED_PINS_REVIEW:
                print(
                    "pip-audit: excepciones temporales CADUCADAS el "
                    f"{QA_AGENTS_IGNORED_PINS_REVIEW.isoformat()} (alta 18-nov-2026): "
                    "revisar los pins de browser-use o renovar cada entrada con "
                    "motivo y fecha nueva; mientras, el gate no perdona",
                    file=sys.stderr,
                )
                return 1
            waived = [
                f"{dep['name']}=={dep['version']}"
                for dep in json.loads(result.stdout)["dependencies"]
                if dep.get("vulns")
            ]
            if waived:
                print(
                    "pip-audit: advisories cubiertos por excepcion temporal fijada: "
                    + ", ".join(waived)
                )
            print(
                "pip-audit: excepciones temporales en uso "
                f"(caducan {QA_AGENTS_IGNORED_PINS_REVIEW.isoformat()}, "
                "alta 18-nov-2026)",
                file=sys.stderr,
            )
            return 0
        if pins:
            requirements = output_dir / "cpu-base-requirements.txt"
            requirements.write_text("\n".join(pins) + "\n")
            print(
                "pip-audit: CPU wheels not in PyPI; auditing base releases: "
                + ", ".join(pins)
            )
            print(
                "pip-audit: this checks base-release advisories, not CPU-wheel build provenance"
            )
            return run_audit(
                run=run,
                sleep=sleep,
                clock=clock,
                output_dir=output_dir / "cpu-base",
                budget=deadline - clock(),
                _requirements=str(requirements),
                _base_only=True,
            )
        if not is_transport_timeout(result) or attempt == 3:
            return 1
        delay = attempt * 5
        if deadline - clock() <= delay:
            return 1
        print(f"pip-audit: PyPI read timeout, retry in {delay}s", file=sys.stderr)
        sleep(delay)
    return 1  # pragma: no cover - loop always returns on attempt 3


# EXCEPCIONES TEMPORALES (alta 18-nov-2026) para qa-agents/requirements.txt.
# browser-use 0.13.14 fija CON == estas cuatro versiones con advisories;
# browser-use 1.0.6 (16-nov-2026) solo resuelve mcp (==2.3.0) y sigue
# fijando pillow==12.3.0: no hay version upstream que las corrija. La
# superficie son los agentes QA de CI contra la instancia local de GerarAI
# (no prod, sin secretos de usuario). Las excepciones van por (paquete,
# version exacta): si la resolucion trae OTRA version con advisories, o
# cualquier otro paquete, el gate sigue en rojo. Retirar cada entrada al
# subir browser-use; revisar en cada release de browser-use.
# Fecha limite de las excepciones: pasada, el gate vuelve a rojo aunque los
# advisories sigan siendo los fijados. Renovar solo tras revisar el estado de
# los pins de browser-use y anotar motivo y fecha nueva.
QA_AGENTS_IGNORED_PINS_REVIEW = date(2026, 12, 18)

QA_AGENTS_IGNORED_PINS = {
    "anyio": "4.12.1",  # PYSEC-2026-4025, PYSEC-2026-4024 (fix 4.14.2)
    "mcp": "2.1.1",  # CVE-2026-59951, CVE-2026-116685, CVE-2026-116684 (fix 2.2.0)
    "pillow": "12.3.0",  # ~40 advisories, fix 13.0.0 (browser-use 1.0.6 aun fija 12.3.0)
    "pypdf": "6.16.2",  # PYSEC-2026-4153, PYSEC-2026-4154, PYSEC-2026-4160 (fix 6.17.0+)
}


if __name__ == "__main__":  # pragma: no cover
    rc = run_audit()
    # Las herramientas QA (browser-use + playwright en agent-qa.yml) se
    # instalan del mismo modo y merecen la misma auditoria; excepciones
    # itemizadas arriba hasta que browser-use suelte los pins.
    rc_qa = run_audit(
        output_dir=Path("pip-audit-logs") / "qa-agents",
        _requirements="qa-agents/requirements.txt",
        _ignored_pins=QA_AGENTS_IGNORED_PINS,
    )
    raise SystemExit(rc or rc_qa)
