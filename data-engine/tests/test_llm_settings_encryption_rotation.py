"""Rotacion y manejo de la clave de cifrado de las API keys LLM por tenant."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.core.llm_settings_crypto import (
    LLMSettingsCryptoError,
    decrypt_api_key,
    encrypt_api_key,
    encryption_available,
    needs_reencryption,
)
from app.models import Tenant, TenantLLMSettings
from app.services.tenant_llm_settings_service import (
    TenantLLMUpdate,
    config_from_row,
    save_tenant_settings,
    settings_view,
)

OLD_KEY = "clave-antigua-de-cifrado-con-mas-de-32-bytes"
NEW_KEY = "clave-nueva-de-cifrado-con-bastante-mas-de-32-bytes"
AUTH_SECRET = "secreto-de-autenticacion-local-de-al-menos-32-bytes"
API_KEY = "sk-rotacion-9876"


def _settings(**extra) -> Settings:
    base = dict(
        _env_file=None,
        app_env="test",
        research_auth_secret=AUTH_SECRET,
        llm_settings_encryption_key=NEW_KEY,
        opencode_go_api_key="platform-key-not-for-tenants",
    )
    # model_copy: el validador de produccion exige mas secretos que no vienen al caso.
    return Settings(**base).model_copy(update=extra)


def test_clave_rotada_sin_anteriores_no_descifra() -> None:
    cipher = encrypt_api_key(API_KEY, _settings(llm_settings_encryption_key=OLD_KEY))
    with pytest.raises(LLMSettingsCryptoError, match="ciphertext_invalid"):
        decrypt_api_key(cipher, _settings())


def test_clave_anterior_descifra_y_lo_nuevo_se_cifra_con_la_actual() -> None:
    cipher = encrypt_api_key(API_KEY, _settings(llm_settings_encryption_key=OLD_KEY))
    rotated = _settings(llm_settings_encryption_key_previous=f" corta , {OLD_KEY} ")
    assert decrypt_api_key(cipher, rotated) == API_KEY
    assert needs_reencryption(cipher, rotated)
    fresh = encrypt_api_key(API_KEY, rotated)
    assert not needs_reencryption(fresh, rotated)
    # Lo nuevo NO depende de la clave anterior.
    assert decrypt_api_key(fresh, _settings()) == API_KEY


def test_la_clave_anterior_sola_no_habilita_el_cifrado_en_produccion() -> None:
    prod = _settings(
        app_env="production",
        llm_settings_encryption_key=None,
        llm_settings_encryption_key_previous=OLD_KEY,
    )
    assert not encryption_available(prod)
    with pytest.raises(LLMSettingsCryptoError, match="not_configured"):
        encrypt_api_key(API_KEY, prod)
    cipher = encrypt_api_key(API_KEY, _settings(llm_settings_encryption_key=OLD_KEY))
    with pytest.raises(LLMSettingsCryptoError, match="not_configured"):
        decrypt_api_key(cipher, prod)


def test_produccion_nunca_usa_el_secreto_de_autenticacion() -> None:
    local_cipher = encrypt_api_key(
        API_KEY, _settings(llm_settings_encryption_key=None)
    )
    prod = _settings(app_env="production")
    with pytest.raises(LLMSettingsCryptoError, match="ciphertext_invalid"):
        decrypt_api_key(local_cipher, prod)
    assert not encryption_available(
        _settings(app_env="production", llm_settings_encryption_key=None)
    )


def test_en_local_lo_guardado_antes_de_fijar_la_clave_sigue_funcionando() -> None:
    local_cipher = encrypt_api_key(
        API_KEY, _settings(llm_settings_encryption_key=None)
    )
    assert decrypt_api_key(local_cipher, _settings()) == API_KEY
    assert needs_reencryption(local_cipher, _settings())


@pytest.mark.parametrize("key", ["", "   ", "corta-de-31-bytes-xxxxxxxxxxxxx"])
def test_clave_explicita_corta_deja_el_cifrado_no_disponible(key: str) -> None:
    settings = _settings(app_env="production", llm_settings_encryption_key=key)
    assert not encryption_available(settings)


def test_prefijo_desconocido_o_token_roto_falla_cerrado() -> None:
    settings = _settings()
    with pytest.raises(LLMSettingsCryptoError, match="unsupported"):
        decrypt_api_key("v2:abc", settings)
    with pytest.raises(LLMSettingsCryptoError, match="ciphertext_invalid"):
        decrypt_api_key("v1:no-es-un-token", settings)
    assert not needs_reencryption("v2:abc", settings)


@pytest.fixture(autouse=True)
def _limpia_filas_creadas():
    """Otras suites cuentan las filas de ajustes LLM: no dejar las nuestras."""
    yield
    if not _CREATED:
        return
    with SessionLocal() as db:
        db.execute(
            delete(TenantLLMSettings)
            .where(TenantLLMSettings.tenant_id.in_(_CREATED))
            .execution_options(include_all_tenants=True)
        )
        db.commit()
    _CREATED.clear()


_CREATED: list[int] = []


def _tenant(db, name: str) -> Tenant:
    tenant = Tenant(external_id=f"{name}-{uuid4().hex[:8]}", name=name)
    db.add(tenant)
    db.flush()
    _CREATED.append(tenant.id)
    return tenant


def test_fila_con_clave_anterior_funciona_y_se_recifra_al_guardar() -> None:
    init_db()
    old = _settings(llm_settings_encryption_key=OLD_KEY)
    rotated = _settings(llm_settings_encryption_key_previous=OLD_KEY)
    with SessionLocal() as db:
        tenant = _tenant(db, "llm-rotacion")
        db.info["tenant_id"] = tenant.id
        row = save_tenant_settings(
            db,
            TenantLLMUpdate(provider="openai", model="gpt-4.1-mini", api_key=API_KEY),
            old,
        )
        db.commit()
        old_cipher = row.api_key_ciphertext
        assert old_cipher

        # Sin la clave anterior: la IA del tenant queda desactivada (falla cerrado).
        broken = config_from_row(row, _settings())
        assert broken.error == "tenant_llm_settings_corrupt"
        assert settings_view(db, _settings())["status"] == "disabled"

        # Con la clave anterior declarada sigue funcionando...
        config = config_from_row(row, rotated)
        assert config.error is None
        assert config.api_key == API_KEY
        assert settings_view(db, rotated)["status"] == "tenant"

        # ...y al guardar sin clave nueva se recifra con la actual.
        row = save_tenant_settings(
            db,
            TenantLLMUpdate(provider="openai", model="gpt-4.1"),
            rotated,
        )
        db.commit()
        assert row.api_key_ciphertext != old_cipher
        assert row.api_key_last4 == API_KEY[-4:]
        assert decrypt_api_key(row.api_key_ciphertext or "", _settings()) == API_KEY


def test_fila_ilegible_no_se_toca_al_guardar() -> None:
    init_db()
    with SessionLocal() as db:
        tenant = _tenant(db, "llm-ilegible")
        db.info["tenant_id"] = tenant.id
        row = save_tenant_settings(
            db,
            TenantLLMUpdate(provider="openai", model="gpt-4.1-mini", api_key=API_KEY),
            _settings(llm_settings_encryption_key=OLD_KEY),
        )
        db.commit()
        cipher = row.api_key_ciphertext
        row = save_tenant_settings(
            db, TenantLLMUpdate(provider="openai", model="gpt-4.1"), _settings()
        )
        db.commit()
        assert row.api_key_ciphertext == cipher
        assert config_from_row(row, _settings()).error == "tenant_llm_settings_corrupt"
