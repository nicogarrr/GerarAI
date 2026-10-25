"""One monotonic deadline shared by context, candidates and guard retries."""
from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from functools import wraps

from app.core.config import get_settings
from app.llm.errors import ProviderTransportError

_deadline: ContextVar[float | None] = ContextVar("chat_deadline", default=None)


def remaining_seconds(default: float | None = None) -> float:
    limit = get_settings().chat_total_timeout_seconds if default is None else default
    deadline = _deadline.get()
    remaining = limit if deadline is None else min(limit, deadline - time.monotonic())
    if remaining <= 0:
        raise ProviderTransportError("chat", "timeout", 1)
    return remaining


def bounded_chat(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        # Nested calls keep the original deadline rather than starting 20 s again.
        if _deadline.get() is not None:
            return await fn(*args, **kwargs)
        token = _deadline.set(time.monotonic() + get_settings().chat_total_timeout_seconds)
        try:
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=remaining_seconds())
        finally:
            _deadline.reset(token)
    return wrapped


async def complete_with_deadline(provider, request, **kwargs):
    from app.services.llm_output_guard import complete_guarded
    # El TimeoutError del propio proveedor conserva su tipo; solo el
    # vencimiento del plazo total se convierte en ProviderTransportError.
    task = asyncio.ensure_future(complete_guarded(provider, request, **kwargs))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=remaining_seconds())
    except TimeoutError:
        if task.done() and not task.cancelled():
            raise
        task.cancel()
        raise ProviderTransportError("chat", "timeout", 1) from None
    except asyncio.CancelledError:
        # El plazo del chat (bounded_chat) cancela a quien espera, y shield protege la
        # tarea interna: sin esto la llamada al proveedor sigue en segundo plano hasta
        # terminar y su respuesta se descarta (medido 25-oct: 17,4 s tras vencer el plazo).
        if not task.done():
            task.cancel()
        raise
