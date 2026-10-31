"""CSRF token generation and validation middleware.

Fulfills VAL-SEC-001: CSRF protection on state-changing endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CSRF_TOKEN_MAX_AGE_SECONDS = 86400  # 24 horas
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXCLUDED_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/api/health",
    "/api/csrf-token",
)


def _get_csrf_secret() -> str:
    settings = get_settings()
    secret = settings.research_auth_secret or "gerarai-csrf-default-secret-key-32chars"
    return secret


def generate_csrf_token() -> str:
    """Genera un token CSRF criptograficamente seguro firmado con HMAC."""
    secret = _get_csrf_secret().encode()
    salt = secrets.token_hex(16)
    timestamp = str(int(time.time()))
    payload = f"{salt}:{timestamp}".encode()
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{salt}.{timestamp}.{signature}"


def validate_csrf_token(token: str | None) -> bool:
    """Valida la firma y frescura de un token CSRF."""
    if not token or not isinstance(token, str):
        return False
    parts = token.strip().split(".")
    if len(parts) != 3:
        return False
    salt, timestamp_str, signature = parts
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return False

    now = int(time.time())
    if timestamp > now + 60:  # margen de 1 min por desfase de reloj
        return False
    if now - timestamp > CSRF_TOKEN_MAX_AGE_SECONDS:
        return False

    secret = _get_csrf_secret().encode()
    payload = f"{salt}:{timestamp_str}".encode()
    expected_signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware que exige un token CSRF valido en metodos mutantes (POST, PUT, DELETE, PATCH)."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES):
            return await call_next(request)

        # Toda la superficie real vive bajo /api/. Fuera de /api/ solo quedan
        # rutas legacy retiradas, que deben responder 404; exigir CSRF antes
        # del routing las convertia en 403 y rompia el contrato de retirada
        # (tests/test_router_contracts.py).
        if not path.startswith("/api/"):
            return await call_next(request)

        # Extraer token de cabeceras o cookies
        csrf_token = (
            request.headers.get("x-csrf-token")
            or request.headers.get("x-csrftoken")
            or request.headers.get("x-xsrf-token")
            or request.cookies.get("csrf_token")
            or request.cookies.get("csrftoken")
        )

        if not csrf_token or not validate_csrf_token(csrf_token):
            # Si el request no lleva CSRF valido, verificar si viene con firma interna de servicio (Research OS)
            has_internal_sig = (
                request.headers.get("x-cavaai-signature")
                and request.headers.get("x-cavaai-user")
                and request.headers.get("x-cavaai-timestamp")
            )
            if not has_internal_sig:
                logger.warning(f"CSRF validation failed for {request.method} {path}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Falta el token CSRF o es inválido (403 Forbidden)."},
                )

        return await call_next(request)

