"""Retired raw-volume MinIO scripts must stop before any side effect."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh", "verify-backup-restore.sh"])
@pytest.mark.parametrize("override", [False, True])
def test_retired_scripts_stop_before_docker_or_creating_backup(tmp_path, script, override):
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/bash\ntouch "$SIDE_EFFECT"\nexit 1\n')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "SIDE_EFFECT": str(tmp_path / "called-docker")}
    env.pop("COMPOSE_CMD", None)
    if override:
        env["COMPOSE_CMD"] = "docker compose -f docker-compose.prod.yml"
    result = subprocess.run(["bash", str(ROOT / "scripts" / script),
                             "backups/missing", "--confirm-restore"],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert "retirado" in result.stderr
    assert "Garage" in result.stderr
    assert not (tmp_path / "called-docker").exists()
    assert not (tmp_path / "backups").exists()


def test_deploy_does_not_require_retired_minio_password(tmp_path):
    env_file = tmp_path / "production.env"
    env_file.write_text("\n".join(f"{key}=test-value" for key in (
        "POSTGRES_PASSWORD", "RESEARCH_AUTH_SECRET", "GARAGE_RPC_SECRET",
        "GARAGE_ACCESS_KEY", "GARAGE_SECRET_KEY", "BACKEND_DOMAIN")))
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    docker.chmod(0o755)
    calls = tmp_path / "docker-calls"
    result = subprocess.run(["bash", str(ROOT / "scripts/deploy.sh")],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "ENV_FILE": str(env_file), "CALLS": str(calls), "SKIP_PULL": "1"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "up -d --build" in calls.read_text()
    assert "docker-compose.prod.yml" in calls.read_text()
    assert "docker-compose.yml" not in calls.read_text()
