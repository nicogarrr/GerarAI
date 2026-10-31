"""Barrido de bypass de auth: toda ruta privada exige firma.

Recorre TODAS las rutas registradas en la app (no una lista a mano) y llama a
cada una sin firma, con firma caducada, con firma de otra ruta y con firma de
otro método. Solo las rutas públicas declaradas abajo pueden responder sin
401. Una ruta nueva que olvide ``private_dependencies`` rompe este test.
"""

from __future__ import annotations

import re
import time

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.csrf import generate_csrf_token
from tests.auth_helpers import auth_settings, bound_headers

SECRET = "auth-sweep-secret-with-at-least-32-characters!!"

# Públicas a propósito (ver main.py): raíz y health, feed ICS con token en la URL,
# relay de Telegram con su propia prueba HMAC y el esquema OpenAPI en test.
PUBLIC = (
    re.compile(r"^/$"),
    re.compile(r"^/api/health"),
    re.compile(r"^/health"),
    # Emite tokens CSRF: público por diseño (el frontend lo pide antes de mutar).
    re.compile(r"^/api/csrf-token$"),
    # Alias del mismo handler que /api/health/data-sources (health es público
    # a propósito): expone idéntica lectura local de estado de fuentes.
    re.compile(r"^/api/data-sources$"),
    re.compile(r"^/api/calendar/feed/\{filename\}$"),
    re.compile(r"^/api/telegram/"),
    re.compile(r"^/(openapi\.json|docs|redoc)"),
)


def _private_routes():
    # El esquema OpenAPI enumera todas las rutas incluidas (los routers
    # incluidos se resuelven de forma perezosa y no aparecen en app.routes).
    for path, operations in main.app.openapi()["paths"].items():
        if any(pattern.search(path) for pattern in PUBLIC):
            continue
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                yield method.upper(), path


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _csrf(method: str) -> dict[str, str]:
    """Token CSRF válido en métodos mutantes, como hace el frontend.

    El middleware CSRF (VAL-SEC-001) corre antes del routing y responde 403 a
    todo mutante sin token, así que sin él el barrido mediría el middleware y
    no la auth: una ruta mutante que olvidara ``private_dependencies`` se
    escondería detrás de ese 403. Con token válido la petición llega a la capa
    de auth y debe responder 401.
    """
    if method in {"GET", "HEAD", "OPTIONS"}:
        return {}
    return {"X-CSRF-Token": generate_csrf_token()}


ROUTES = sorted(set(_private_routes()))


@pytest.fixture(scope="module")
def client():
    patcher = pytest.MonkeyPatch()
    # El limitador de fallos de auth devolvería 429 tras unas decenas de 401
    # seguidos desde la misma IP; aquí cada ruta debe responder su propio 401.
    from app.core import rate_limit

    async def _no_failures(*_args, **_kwargs):
        return 0

    patcher.setattr(rate_limit, "_count_hits", _no_failures)
    # Los ~1.500 401 de este barrido se registran igualmente: en un almacén
    # propio, para no dejar la IP del TestClient bloqueada (429) a los tests
    # que corran después en el mismo worker.
    patcher.setattr(rate_limit, "_local_hits", {})
    patcher.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    yield TestClient(main.app, raise_server_exceptions=False)
    patcher.undo()


def test_sweep_covers_the_app():
    assert len(ROUTES) > 250


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=[f"{m} {p}" for m, p in ROUTES])
def test_private_route_rejects_unsigned_and_misbound_requests(client, method, path):
    url = _concrete(path)

    csrf = _csrf(method)

    unsigned = client.request(method, url, headers=csrf)
    assert unsigned.status_code == 401, (method, url, unsigned.status_code, unsigned.text[:200])

    expired = bound_headers(
        SECRET, "sweep-tenant", "sweep-user", method=method, path=url,
        timestamp=str(int(time.time()) - 3600),
    )
    response = client.request(method, url, headers={**expired, **csrf})
    assert response.status_code == 401, ("expired", method, url, response.status_code)

    other_path = bound_headers(SECRET, "sweep-tenant", "sweep-user", method=method, path="/api/health")
    response = client.request(method, url, headers={**other_path, **csrf})
    assert response.status_code == 401, ("other path", method, url, response.status_code)

    other_method = "POST" if method == "GET" else "GET"
    wrong_method = bound_headers(SECRET, "sweep-tenant", "sweep-user", method=other_method, path=url)
    response = client.request(method, url, headers={**wrong_method, **csrf})
    assert response.status_code == 401, ("other method", method, url, response.status_code)

    forged = bound_headers("x" * 48, "sweep-tenant", "sweep-user", method=method, path=url)
    response = client.request(method, url, headers={**forged, **csrf})
    assert response.status_code == 401, ("forged secret", method, url, response.status_code)
