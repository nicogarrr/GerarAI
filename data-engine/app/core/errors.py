"""Sanitized error details for HTTP responses.

Internal exception text must never reach API clients: it can leak stack
context, SQL fragments, credentials or vendor internals. Instead, the client
gets a generic, status-appropriate message plus a short correlation id; the
full exception is logged server-side keyed by that same id so support can
correlate a user report with the server log.
"""

from __future__ import annotations

import logging
import re
import traceback
import uuid

from app.core.log_redaction import redact_structured, redact_telegram_tokens

logger = logging.getLogger("gerarai.request_errors")

_STATUS_DEFAULTS: dict[int, str] = {
    400: "Invalid request",
    401: "Unauthenticated",
    403: "Forbidden",
    404: "Resource not found",
    409: "Conflicting state",
    422: "Invalid request",
    424: "Upstream dependency failed",
    429: "Rate limited by upstream provider",
    500: "Internal server error",
    502: "Upstream error",
    503: "Service unavailable",
}

# Credenciales de proveedor en query string (?token=, ?apikey=, ?api_key=...).
# Los clientes de mercado (Finnhub, FMP, AlphaVantage, TwelveData) las llevan
# ahi, y httpx/fetch meten la URL completa en el texto de sus excepciones, de
# modo que sin esto la key del servidor acaba en el log y a veces en la
# respuesta. Se aplica tambien al log: el log no es un sitio seguro.
_SECRET_QUERY_RE = re.compile(
    r"(?i)\b(token|apikey|api_key|api-key|access_token|secret_key|signature|sig)=([^&\s\"'<>]+)"
)

# Credenciales en userinfo de URL (esquema://usuario:password@host): un DSN
# de Redis o Postgres lleva la password ahi, y el traceback de un fallo de
# conexion a cache/broker la muestra entera. El usuario se conserva porque
# no es secreto y ayuda a correlacionar.
_USERINFO_RE = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+):([^@\s/]+)@"
)

# Pares clave=valor de passwords en textos de error ("password=hunter2" en
# un fallo de conexion a base de datos). token/apikey/... ya los cubre
# _SECRET_QUERY_RE; esto cierra el resto de nombres habituales. Idempotente:
# REDACTED no contiene '=' ni caracteres excluidos, re-aplicar no cambia nada.
_SECRET_KV_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|private_key|client_secret)=([^\s&\"'<>]+)"
)


def redact_secrets(text: str) -> str:
    """Redacta credenciales: pares de query, userinfo de URL y password=.

    Despues aplica las mascaras estructuradas del filtro de logs (claves en
    dicts/JSON, variables con prefijo, credenciales con forma de proveedor): esto es lo que
    viaja en el traceback del seguimiento de errores.
    """
    return redact_structured(
        _SECRET_KV_RE.sub(
            r"\1=REDACTED",
            _SECRET_QUERY_RE.sub(
                r"\1=REDACTED", _USERINFO_RE.sub(r"\1:REDACTED@", redact_telegram_tokens(text))
            ),
        )
    )


def safe_detail(exc: Exception, status_code: int) -> str:
    """Log ``exc`` server-side and return a generic client-safe detail.

    The returned message carries only the correlation id — never the raw
    exception text — so callers can replace ``detail=str(exc)``-style raises
    directly. The log line is redacted too, traceback incluido: un traceback
    es justo el caso en el que una URL de proveedor con su key aparece en el
    último frame (``httpx`` la incluye en el mensaje de HTTPStatusError).
    """
    ref = uuid.uuid4().hex[:12]
    logger.error(
        "request_error ref=%s status=%s type=%s\n%s",
        ref,
        status_code,
        type(exc).__name__,
        redact_secrets("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
    )
    base = _STATUS_DEFAULTS.get(status_code, "Request failed")
    return f"{base} (ref: {ref})"




def exc_summary(exc: BaseException) -> str:
    """``TipoError: detalle`` redactado, para logs de dependencias caídas.

    Los 503 fail-closed (rate limit, nonces) se registran sin traceback: el
    texto de la excepción de redis/httpx puede llevar un DSN con credenciales,
    así que pasa por :func:`redact_secrets` igual que los logs de request_error.
    """
    cause = exc.__cause__ or exc
    return f"{type(cause).__name__}: {redact_secrets(str(cause))}"


def ticker_from_path(path: str) -> str | None:
    """Ticker de rutas ``/api/companies/<ticker>/...`` para logs de diagnóstico.

    La ficha dispara su lectura en ráfaga sobre esas rutas; un 5xx sin el
    ticker en el log no se puede acotar a una empresa.
    """
    parts = path.split("/")
    if len(parts) >= 4 and parts[1] == "api" and parts[2] == "companies" and parts[3]:
        return parts[3]
    return None

MSG_VALUE_OUT_OF_RANGE = "Valor fuera de rango para este campo."


def is_db_value_out_of_range(exc: BaseException) -> bool:
    """True si la excepción es un valor de cliente que la BD no puede representar.

    - Postgres: ``sqlalchemy.exc.DataError`` (``bigint out of range``, texto más
      largo que la columna, valor numérico inválido...).
    - SQLite: ``OverflowError`` al enlazar un entero > 2**63-1 dentro de
      SQLAlchemy. Un OverflowError de cálculo (math, float) NO cuenta: ese sigue
      siendo un 500, porque es un bug nuestro y no entrada inválida.
    """
    from sqlalchemy.exc import DataError

    if isinstance(exc, DataError):
        return True
    if isinstance(exc, OverflowError):
        tb = exc.__traceback__
        while tb is not None:
            module = tb.tb_frame.f_globals.get("__name__", "")
            if isinstance(module, str) and module.startswith("sqlalchemy."):
                return True
            tb = tb.tb_next
    return False
