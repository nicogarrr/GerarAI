"""Regresion F12: RawBodyMiddleware no debe abortar respuestas en streaming.

El receive de replay devolvia un "http.disconnect" fabricado en la segunda
llamada; StreamingResponse lo interpreta como cliente colgado y cancela el
cuerpo: 200 con 0 bytes (rompia /api/export y las descargas de tesis).
"""

import io

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from app.core.raw_body import RawBodyMiddleware

DEFAULT_LIMIT = 10 * 1024 * 1024


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RawBodyMiddleware)

    @app.get("/stream")
    def stream():
        return StreamingResponse(io.BytesIO(b"type,date\r\nt,2026-01-01\r\n"), media_type="text/csv")

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return JSONResponse({"len": len(body)})

    return app


def test_streaming_response_survives_raw_body_middleware():
    client = TestClient(_app())
    response = client.get("/stream")
    assert response.status_code == 200
    assert response.content == b"type,date\r\nt,2026-01-01\r\n"


def test_request_body_still_replays():
    client = TestClient(_app())
    response = client.post("/echo", content=b"payload-bytes")
    assert response.status_code == 200
    assert response.json() == {"len": len(b"payload-bytes")}



def test_single_chunk_body_over_limit_rejected():
    """Un body de un solo chunk tambien debe respetar el limite."""
    client = TestClient(_app())
    response = client.post("/echo", content=b"x" * (DEFAULT_LIMIT + 1))
    assert response.status_code == 413


def test_multi_chunk_body_over_limit_rejected():
    """Muchos chunks pequeños que en total superan el limite -> 413."""
    client = TestClient(_app())
    chunks = [b"y" * (DEFAULT_LIMIT // 2), b"y" * (DEFAULT_LIMIT // 2), b"y"]
    response = client.post("/echo", content=iter(chunks))
    assert response.status_code == 413


def test_body_exactly_at_limit_accepted():
    client = TestClient(_app())
    response = client.post("/echo", content=b"z" * DEFAULT_LIMIT)
    assert response.status_code == 200
    assert response.json() == {"len": DEFAULT_LIMIT}


def test_per_prefix_limit_lets_document_uploads_through():
    app = FastAPI()
    app.add_middleware(
        RawBodyMiddleware,
        max_body_bytes_by_prefix={"/api/knowledge/documents/upload": 16 * 1024 * 1024},
    )

    @app.post("/api/knowledge/documents/upload")
    async def upload(request: Request):
        body = await request.body()
        return JSONResponse({"len": len(body)})

    @app.post("/api/other")
    async def other(request: Request):
        body = await request.body()
        return JSONResponse({"len": len(body)})

    client = TestClient(app)
    payload = b"x" * (12 * 1024 * 1024)  # 12MB: entre 10 y 16
    response = client.post("/api/knowledge/documents/upload", content=payload)
    assert response.status_code == 200
    assert response.json()["len"] == len(payload)
    # El resto de rutas siguen con el tope global de 10MB:
    response = client.post("/api/other", content=payload)
    assert response.status_code == 413


def test_sources_ingest_file_route_uses_document_limit():
    """/api/sources/documents/ingest-file valida 15MB en la ruta; el
    middleware debe dejar pasar ese rango (mas overhead multipart)."""
    app = FastAPI()
    app.add_middleware(
        RawBodyMiddleware,
        max_body_bytes_by_prefix={"/api/sources/documents/ingest-file": 16 * 1024 * 1024},
    )

    @app.post("/api/sources/documents/ingest-file")
    async def ingest(request: Request):
        body = await request.body()
        return JSONResponse({"len": len(body)})

    client = TestClient(app)
    payload = b"x" * (12 * 1024 * 1024)  # 12MB: entre 10 y 16
    response = client.post("/api/sources/documents/ingest-file", content=payload)
    assert response.status_code == 200
    assert response.json()["len"] == len(payload)
    response = client.post("/api/sources/documents/ingest-file", content=b"x" * (17 * 1024 * 1024))
    assert response.status_code == 413


def test_per_prefix_limit_still_rejects_above_its_cap():
    app = FastAPI()
    app.add_middleware(
        RawBodyMiddleware,
        max_body_bytes_by_prefix={"/api/knowledge/documents/upload": 16 * 1024 * 1024},
    )

    @app.post("/api/knowledge/documents/upload")
    async def upload(request: Request):
        body = await request.body()
        return JSONResponse({"len": len(body)})

    client = TestClient(app)
    payload = b"x" * (17 * 1024 * 1024)
    response = client.post("/api/knowledge/documents/upload", content=payload)
    assert response.status_code == 413


def _unsigned_cap_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RawBodyMiddleware, max_unsigned_body_bytes=1024)

    @app.post("/echo")
    async def echo(request: Request):
        return JSONResponse({"len": len(await request.body())})

    return app


def test_unsigned_body_over_small_cap_rejected():
    client = TestClient(_unsigned_cap_app())
    assert client.post("/echo", content=b"x" * 2048).status_code == 413
    assert client.post("/echo", content=b"x" * 512).status_code == 200


def test_signed_body_over_small_cap_accepted():
    client = TestClient(_unsigned_cap_app())
    response = client.post(
        "/echo", content=b"x" * 2048, headers={"x-cavaai-signature": "abc"}
    )
    assert response.status_code == 200
    assert response.json() == {"len": 2048}
