"""Docker owns the reservation: probes that close sockets cannot reserve ports."""
from types import SimpleNamespace

import pytest

from scripts.backup import disaster_drill as mod
from scripts.backup._kit import FailClosedError


def test_up_uses_atomic_loopback_bindings_and_refreshes_after_destroy(monkeypatch, tmp_path):
    # Reproduce the old probe returning the same free port for every service.
    monkeypatch.setattr(mod, "free_port", lambda: 50041)
    monkeypatch.setattr(mod, "require_tool_docker", lambda: None)
    drill = mod.DrillEnvironment(workdir=tmp_path)
    assert (drill.pg_port, drill.minio_port, drill.qdrant_port) == (0, 0, 0)
    assert drill.app_port == 50041
    calls = []
    assigned = iter([50101, 50102, 50103, 50201, 50202, 50203])

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "port"]:
            return SimpleNamespace(stdout=f"127.0.0.1:{next(assigned)}\n")
        if argv[:2] == ["docker", "run"]:
            binding = argv[argv.index("-p") + 1]
            assert binding in {"127.0.0.1::5432", "127.0.0.1::9000", "127.0.0.1::6333"}
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(mod, "run", run)
    ready = []
    monkeypatch.setattr(drill, "wait_ready", lambda: ready.append((drill.pg_port, drill.minio_port, drill.qdrant_port)))
    drill.up()
    assert ready == [(50101, 50102, 50103)]
    env = mod._drill_app_env(drill)
    assert "50101" in env["DATABASE_URL"]
    assert env["QDRANT_URL"] == "http://127.0.0.1:50103"
    assert env["MINIO_ENDPOINT"] == "127.0.0.1:50102"
    drill.destroy()
    assert ready[-1] == (50201, 50202, 50203)
    assert len([a for a in calls if a[:2] == ["docker", "rm"]]) == 3
    drill.cleanup()
    assert drill.containers == {} and drill.volumes == {}


@pytest.mark.parametrize("raw", ["", "0.0.0.0:50101", "[::]:50101", "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:abc", "127.0.0.1:50001\n127.0.0.1:50002"])
def test_missing_nonlocal_or_ambiguous_binding_fails_closed(monkeypatch, tmp_path, raw):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    drill.containers["qdrant"] = "cavaai-drill-test-qdrant"
    monkeypatch.setattr(mod, "run", lambda *a, **k: SimpleNamespace(stdout=raw))
    with pytest.raises(FailClosedError):
        drill._published_port("qdrant", 6333)


@pytest.mark.parametrize("port", [1, 65535])
def test_valid_port_range_edges(monkeypatch, tmp_path, port):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    drill.containers["postgres"] = "cavaai-drill-test-postgres"
    monkeypatch.setattr(mod, "run", lambda *a, **k: SimpleNamespace(stdout=f"127.0.0.1:{port}\n"))
    assert drill._published_port("postgres", 5432) == port


def test_failed_docker_run_is_still_registered_for_cleanup(monkeypatch, tmp_path):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    monkeypatch.setattr(mod, "require_tool_docker", lambda: None)
    removed = []

    def run(argv, **kwargs):
        if argv[:2] == ["docker", "run"]:
            raise FailClosedError("network allocation failed")
        removed.append(argv)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(mod, "run", run)
    with pytest.raises(FailClosedError):
        drill._run_container("qdrant", mod.QDRANT_IMAGE, ["-p", "127.0.0.1::6333"], [])
    name = drill.containers["qdrant"]
    drill.cleanup()
    assert ["docker", "rm", "-f", name] in removed


def test_port_query_failure_propagates(monkeypatch, tmp_path):
    drill = mod.DrillEnvironment(workdir=tmp_path)
    drill.containers["qdrant"] = "cavaai-drill-test-qdrant"

    def run(*args, **kwargs):
        raise FailClosedError("docker port failed")

    monkeypatch.setattr(mod, "run", run)
    with pytest.raises(FailClosedError, match="docker port failed"):
        drill._published_port("qdrant", 6333)
