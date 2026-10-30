"""Pruebas de ausencia de credenciales hardcodeadas y script de admin seguro.

Fulfills: VAL-SEC-002
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base
from scripts.create_initial_admin import (
    AdminCredentials,
    create_initial_admin,
    load_credentials_from_env,
    validate_credentials,
)


@pytest.fixture
def sqlite_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_cls = sessionmaker(bind=engine)
    session = session_cls()
    try:
        yield session
    finally:
        session.close()


def test_validate_credentials_valid():
    # Contrasena valida: >= 12 caracteres, mayuscula, minuscula, numero/simbolo
    validate_credentials("admin@gerarai.com", "SuperClaveSegura2026!")


@pytest.mark.parametrize(
    "invalid_email",
    [
        "",
        "notanemail",
        "admin@",
        "@gerarai.com",
        "admin@.com",
    ],
)
def test_validate_credentials_invalid_email(invalid_email: str):
    with pytest.raises(ValueError, match="El email proporcionado no tiene un formato valido"):
        validate_credentials(invalid_email, "SuperClaveSegura2026!")


@pytest.mark.parametrize(
    ("weak_password", "error_match"),
    [
        ("short", "al menos 12 caracteres"),
        ("short123!", "al menos 12 caracteres"),
        ("admin12345678", "demasiado comun o insegura"),
        ("password123456", "demasiado comun o insegura"),
        ("solominusculasylargasinnumero", "mayusculas, minusculas y al menos un numero o simbolo"),
        ("SOLOMAYUSCULAS9876543210!", "mayusculas, minusculas y al menos un numero o simbolo"),
    ],
)
def test_validate_credentials_weak_passwords(weak_password: str, error_match: str):
    with pytest.raises(ValueError, match=error_match):
        validate_credentials("admin@gerarai.com", weak_password)


def test_load_credentials_from_env_missing():
    with patch.dict(os.environ, {}, clear=True):
        assert load_credentials_from_env() is None


def test_load_credentials_from_env_success():
    env_vars = {
        "ADMIN_EMAIL": "admin@empresa.es",
        "ADMIN_PASSWORD": "ClaveMuySegura2026!",
        "ADMIN_NAME": "Nico Admin",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        creds = load_credentials_from_env()
        assert creds is not None
        assert creds.email == "admin@empresa.es"
        assert creds.password == "ClaveMuySegura2026!"
        assert creds.name == "Nico Admin"


def test_create_initial_admin_success_and_idempotent(sqlite_db):
    creds = AdminCredentials(
        email="operaciones@gerarai.com",
        password="ClaveMuySegura2026!",
        name="Operaciones",
    )

    tenant1 = create_initial_admin(creds, sqlite_db)
    assert tenant1.id is not None
    assert tenant1.external_id == "tenant_operaciones_at_gerarai_com"
    assert tenant1.status == "active"
    assert tenant1.metadata_["role"] == "admin"
    assert tenant1.metadata_["admin_email"] == "operaciones@gerarai.com"

    # Segunda ejecucion no duplica, devuelve el existente
    tenant2 = create_initial_admin(creds, sqlite_db)
    assert tenant2.id == tenant1.id


def test_no_hardcoded_admin_credentials_in_source_tree():
    """Verifica que no existan credenciales admin o API keys hardcodeadas en app/."""
    data_engine_dir = Path(__file__).resolve().parents[1]
    app_dir = data_engine_dir / "app"

    suspicious_patterns = [
        "admin_password =",
        "admin_pass =",
        "ADMIN_PASSWORD =",
    ]

    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for pattern in suspicious_patterns:
            assert pattern not in content, f"Posible credencial hardcodeada en {py_file}: {pattern}"
