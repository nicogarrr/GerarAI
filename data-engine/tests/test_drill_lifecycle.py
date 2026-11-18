"""Exercise drill lifecycle without Docker; real containers remain a CI check."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.backup import disaster_drill as mod
from scripts.backup._kit import FailClosedError


def test_isolation_refuses_existing_names_or_repo_directory(monkeypatch, tmp_path):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    monkeypatch.setattr(mod, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    drill.require_isolated()
    monkeypatch.setattr(mod, "run", lambda *a, **k: SimpleNamespace(stdout=f"cavaai-{drill.drill_id}-minio"))
    with pytest.raises(FailClosedError):
        drill.require_isolated()
    drill.workdir = mod.DATA_ENGINE_ROOT
    with pytest.raises(FailClosedError):
        drill.require_isolated()


def test_ready_checks_all_services_and_timeout_keeps_diagnostics(monkeypatch, tmp_path):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    monkeypatch.setattr(drill, "_pg_query", lambda: True)
    monkeypatch.setattr(drill, "_http_ok", lambda *a: True)
    drill.wait_ready()
    drill.containers["qdrant"] = "cavaai-drill-test-qdrant"
    monkeypatch.setattr(mod, "run", lambda *a, **k: SimpleNamespace(stdout="exited", stderr="failure"))
    assert "qdrant" in drill._diagnostico_contenedores(["qdrant", "missing"])
    with pytest.raises(FailClosedError, match="no respondieron"):
        drill.wait_ready(timeout=0)
    drill.keep = True
    drill.cleanup()
    assert drill.containers


@pytest.mark.parametrize("kind, expected", [("success", True), ("server", False), ("client", True), ("network", False)])
def test_http_readiness_outcomes(monkeypatch, kind, expected):
    import urllib.error
    import urllib.request
    from contextlib import nullcontext

    def open_url(*a, **k):
        if kind == "success":
            return nullcontext(SimpleNamespace(status=200))
        if kind == "network":
            raise OSError("offline")
        raise urllib.error.HTTPError("http://localhost", 503 if kind == "server" else 404, "error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", open_url)
    assert mod.DrillEnvironment._http_ok(50001, "/healthz") is expected


@pytest.mark.parametrize("outcome", ["success", "exit", "timeout"])
def test_app_uses_discovered_ports_and_stops(monkeypatch, tmp_path, outcome):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    app = mod.AppProcess(drill)
    proc = Mock(returncode=2)
    proc.poll.return_value = 2 if outcome == "exit" else None
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(drill, "_http_ok", lambda *a: outcome == "success")
    times = iter([0, 0, mod.APP_WAIT_SECONDS + 1])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(mod.time, "sleep", lambda *a: None)
    if outcome == "success":
        assert app.start() == f"http://127.0.0.1:{drill.app_port}"
    else:
        with pytest.raises(FailClosedError):
            app.start()
    app.stop()
    if outcome != "exit":
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()
    app.proc = None
    app.stop()


@pytest.mark.parametrize("failure", [None, "data", "app", "known", "unexpected"])
def test_full_lifecycle_restores_to_new_ports_and_fails_closed(monkeypatch, tmp_path, failure):
    from scripts.backup import backup_all
    from scripts.restore import restore_minio, restore_postgres, restore_qdrant, verify_restore

    drill = mod.DrillEnvironment(workdir=tmp_path)
    drill.pg_port, drill.minio_port, drill.qdrant_port = 50001, 50002, 50003
    drill.containers["postgres"] = "cavaai-drill-before-postgres"
    monkeypatch.setattr(mod, "DrillEnvironment", lambda **k: drill)
    monkeypatch.setattr(drill, "require_isolated", lambda: None)

    def up():
        if failure == "known":
            raise FailClosedError("docker run failed")
        if failure == "unexpected":
            raise ValueError("unexpected failure")

    monkeypatch.setattr(drill, "up", up)
    cleaned = Mock()
    monkeypatch.setattr(drill, "cleanup", cleaned)

    def destroy():
        drill.minio_port, drill.qdrant_port = 51002, 51003
        drill.containers["postgres"] = "cavaai-drill-after-postgres"

    monkeypatch.setattr(drill, "destroy", destroy)
    app = SimpleNamespace(start=Mock(return_value="http://127.0.0.1:50004"), stop=Mock())
    monkeypatch.setattr(mod, "AppProcess", lambda *a: app)
    monkeypatch.setattr(mod, "seed_all", lambda *a: None)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    manifest = backup_dir / "manifest.json"
    manifest.write_text(json.dumps({"backup_id": "test"}))
    monkeypatch.setattr(backup_all, "run_all", lambda *a: (SimpleNamespace(write=lambda: manifest), backup_dir))
    pg = Mock(return_value={})
    mi = Mock(return_value={})
    qd = Mock(return_value={})
    monkeypatch.setattr(restore_postgres, "run_restore", pg)
    monkeypatch.setattr(restore_minio, "run_restore", mi)
    monkeypatch.setattr(restore_qdrant, "run_restore", qd)

    def verify(config, *, phase):
        assert config.minio_endpoint == "127.0.0.1:51002"
        assert config.qdrant_url == "http://127.0.0.1:51003"
        ok = failure != ("data" if phase == verify_restore.PHASE_DATA else "app")
        return ok, [], {"checks_passed": int(ok), "checks_total": 1}

    monkeypatch.setattr(verify_restore, "verify", verify)
    monkeypatch.setattr(mod, "_assert_seed_counts", lambda *a: None)
    assert mod.run_drill(workdir=tmp_path) == (0 if failure is None else 1)
    cleaned.assert_called_once()
    app.stop.assert_called_once()
    if failure not in {"known", "unexpected"}:
        assert pg.call_args.kwargs["container"] == "cavaai-drill-after-postgres"
        assert mi.call_args.kwargs["endpoint"] == "127.0.0.1:51002"
        assert qd.call_args.kwargs["url"] == "http://127.0.0.1:51003"


def test_seed_connects_to_assigned_ports(monkeypatch, tmp_path):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    drill.pg_port, drill.minio_port, drill.qdrant_port = 50001, 50002, 50003
    for name in ["seed_postgres", "seed_minio", "seed_qdrant"]:
        monkeypatch.setattr(mod.seed_drill_data, name, Mock())
    mod.seed_all(drill)
    assert "50001" in mod.seed_drill_data.seed_postgres.call_args.args[0]
    assert mod.seed_drill_data.seed_minio.call_args.args[0] == "127.0.0.1:50002"
    assert mod.seed_drill_data.seed_qdrant.call_args.args[0] == "http://127.0.0.1:50003"


@pytest.mark.parametrize("mode", ["explicit", "temporary", "keep", "failure"])
def test_cli_workdir_and_cleanup(monkeypatch, tmp_path, mode):
    def run(**kwargs):
        assert kwargs["workdir"].exists()
        if mode == "failure":
            raise FailClosedError("failed")
        return 0

    monkeypatch.setattr(mod, "run_drill", run)
    argv = ["--workdir", str(tmp_path / "explicit")] if mode == "explicit" else []
    if mode == "keep":
        argv.append("--keep")
    assert mod.main(argv) == (1 if mode == "failure" else 0)


def test_seed_manifest_checks_counts_and_hashes(tmp_path):
    artifact = tmp_path / "dump"
    artifact.write_text("fixture")
    manifest = {
        "postgres": {"tables": {"companies": mod.SEED_COMPANIES}},
        "minio": {"object_count": mod.SEED_OBJECTS},
        "qdrant": {"total_points": mod.SEED_POINTS},
        "tools": {"qdrant": {"version": mod.REQUIRED_QDRANT_MAJOR_MINOR + ".2"}},
        "artifacts": [{"path": "dump", "sha256": mod.sha256_file(artifact)}],
    }
    mod._assert_seed_counts(manifest, tmp_path)
    artifact.write_text("corrupt")
    with pytest.raises(FailClosedError, match="sha256"):
        mod._assert_seed_counts(manifest, tmp_path)
    manifest["postgres"]["tables"]["companies"] = -1
    with pytest.raises(FailClosedError, match="companies"):
        mod._assert_seed_counts(manifest, tmp_path)


def test_wait_retries_unready_service(monkeypatch, tmp_path):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    checks = iter([False, True])
    monkeypatch.setattr(drill, "_pg_query", lambda: next(checks))
    monkeypatch.setattr(drill, "_http_ok", lambda *a: True)
    sleep = Mock()
    monkeypatch.setattr(mod.time, "sleep", sleep)
    drill.wait_ready()
    sleep.assert_called_once_with(2)
