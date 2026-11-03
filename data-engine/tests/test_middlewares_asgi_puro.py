"""Middlewares propios en ASGI puro: mismas cabeceras y mismo CSRF, sin BaseHTTPMiddleware.

BaseHTTPMiddleware crea una tarea y canales en memoria por peticion y reenvia el
cuerpo de la respuesta por ellos; con dos en la pila (CSRF y cabeceras de
seguridad) lo pagaba cada llamada a la API, tambien los GET.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

import main
from app.core.csrf import CSRFMiddleware


def test_ninguno_de_los_middlewares_propios_es_base_http():
    for middleware in main.app.user_middleware:
        assert not (isinstance(middleware.cls, type) and issubclass(middleware.cls, BaseHTTPMiddleware)), (
            middleware
        )
    assert not issubclass(CSRFMiddleware, BaseHTTPMiddleware)


def test_orden_de_la_pila_se_conserva():
    names = [m.cls.__name__ for m in main.app.user_middleware]
    assert names[0] == "SecurityHeadersMiddleware"  # la mas externa, como el decorador
    assert names[-1] == "CSRFMiddleware"  # la mas interna


def _app():
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(main.SecurityHeadersMiddleware)

    @app.get("/x")
    def x():
        return {"ok": True}

    @app.post("/x")
    def px():
        return {"ok": True}

    @app.get("/own")
    def own():
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    return app


def test_cabeceras_de_seguridad_con_setdefault():
    c = TestClient(_app())
    r = c.get("/x")
    assert r.json() == {"ok": True}
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert c.get("/own").headers["x-frame-options"] == "SAMEORIGIN"  # no pisa la de la ruta


def test_csrf_igual_que_antes():
    from app.core.csrf import generate_csrf_token

    c = TestClient(_app())
    r = c.post("/x")
    assert r.status_code == 403
    assert r.json() == {"detail": "Falta el token CSRF o es inválido (403 Forbidden)."}
    assert r.headers["x-frame-options"] == "DENY"  # el 403 tambien lleva cabeceras
    assert c.post("/x", headers={"X-CSRF-Token": generate_csrf_token()}).json() == {"ok": True}
    assert (
        c.post(
            "/x", headers={"x-cavaai-signature": "s", "x-cavaai-user": "u", "x-cavaai-timestamp": "1"}
        ).status_code
        == 200
    )
