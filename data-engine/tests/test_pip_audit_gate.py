import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pip_audit_gate", Path(__file__).resolve().parents[2] / "scripts" / "pip_audit_gate.py"
)
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

CLEAN = json.dumps({"dependencies": [{"name": "fixture", "version": "1", "vulns": []}], "fixes": []})
VULNERABLE = json.dumps({"dependencies": [{"name": "fixture", "version": "1", "vulns": [{"id": "TEST-1"}]}]})
TRANSPORT = "requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443): Read timed out. (read timeout=30)"


def result(code=0, stdout=CLEAN, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def exercise(tmp_path, sequence, **kwargs):
    calls, delays = [], []

    def run(command, **options):
        calls.append((command, options))
        item = sequence[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    rc = gate.run_audit(run=run, sleep=delays.append, output_dir=tmp_path, **kwargs)
    return rc, calls, delays


def test_transient_recovers_and_keeps_both_logs(tmp_path):
    rc, calls, delays = exercise(tmp_path, [result(1, "", TRANSPORT), result()])
    assert rc == 0 and len(calls) == 2 and delays == [5]
    assert (tmp_path / "attempt-1.stderr").read_text() == TRANSPORT
    assert (tmp_path / "attempt-2.stdout").read_text() == CLEAN
    command, options = calls[0]
    assert command == [
        gate.sys.executable,
        "-m",
        "pip_audit",
        "-r",
        "data-engine/requirements.txt",
        "--format",
        "json",
        "--timeout",
        "30",
    ]
    assert options == {"capture_output": True, "text": True, "timeout": 180}


def test_transient_exhausted_stays_red(tmp_path):
    rc, calls, delays = exercise(tmp_path, [result(1, "", TRANSPORT)] * 3)
    assert rc == 1 and len(calls) == 3 and delays == [5, 10]
    assert len(list(tmp_path.iterdir())) == 6


@pytest.mark.parametrize("code", [0, 1])
def test_advisory_fails_immediately_even_with_transport_text(tmp_path, code):
    rc, calls, delays = exercise(tmp_path, [result(code, VULNERABLE, TRANSPORT)])
    assert rc == 1 and len(calls) == 1 and not delays


@pytest.mark.parametrize(
    "failure",
    [
        result(1, "", "resolution failed"),
        result(1, CLEAN),
        result(1, "", TRANSPORT.replace("pypi.org", "other.example")),
        result(0, "", TRANSPORT),
        result(1, "", "unknown error"),
    ],
)
def test_unknown_resolution_or_inconsistent_exit_fails(tmp_path, failure):
    rc, calls, delays = exercise(tmp_path, [failure])
    assert rc == 1 and len(calls) == 1 and not delays


@pytest.mark.parametrize(
    "report",
    [
        "",
        "bad json",
        "null",
        "[]",
        "{}",
        '{"dependencies":[]}',
        CLEAN[:-1] + ',"error":"incomplete"}',
        '{"dependencies":[null]}',
        '{"dependencies":[{"name":"x","version":"1","skip_reason":"not found","vulns":[]}]}',
        '{"dependencies":[{"name":"","version":"1","vulns":[]}]}',
        '{"dependencies":[{"name":"x","version":null,"vulns":[]}]}',
        '{"dependencies":[{"name":"x","version":"1","vulns":null}]}',
        '{"dependencies":[{"name":"x","version":"1","vulns":[{}]}]}',
        '{"dependencies":[{"name":"x","version":"1","vulns":[null]}]}',
    ],
)
def test_malformed_or_partial_report_fails_closed(tmp_path, report):
    rc, calls, delays = exercise(tmp_path, [result(0, report)])
    assert rc == 1 and len(calls) == 1 and not delays


def test_malformed_report_never_retried_despite_timeout(tmp_path):
    rc, calls, delays = exercise(tmp_path, [result(1, "{broken", TRANSPORT)])
    assert rc == 1 and len(calls) == 1 and not delays


def test_global_timeout_before_attempt(tmp_path):
    rc, calls, _ = exercise(tmp_path, [], budget=0)
    assert rc == 1 and not calls


def test_global_timeout_during_attempt_rejects_even_clean_report(tmp_path):
    ticks = iter([0, 0, 601])
    rc, calls, _ = exercise(tmp_path, [result()], clock=lambda: next(ticks))
    assert rc == 1 and len(calls) == 1


def test_global_timeout_before_backoff(tmp_path):
    ticks = iter([0, 0, 598, 598])
    rc, calls, delays = exercise(tmp_path, [result(1, "", TRANSPORT)], clock=lambda: next(ticks))
    assert rc == 1 and len(calls) == 1 and not delays


@pytest.mark.parametrize(
    "stdout,stderr", [(b"partial", b"diagnostic"), ("partial", "diagnostic"), (None, None)]
)
def test_process_timeout_fails_and_preserves_partial_logs(tmp_path, stdout, stderr):
    error = subprocess.TimeoutExpired("pip_audit", 180, output=stdout, stderr=stderr)
    rc, calls, delays = exercise(tmp_path, [error])
    assert rc == 1 and len(calls) == 1 and not delays
    assert (tmp_path / "attempt-1.stdout").read_text() == ("partial" if stdout else "")
    assert (tmp_path / "attempt-1.stderr").read_text() == ("diagnostic" if stderr else "")


def test_start_failure_is_red(tmp_path):
    rc, calls, delays = exercise(tmp_path, [OSError("missing executable")])
    assert rc == 1 and len(calls) == 1 and not delays
    assert "missing executable" in (tmp_path / "attempt-1.stderr").read_text()


def test_real_subprocess_cli_clean(tmp_path, monkeypatch):
    # Ejercita captura, comando y salida del proceso real sin depender de PyPI.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pip_audit.py").write_text("import json; print(" + repr(CLEAN) + ")")
    assert gate.run_audit(output_dir=tmp_path / "logs") == 0
    assert json.loads((tmp_path / "logs/attempt-1.stdout").read_text()) == json.loads(CLEAN)


def test_workflow_keeps_gate_blocking_and_uploads_logs():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
    block = workflow.split("      - name: Audit Python dependencies\n", 1)[1].split("\n  e2e:", 1)[0]
    assert "run: python scripts/pip_audit_gate.py" in block
    assert "continue-on-error" not in block
    assert "if: ${{ always() }}" in block
    assert "path: pip-audit-logs/" in block
    assert "uses: actions/upload-artifact@" in block


CPU_REPORT = json.dumps(
    {
        "dependencies": [
            {
                "name": name,
                "skip_reason": f"Dependency not found on PyPI and could not be audited: {name} ({version}+cpu)",
            }
            for name, version in gate.CPU_BASE_VERSIONS.items()
        ]
    }
)
BASE_REPORT = json.dumps(
    {
        "dependencies": [
            {"name": name, "version": version, "vulns": []}
            for name, version in gate.CPU_BASE_VERSIONS.items()
        ]
    }
)


def test_cpu_base_release_audit_must_succeed(tmp_path):
    rc, calls, delays = exercise(tmp_path, [result(0, CPU_REPORT), result(0, BASE_REPORT)])
    assert rc == 0 and len(calls) == 2 and not delays
    assert calls[1][0][-2:] == ["--no-deps", "--disable-pip"]
    assert (tmp_path / "cpu-base-requirements.txt").read_text() == "torch==2.14.1\ntorchvision==0.29.2\n"
    assert (tmp_path / "cpu-base/attempt-1.stdout").read_text() == BASE_REPORT


@pytest.mark.parametrize(
    "secondary",
    [
        result(1, VULNERABLE),
        result(0, CLEAN),
        result(0, CPU_REPORT),
        result(0, "{broken"),
        result(1, "", "unknown failure"),
    ],
)
def test_cpu_base_failure_incomplete_or_wrong_versions_stays_red(tmp_path, secondary):
    rc, calls, _ = exercise(tmp_path, [result(0, CPU_REPORT), secondary])
    assert rc == 1 and len(calls) == 2


def test_cpu_base_transport_retry_is_still_bounded(tmp_path):
    rc, calls, delays = exercise(
        tmp_path, [result(0, CPU_REPORT), result(1, "", TRANSPORT), result(0, BASE_REPORT)]
    )
    assert rc == 0 and len(calls) == 3 and delays == [5]


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        "null",
        "[]",
        "{broken",
        '{"dependencies":[null]}',
        CPU_REPORT.replace("2.14.1+cpu", "2.14.0+cpu"),
        CPU_REPORT.replace("torchvision", "other"),
        json.dumps({"dependencies": json.loads(CPU_REPORT)["dependencies"] * 2}),
    ],
)
def test_cpu_skips_are_exact_not_generic_allowlist(text):
    assert gate.cpu_base_requirements(text) == []
