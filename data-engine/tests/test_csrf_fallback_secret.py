"""El secreto CSRF de respaldo nunca es una constante publica del repo.

Antes del fix, sin RESEARCH_AUTH_SECRET configurado (solo posible fuera de
produccion) el HMAC de los tokens CSRF usaba la cadena publica
"gerarai-csrf-default-secret-key-32chars": cualquiera podia firmar tokens
validos. Ahora el respaldo es aleatorio por proceso.
"""

from __future__ import annotations

import hashlib
import hmac

from app.core import csrf
from app.core.csrf import generate_csrf_token, validate_csrf_token


def _forge_token_with_public_constant() -> str:
    """Token firmado con la antigua constante publica del repo."""
    secret = b"gerarai-csrf-default-secret-key-32chars"
    salt, timestamp = "00" * 16, "9999999999"  # expirado a proposito? no: fresco
    import time

    timestamp = str(int(time.time()))
    payload = f"{salt}:{timestamp}".encode()
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{salt}.{timestamp}.{signature}"


def test_fallback_secret_is_not_the_public_constant():
    assert csrf._get_csrf_secret() != "gerarai-csrf-default-secret-key-32chars"
    assert len(csrf._get_csrf_secret()) >= 32


def test_fallback_secret_is_stable_within_process():
    assert csrf._get_csrf_secret() == csrf._get_csrf_secret()


def test_token_forged_with_public_constant_is_rejected():
    forged = _forge_token_with_public_constant()
    assert validate_csrf_token(forged) is False


def test_generated_token_roundtrip_validates():
    assert validate_csrf_token(generate_csrf_token()) is True
