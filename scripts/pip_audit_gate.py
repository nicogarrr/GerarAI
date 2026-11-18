"""Fail-closed pip-audit gate with bounded retries for PyPI read timeouts only."""

import json
import subprocess
import sys
import time
from pathlib import Path


def inspect_report(text):
    """Return clean/vulnerable/invalid. Skipped or partial audits never pass."""
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
        vulnerable = vulnerable or bool(vulns)
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
):
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
        report = inspect_report(result.stdout)
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_audit())
