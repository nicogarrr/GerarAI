"""Raw request-body capture for request-signature verification.

FastAPI reads (and may discard) the body before solving dependencies — for
multipart/form routes the raw bytes are consumed by the form parser and a
later ``await request.body()`` raises ``RuntimeError("Stream consumed")``.
This pure-ASGI middleware buffers the body once, replays it downstream so
every consumer sees the same bytes, and exposes the raw bytes on
``request.state.raw_body`` for HMAC body-hash verification.
"""

from __future__ import annotations

from typing import Any


class RawBodyMiddleware:
    def __init__(
        self,
        app,
        max_body_bytes: int = 10 * 1024 * 1024,
        max_body_bytes_by_prefix: dict[str, int] | None = None,
        max_unsigned_body_bytes: int | None = None,
    ):
        self.max_unsigned_body_bytes = max_unsigned_body_bytes
        self.app = app
        self.max_body_bytes = max_body_bytes
        # Limites por prefijo de ruta: la subida de documentos admite 15MB
        # (MAX_DOCUMENT_BYTES) y el tope global de 10MB le daba un 413 seco
        # a documentos legitimos de 10-15MB antes de llegar a la ruta.
        self.max_body_bytes_by_prefix = max_body_bytes_by_prefix or {}

    def _limit_for(self, path: str) -> int:
        limit = self.max_body_bytes
        for prefix, prefix_limit in self.max_body_bytes_by_prefix.items():
            if path.startswith(prefix):
                limit = max(limit, prefix_limit)
        return limit

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(str(scope.get("path") or ""))
        # Un request sin firma no puede llegar a ninguna ruta firmada: no hay
        # motivo para bufferizar 10-16MB de un cliente anonimo antes de que
        # la auth lo rechace. Se le aplica un tope pequeno.
        if self.max_unsigned_body_bytes is not None and not _signed_by_bridge(scope):
            limit = min(limit, self.max_unsigned_body_bytes)
        chunks: list[bytes] = []
        total = 0
        message: dict[str, Any] = await receive()
        while True:
            chunk = message.get("body", b"")
            chunks.append(chunk)
            total += len(chunk)
            # El limite se aplica tras CADA chunk: un body de un solo chunk
            # tambien debe rechazarse si supera el limite de su ruta.
            if total > limit:
                from starlette.responses import JSONResponse

                response = JSONResponse({"detail": "body too large"}, status_code=413)
                await response(scope, receive, send)
                return
            if not message.get("more_body"):
                break
            message = await receive()
        raw_body = b"".join(chunks)

        scope.setdefault("state", {})["raw_body"] = raw_body
        replayed = False

        async def replay_receive() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            # Tras el replay hay que delegar en el receive real: devolver un
            # "http.disconnect" fabricado hace que StreamingResponse crea que
            # el cliente colgo y aborta el cuerpo (200 con 0 bytes - F12,
            # rompia /api/export y las descargas de tesis).
            return await receive()

        await self.app(scope, replay_receive, send)


def _signed_by_bridge(scope: dict) -> bool:
    """True si la peticion puede optar al limite grande de body.

    Antes bastaba con que existiera la cabecera ``X-CavaAI-Signature`` (con
    cualquier valor): un cliente anonimo contra el dominio publico mandaba
    ``X-CavaAI-Signature: x`` y el backend bufferizaba 10-16MB por peticion
    antes de que la auth lo rechazase. Con secreto configurado se exige la
    firma HMAC de cabeceras valida y vigente (la misma comprobacion sin body
    que usa el corte de 401); el body se verifica despues en la auth. Sin
    secreto (desarrollo local) se mantiene la comprobacion de presencia.
    """
    has_header = any(
        name.lower() == b"x-cavaai-signature" and value
        for name, value in scope.get("headers") or []
    )
    if not has_header:
        return False
    from app.core import config
    from app.core.rate_limit import _carries_valid_signature

    settings = config.get_settings()
    if not getattr(settings, "research_auth_secret", None):
        return True
    return _carries_valid_signature(scope, settings)
