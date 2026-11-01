"""The initdb temporary server listens on a socket, not TCP: do not race its restart."""
from types import SimpleNamespace

from scripts.backup import disaster_drill


def test_ready_query_requires_tcp_final_server(monkeypatch, tmp_path):
    drill = disaster_drill.DrillEnvironment(workdir=tmp_path)
    drill.containers["postgres"] = "cavaai-drill-test-postgres"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--host") + 1] == "127.0.0.1"
        assert argv[argv.index("--env") + 1].startswith("PGPASSWORD=")
        return SimpleNamespace(returncode=0, stdout="1\n")

    monkeypatch.setattr(disaster_drill, "run", run)
    assert drill._pg_query() is True
    assert calls[0][-1] == "SELECT 1"


def test_ready_query_does_not_accept_failed_or_wrong_tcp_result(monkeypatch, tmp_path):
    drill = disaster_drill.DrillEnvironment(workdir=tmp_path)
    drill.containers["postgres"] = "cavaai-drill-test-postgres"
    for result in [SimpleNamespace(returncode=1, stdout="1"), SimpleNamespace(returncode=0, stdout="")]:
        monkeypatch.setattr(disaster_drill, "run", lambda *args, result=result, **kwargs: result)
        assert drill._pg_query() is False
