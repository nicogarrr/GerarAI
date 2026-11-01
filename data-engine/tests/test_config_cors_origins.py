"""CORS_ORIGINS se escribe como lista separada por comas en las plantillas.

Antes, `cp docker.env.example data-engine/.env` (el arranque local documentado)
tumbaba el backend: pydantic-settings leia `CORS_ORIGINS=a,b` como JSON y
fallaba con SettingsError antes de llegar a ningun validador.
"""

from pathlib import Path

import pytest

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Settings:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return Settings(_env_file=env_file)  # type: ignore[call-arg]


def test_cors_origins_separado_por_comas(tmp_path, monkeypatch):
    settings = _settings_from_env_file(
        tmp_path, monkeypatch, "CORS_ORIGINS=http://localhost:3000, http://127.0.0.1:3000\n"
    )
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_cors_origins_json_sigue_valiendo(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example", "https://b.example"]')
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]


def test_cors_origins_vacio_no_tumba_el_arranque(tmp_path, monkeypatch):
    settings = _settings_from_env_file(tmp_path, monkeypatch, "CORS_ORIGINS=\n")
    assert settings.cors_origins == []


def test_plantilla_local_carga_como_env_del_backend(monkeypatch):
    """La guia de desarrollo copia docker.env.example a data-engine/.env."""
    template = REPO_ROOT / "docker.env.example"
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(_env_file=template)  # type: ignore[call-arg]
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
