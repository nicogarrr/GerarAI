"""Firma de identidad Research OS compartida por los tests de API.

``bound_headers`` firma ligada al request (nonce + metodo + ruta + hash del
cuerpo): vale contra el backend leniente actual y contra el estricto
(research_auth_strict_binding=True). ``legacy_headers`` solo existe para los
tests que ejercitan deliberadamente el modo legacy; esos tests deben modelar
``research_auth_strict_binding=False`` de forma explicita en sus settings.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from uuid import uuid4

from app.core.auth import body_digest, sign_research_identity


def bound_headers(
    secret: str,
    tenant: str,
    user: str,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Cabeceras X-CavaAI-* con firma ligada. `path` sin query string."""
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    nonce = uuid4().hex if nonce is None else nonce
    body_hash = body_digest(body)
    signature = sign_research_identity(
        secret,
        tenant_id=tenant,
        user_id=user,
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        body_hash=body_hash,
    )
    return {
        "X-CavaAI-Tenant": tenant,
        "X-CavaAI-User": user,
        "X-CavaAI-Timestamp": timestamp,
        "X-CavaAI-Signature": signature,
        "X-CavaAI-Nonce": nonce,
        "X-CavaAI-Method": method.upper(),
        "X-CavaAI-Path": path,
        "X-CavaAI-Body-Hash": body_hash,
    }


def legacy_headers(
    secret: str, tenant: str, user: str, *, timestamp: str | None = None
) -> dict[str, str]:
    """Firma legacy (tenant:user:timestamp), solo para tests del modo leniente."""
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    return {
        "X-CavaAI-Tenant": tenant,
        "X-CavaAI-User": user,
        "X-CavaAI-Timestamp": timestamp,
        "X-CavaAI-Signature": sign_research_identity(
            secret, tenant_id=tenant, user_id=user, timestamp=timestamp
        ),
    }


def auth_settings(
    *,
    strict: bool,
    secret: str,
    app_env: str = "test",
    required: bool = True,
    max_age_seconds: int = 300,
) -> SimpleNamespace:
    """Settings explicitos sobre el binding estricto (el default importa)."""
    return SimpleNamespace(
        app_env=app_env,
        is_production=app_env.lower() in {"production", "prod"},
        research_auth_required=required,
        research_auth_secret=secret,
        research_auth_max_age_seconds=max_age_seconds,
        research_auth_strict_binding=strict,
        redis_url="redis://127.0.0.1:1/0",
    )


def signed_request(
    client,
    secret: str,
    tenant: str,
    user: str,
    method: str,
    path: str,
    *,
    json_body=None,
    params: dict | None = None,
    headers: dict | None = None,
):
    """Petición firmada ligada al request contra un TestClient.

    `path` es solo la ruta (la query va en `params`): el servidor verifica la
    firma contra request.url.path. El cuerpo se serializa aqui mismo para que
    el hash cubra exactamente los bytes enviados.
    """
    body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
    signed = bound_headers(secret, tenant, user, method=method, path=path, body=body)
    if json_body is not None:
        signed["Content-Type"] = "application/json"
    if headers:
        signed.update(headers)
    kwargs: dict = {"headers": signed}
    if json_body is not None:
        kwargs["content"] = body
    if params:
        kwargs["params"] = params
    return client.request(method.upper(), path, **kwargs)


def csrf_client(app=None, **kwargs):
    """TestClient con un token CSRF válido por defecto, como el frontend.

    El middleware CSRF (VAL-SEC-001) corre antes del routing y responde 403 a
    todo mutante sin token. Los tests que miden auth o comportamiento de ruta
    (no el middleware) lo usan para que la petición llegue a la capa que
    quieren medir. Quien mide el middleware (test_csrf_protection) o las
    rutas públicas sigue creando su TestClient a pelo: este helper es una
    función opt-in, no un fixture autouse.
    """
    from fastapi.testclient import TestClient

    import main as _main
    from app.core.csrf import generate_csrf_token

    client = TestClient(app if app is not None else _main.app, **kwargs)
    client.headers.update({"X-CSRF-Token": generate_csrf_token()})
    return client
