"""Cifrado en reposo de las API keys LLM por tenant (Fernet).

La clave se toma de ``LLM_SETTINGS_ENCRYPTION_KEY`` (>=32 bytes) y en
local/test se deriva de ``RESEARCH_AUTH_SECRET``. En produccion NUNCA se usa
el secreto de autenticacion como sustituto: sin clave explicita el cifrado
queda no disponible y la API responde 503 al intentar guardar una clave.

Rotacion: ``LLM_SETTINGS_ENCRYPTION_KEY_PREVIOUS`` (separadas por comas) lista
claves anteriores que solo DESCIFRAN; todo lo nuevo se cifra con la actual.
En local/test el secreto de autenticacion tambien descifra aunque haya clave
explicita, para que las filas guardadas antes de fijarla sigan funcionando.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import Settings, get_settings

KEY_VERSION = 1
_CIPHERTEXT_PREFIX = "v1:"


class LLMSettingsCryptoError(RuntimeError):
    """La configuracion cifrada no se puede usar (falta clave o esta corrupta)."""


def _derived_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _key_bytes(settings: Settings | None = None) -> bytes | None:
    settings = settings or get_settings()
    explicit = (settings.llm_settings_encryption_key or "").strip()
    if explicit:
        if len(explicit.encode("utf-8")) < 32:
            return None
        return _derived_key(explicit)
    if settings.is_production:
        return None
    fallback = (settings.research_auth_secret or "").strip()
    if len(fallback.encode("utf-8")) < 32:
        return None
    return _derived_key(fallback)


def _decrypt_keys(settings: Settings) -> list[bytes]:
    """Clave actual primero y despues las anteriores validas (sin duplicados)."""
    keys: list[bytes] = []
    current = _key_bytes(settings)
    if current is not None:
        keys.append(current)
    previous = settings.llm_settings_encryption_key_previous or ""
    candidates = [item.strip() for item in previous.split(",")]
    if not settings.is_production and (settings.llm_settings_encryption_key or "").strip():
        # Filas guardadas en local antes de fijar la clave explicita.
        candidates.append((settings.research_auth_secret or "").strip())
    for secret in candidates:
        if len(secret.encode("utf-8")) < 32:
            continue
        derived = _derived_key(secret)
        if derived not in keys:
            keys.append(derived)
    return keys


def needs_reencryption(ciphertext: str, settings: Settings | None = None) -> bool:
    """True si el texto cifrado se descifra pero NO con la clave actual."""
    settings = settings or get_settings()
    key = _key_bytes(settings)
    if key is None or not ciphertext.startswith(_CIPHERTEXT_PREFIX):
        return False
    try:
        Fernet(key).decrypt(ciphertext[len(_CIPHERTEXT_PREFIX) :].encode("ascii"))
    except (InvalidToken, ValueError, UnicodeError):
        return True
    return False


def encryption_available(settings: Settings | None = None) -> bool:
    return _key_bytes(settings) is not None


def encrypt_api_key(plaintext: str, settings: Settings | None = None) -> str:
    key = _key_bytes(settings)
    if key is None:
        raise LLMSettingsCryptoError("llm_settings_encryption_not_configured")
    token = Fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{_CIPHERTEXT_PREFIX}{token}"


def decrypt_api_key(ciphertext: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if _key_bytes(settings) is None:
        raise LLMSettingsCryptoError("llm_settings_encryption_not_configured")
    if not ciphertext.startswith(_CIPHERTEXT_PREFIX):
        raise LLMSettingsCryptoError("llm_settings_ciphertext_unsupported")
    token = ciphertext[len(_CIPHERTEXT_PREFIX) :]
    try:
        fernet = MultiFernet([Fernet(key) for key in _decrypt_keys(settings)])
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise LLMSettingsCryptoError("llm_settings_ciphertext_invalid") from exc


def last4(api_key: str) -> str:
    return api_key[-4:] if len(api_key) >= 4 else api_key
