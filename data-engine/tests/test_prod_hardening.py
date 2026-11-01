"""Contratos de hardening de produccion (config, BD, deploy y backups).

Son tests de texto/configuracion: no levantan servicios ni tocan produccion.
Fijan las decisiones de la auditoria para que un cambio futuro no las revierta
en silencio (pool, placeholders, env-file, writers parados y checksums).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.database import _engine_pool_kwargs

DATA_ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DATA_ENGINE_ROOT.parent
SCRIPTS = REPO_ROOT / "scripts"
DOCS = REPO_ROOT / "docs"

PROD_SECRET = "research-security-test-secret-at-least-32-chars"
PROD_DB = "postgresql+psycopg://fixture_user:fixture_pass@fixture-db.invalid/fixture_db"
WORKERS = (
    "worker",
    "worker-thesis",
    "worker-kpis",
    "worker-alerts",
    "worker-gdelt",
    "worker-knowledge",
)


def _production(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_env="production",
        research_auth_required=True,
        research_auth_secret=PROD_SECRET,
        minio_access_key="production-minio-access-not-a-default",
        minio_secret_key="production-minio-secret-not-a-default",
        database_url=PROD_DB,
    )
    base.update(overrides)
    return Settings(**base)


def test_db_pool_defaults_and_env_parsing(monkeypatch):
    defaults = Settings(_env_file=None, app_env="test")
    assert defaults.db_pool_size == 10
    assert defaults.db_max_overflow == 10
    assert defaults.db_pool_timeout == 30.0
    assert defaults.db_pool_recycle == 3600

    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "7.5")
    monkeypatch.setenv("DB_POOL_RECYCLE", "600")
    worker_like = Settings(_env_file=None, app_env="test")
    assert worker_like.db_pool_size == 4
    assert worker_like.db_max_overflow == 2
    assert worker_like.db_pool_timeout == 7.5
    assert worker_like.db_pool_recycle == 600


def test_engine_pool_kwargs_are_applied_only_to_postgres():
    settings = Settings(
        _env_file=None,
        app_env="test",
        db_pool_size=4,
        db_max_overflow=2,
        db_pool_timeout=10,
        db_pool_recycle=900,
    )
    assert _engine_pool_kwargs("postgresql+psycopg://u:p@db:5432/x", settings) == {
        "pool_size": 4,
        "max_overflow": 2,
        "pool_timeout": 10,
        "pool_recycle": 900,
    }
    assert _engine_pool_kwargs("postgresql+psycopg://u:p@db:5432/x", settings)["pool_size"] == 4
    assert _engine_pool_kwargs("sqlite:///./test.db", settings) == {}


def test_sqlalchemy_compiles_the_pool_settings_without_connecting():
    from sqlalchemy import create_engine

    engine = create_engine(
        "postgresql+psycopg://u:p@127.0.0.1:5432/x",
        pool_size=4,
        max_overflow=2,
        pool_timeout=5,
        pool_recycle=60,
    )
    try:
        assert engine.pool.size() == 4
        assert engine.pool._max_overflow == 2
    finally:
        engine.dispose()


def test_production_rejects_placeholders():
    with pytest.raises(ValidationError, match="RESEARCH_AUTH_SECRET"):
        _production(research_auth_secret="cambia-esto-por-una-clave-larga-aleatoria")
    with pytest.raises(ValidationError, match="MINIO_SECRET_KEY"):
        _production(minio_secret_key="cambia-esto-tambien")
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        _production(
            database_url="postgresql+psycopg://user:genera-una-clave-larga@db:5432/x"
        )
    with pytest.raises(ValidationError, match="SEC_USER_AGENT"):
        _production(sec_user_agent="CavaAI/0.1 tu-email@example.com")


def test_production_accepts_real_looking_values():
    settings = _production(sec_user_agent="GerarAI research ops@gerarai-real.es")
    assert settings.is_production is True
    assert settings.db_pool_size == 10


def test_deploy_script_is_idempotent_and_has_a_secretless_preflight():
    source = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    assert "--env-file" in source and ".env.production" in source
    assert "docker compose" in source
    assert "config >/dev/null" in source
    assert "up -d --build --remove-orphans" in source
    assert "--wait" in source
    assert "cambia-esto" in source and "genera_" in source
    assert "grep -qE" in source
    # El preflight no imprime el contenido de .env.production (secretos).
    assert "cat ${ENV_FILE}" not in source


def test_backup_and_restore_stop_every_writer():
    for script in ("backup.sh", "restore.sh"):
        source = (SCRIPTS / script).read_text(encoding="utf-8")
        stop_lines = [line for line in source.splitlines() if "${COMPOSE} stop" in line]
        assert stop_lines, f"{script} no para servicios"
        joined = " ".join(stop_lines)
        for worker in WORKERS:
            assert worker in joined, f"{script} no para {worker}"
        assert "minio" in joined, f"{script} no para MinIO durante el snapshot"


def test_backup_uses_stop_storage_and_both_scripts_verify_checksums():
    backup = (SCRIPTS / "backup.sh").read_text(encoding="utf-8")
    restore = (SCRIPTS / "restore.sh").read_text(encoding="utf-8")
    assert "--stop-storage" in backup
    assert "sha256sum -c -" in backup
    assert "sha256sum -c -" in restore
    assert "manifest.txt" in restore
    # Fail-closed: el restore verifica ANTES de parar/destruir.
    assert restore.index("sha256sum -c -") < restore.index("${COMPOSE} stop")


def test_scripts_use_the_explicit_production_env_file():
    for script in ("backup.sh", "restore.sh"):
        source = (SCRIPTS / script).read_text(encoding="utf-8")
        assert "--env-file .env.production" in source, script
    deploy = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    assert 'ENV_FILE="${ENV_FILE:-.env.production}"' in deploy
    assert '--env-file "${ENV_FILE}"' in deploy


def test_deploy_and_backup_runbook_document_the_real_commands():
    oracle = (DOCS / "oracle-setup.md").read_text(encoding="utf-8")
    backups = (DOCS / "BACKUP_RESTORE.md").read_text(encoding="utf-8")
    assert "--env-file .env.production" in oracle
    assert "./scripts/deploy.sh" in oracle
    assert "backup.sh --stop-storage" in oracle
    assert "M0" in backups and "mongo-backup.sh" in backups
    assert "checksum" in backups.lower()
