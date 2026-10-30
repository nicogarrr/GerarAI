"""Envio de errores 500 a un servidor de seguimiento, sin dependencias.

Habla el protocolo «store» de Sentry, que tambien implementa GlitchTip
(autoalojado y gratis): ``ERROR_TRACKING_DSN=https://<clave>@<host>/<proyecto>``.
Sin DSN no hace nada. Garantias:

* nunca rompe ni retrasa la peticion: el envio va en un hilo con timeout corto
  y cualquier fallo se descarta;
* el traceback va redactado (``redact_secrets``), igual que el log; no se envian
  cuerpos, cabeceras ni query strings, solo metodo y ruta;
* limite de envios por minuto y una sola notificacion por firma de error y
  minuto, para que un bucle de 500 no inunde el servidor.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.core.errors import redact_secrets

logger = logging.getLogger("gerarai.error_tracking")

MAX_EVENTS_PER_MINUTE = 30
SEND_TIMEOUT_SECONDS = 3.0

_lock = threading.Lock()
_window_start = 0.0
_window_count = 0
_recent: dict[str, float] = {}


def parse_dsn(dsn: str | None) -> tuple[str, str] | None:
    """(url del endpoint store, cabecera X-Sentry-Auth) o None si el DSN no vale."""
    if not dsn:
        return None
    try:
        parts = urlsplit(dsn.strip())
    except ValueError:
        return None
    project = parts.path.strip("/").rsplit("/", 1)[-1]
    if parts.scheme not in ("https", "http") or not parts.hostname or not parts.username or not project.isdigit():
        return None
    prefix = parts.path.strip("/").rsplit("/", 1)[0] if "/" in parts.path.strip("/") else ""
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    base = f"{parts.scheme}://{host}" + (f"/{prefix}" if prefix else "")
    auth = f"Sentry sentry_version=7, sentry_client=gerarai-min/1.0, sentry_key={parts.username}"
    return f"{base}/api/{project}/store/", auth


def _allow(signature: str, now: float) -> bool:
    global _window_start, _window_count
    with _lock:
        if now - _window_start >= 60:
            _window_start, _window_count = now, 0
            for key, seen in list(_recent.items()):
                if now - seen >= 60:
                    del _recent[key]
        if _window_count >= MAX_EVENTS_PER_MINUTE or signature in _recent:
            return False
        _window_count += 1
        _recent[signature] = now
        return True


def build_event(exc: BaseException, *, ref: str, method: str | None, path: str | None, environment: str) -> dict:
    frames = traceback.extract_tb(exc.__traceback__)
    last = frames[-1] if frames else None
    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": "python",
        "level": "error",
        "logger": "gerarai.request_errors",
        "environment": environment,
        "tags": {"ref": ref},
        "transaction": f"{method or ''} {path or ''}".strip() or None,
        "exception": {"values": [{
            "type": type(exc).__name__,
            "value": redact_secrets(str(exc))[:500],
            "stacktrace": {"frames": [
                {"filename": f.filename.rsplit("/app/", 1)[-1], "function": f.name, "lineno": f.lineno}
                for f in frames[-30:]
            ]},
        }]},
        "extra": {"traceback": redact_secrets("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))[-8000:]},
        "fingerprint": [type(exc).__name__, last.filename if last else "", str(last.lineno if last else "")],
    }


def _post(url: str, auth: str, event: dict) -> None:
    request = urllib.request.Request(  # noqa: S310 - URL del DSN que fija el operador, no el usuario
        url, data=json.dumps(event, default=str).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Sentry-Auth": auth},
    )
    try:
        with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS):  # noqa: S310
            pass
    except Exception:  # noqa: BLE001 - el seguimiento nunca rompe nada
        logger.warning("error_tracking send failed")


def report_exception(
    exc: BaseException, *, ref: str, method: str | None = None, path: str | None = None,
    settings=None, sender=None,
) -> bool:
    """Envia ``exc`` si hay DSN y el limite lo permite. True si se encolo."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    target = parse_dsn(getattr(settings, "error_tracking_dsn", None))
    if target is None:
        return False
    event = build_event(
        exc, ref=ref, method=method, path=path,
        environment=getattr(settings, "error_tracking_environment", None) or getattr(settings, "app_env", "unknown"),
    )
    if not _allow("|".join(event["fingerprint"]), time.monotonic()):
        return False
    url, auth = target
    send = sender or (lambda: _post(url, auth, event))
    threading.Thread(target=send, name="error-tracking", daemon=True).start()
    return True
