"""Signed identity bridge between the Next.js server and Research OS.

The browser never creates these headers. Next.js server actions sign the active
Better Auth identity with a shared secret, and FastAPI verifies it before a
tenant-scoped database session is opened.

Hardened payload (anti-replay / anti-tampering):
- every bound signature carries a single-use nonce (Redis ``SET NX EX`` with a
  local TTL-cache fallback) so a captured request cannot be replayed;
- the signature binds tenant, user, timestamp, nonce, HTTP method, request
  path and the SHA-256 of the raw request body, so a signature cannot be
  moved to another endpoint or a tampered body;
- timestamps in the future are rejected outright; the max-age tolerance only
  applies to the past (no ``abs()`` window).

Legacy (unbound) payloads are still accepted outside production so existing
local/test callers keep working; production requires bound signatures.
"""

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.errors import exc_summary, ticker_from_path
from app.core.replay import NonceBackendUnavailable, consume_nonce

logger = logging.getLogger(__name__)

EMPTY_BODY_HASH = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class ResearchPrincipal:
    user_id: str
    tenant_external_id: str


def signature_payload(
    *,
    tenant_id: str,
    user_id: str,
    timestamp: str,
    nonce: str | None = None,
    method: str | None = None,
    path: str | None = None,
    body_hash: str | None = None,
) -> bytes:
    bound = (nonce, method, path, body_hash)
    if all(part is None for part in bound):
        # Legacy payload: kept for local/test callers only.
        return f"{tenant_id}:{user_id}:{timestamp}".encode()
    if any(part is None for part in bound):
        raise ValueError(
            "nonce, method, path and body_hash must be provided together"
        )
    return (
        f"{tenant_id}:{user_id}:{timestamp}:{nonce}:"
        f"{(method or '').upper()}:{path}:{body_hash}"
    ).encode()


def sign_research_identity(
    secret: str,
    *,
    tenant_id: str,
    user_id: str,
    timestamp: str,
    nonce: str | None = None,
    method: str | None = None,
    path: str | None = None,
    body_hash: str | None = None,
) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        signature_payload(
            tenant_id=tenant_id,
            user_id=user_id,
            timestamp=timestamp,
            nonce=nonce,
            method=method,
            path=path,
            body_hash=body_hash,
        ),
        hashlib.sha256,
    ).hexdigest()


def body_digest(body: bytes) -> str:
    """SHA-256 hexdigest of the raw request body bytes."""
    return hashlib.sha256(body).hexdigest()


def _strict_binding(settings) -> bool:
    """Bound signatures are mandatory in production (and when forced).

    ``research_auth_strict_binding`` es ahora un campo real de Settings: antes
    solo se leia por getattr sobre un objeto que no lo tenia, y como
    ``model_config`` es ``extra="ignore"`` la variable de entorno se descartaba
    en silencio, asi que el getattr devolvia False para siempre y el unico
    disparador era ``is_production``.
    """
    return bool(getattr(settings, "is_production", False)) or bool(
        getattr(settings, "research_auth_strict_binding", False)
    )


# Mensajes 401 en español (los ve el usuario cuando la sesión no llega bien
# firmada al motor de datos). El frontend decide por el código 401, no por el texto.
MSG_IDENTITY_REQUIRED = "Tu sesión no es válida o ha caducado. Vuelve a iniciar sesión."
MSG_INVALID_SIGNATURE = "La firma de tu sesión no es válida. Vuelve a iniciar sesión."
MSG_INVALID_TIMESTAMP = "La hora de la firma de tu sesión no es válida. Vuelve a iniciar sesión."
MSG_EXPIRED = "Tu sesión ha caducado. Vuelve a iniciar sesión."
MSG_REQUEST_MISMATCH = "La firma de tu sesión no corresponde a esta petición."
MSG_BOUND_SIGNATURE_REQUIRED = "Falta la firma de la petición. Vuelve a iniciar sesión."
MSG_INVALID_IDENTITY = "Tu sesión no es válida. Vuelve a iniciar sesión."
MSG_REPLAYED = "Esta petición ya se había usado. Vuelve a intentarlo."


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail
    )


async def get_research_principal(
    request: Request,
    x_cavaai_user: str | None = Header(default=None),
    x_cavaai_tenant: str | None = Header(default=None),
    x_cavaai_timestamp: str | None = Header(default=None),
    x_cavaai_signature: str | None = Header(default=None),
    x_cavaai_nonce: str | None = Header(default=None),
    x_cavaai_method: str | None = Header(default=None),
    x_cavaai_path: str | None = Header(default=None),
    x_cavaai_body_hash: str | None = Header(default=None),
) -> ResearchPrincipal | None:
    settings = get_settings()
    required = settings.research_auth_required or getattr(
        settings, "is_production", False
    )
    supplied = all(
        [x_cavaai_user, x_cavaai_tenant, x_cavaai_timestamp, x_cavaai_signature]
    )
    if not supplied:
        if required:
            raise _unauthorized(MSG_IDENTITY_REQUIRED)
        return None

    research_auth_secret = settings.research_auth_secret
    if not research_auth_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research authentication is not configured",
        )

    # compare_digest(str, str) raises TypeError for non-ASCII input.
    # Only lowercase hex SHA-256 signatures are emitted by the identity bridge.
    if re.fullmatch(r"[0-9a-f]{64}", x_cavaai_signature or "") is None:
        raise _unauthorized(MSG_INVALID_SIGNATURE)

    try:
        issued_at = int(x_cavaai_timestamp or "0")
    except ValueError as exc:
        raise _unauthorized(MSG_INVALID_TIMESTAMP) from exc

    now = int(time.time())
    # Tolerancia solo hacia el pasado: un timestamp futuro nunca es valido.
    if issued_at > now:
        raise _unauthorized(MSG_INVALID_TIMESTAMP)
    max_age = settings.research_auth_max_age_seconds
    if now - issued_at > max_age:
        raise _unauthorized(MSG_EXPIRED)

    bound_parts = (x_cavaai_nonce, x_cavaai_method, x_cavaai_path, x_cavaai_body_hash)
    uses_bound_payload = any(part is not None for part in bound_parts)
    if uses_bound_payload:
        if any(part is None for part in bound_parts):
            raise _unauthorized(MSG_INVALID_SIGNATURE)
        method = (x_cavaai_method or "").upper()
        path = x_cavaai_path or ""
        if method != request.method.upper() or path != request.url.path:
            raise _unauthorized(
                MSG_REQUEST_MISMATCH
            )
        raw_body = getattr(request.state, "raw_body", None)
        if raw_body is None:
            raw_body = await request.body()
        if (x_cavaai_body_hash or "") != body_digest(raw_body):
            raise _unauthorized(
                MSG_REQUEST_MISMATCH
            )
    elif _strict_binding(settings):
        raise _unauthorized(
            MSG_BOUND_SIGNATURE_REQUIRED
        )

    expected = sign_research_identity(
        research_auth_secret,
        tenant_id=x_cavaai_tenant or "",
        user_id=x_cavaai_user or "",
        timestamp=x_cavaai_timestamp or "",
        nonce=x_cavaai_nonce if uses_bound_payload else None,
        method=x_cavaai_method if uses_bound_payload else None,
        path=x_cavaai_path if uses_bound_payload else None,
        body_hash=x_cavaai_body_hash if uses_bound_payload else None,
    )
    if not hmac.compare_digest(expected, x_cavaai_signature or ""):
        raise _unauthorized(MSG_INVALID_SIGNATURE)

    if not (x_cavaai_user or "").strip() or not (x_cavaai_tenant or "").strip():
        raise _unauthorized(MSG_INVALID_IDENTITY)

    if uses_bound_payload:
        # Consume the nonce only once the signature is fully verified so an
        # attacker cannot burn nonces with forged requests.
        nonce_key = "cavaai:nonce:" + hashlib.sha256(
            f"{x_cavaai_tenant}:{x_cavaai_user}:{x_cavaai_nonce}".encode()
        ).hexdigest()
        # Mismo criterio que el rate limiter (is_local_environment); antes
        # 'dev'/'ci' usaban Redis aqui y local alli.
        local_only = getattr(settings, "is_local_environment", None)
        if local_only is None:
            local_only = getattr(settings, "app_env", "local").lower() in {"local", "test"}
        try:
            fresh = await consume_nonce(
                nonce_key,
                ttl_seconds=max_age + 60,
                redis_url=getattr(settings, "redis_url", "redis://localhost:6379/0"),
                use_redis=not local_only,
                # Production fails closed without Redis (503, like the rate
                # limiter); local/test keeps the in-process fallback.
                allow_local_fallback=not getattr(settings, "is_production", False),
            )
        except NonceBackendUnavailable as exc:
            # Mismo ciego que el rate limiter: sin este log el 503 solo se ve
            # en el access log y no se puede acotar a ruta/ticker.
            logger.warning(
                "auth_nonce_backend_unavailable method=%s path=%s ticker=%s cause=%s",
                request.method,
                request.url.path,
                ticker_from_path(request.url.path) or "-",
                exc_summary(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication backend unavailable",
            ) from exc
        if not fresh:
            raise _unauthorized(MSG_REPLAYED)

    return ResearchPrincipal(
        user_id=(x_cavaai_user or "").strip(),
        tenant_external_id=(x_cavaai_tenant or "").strip(),
    )
