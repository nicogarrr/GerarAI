"""Redaccion de secretos en logs.

Los proveedores de datos reciben la clave en la query string (``apikey=``,
``token=``...). El logger INFO de httpx imprime la URL completa y las excepciones
de httpx la incluyen en su mensaje, asi que la clave acabaria legible en
``docker logs``. El filtro se instala en TODOS los handlers (los existentes y los
que se creen despues) para cubrir mensaje, args y excepcion/stack renderizados,
sea cual sea el logger de origen.
"""
from __future__ import annotations

import logging
import re

_SECRET_KEYS = (
    "apikey", "api_key", "api-key", "api_token", "key", "token", "access_token",
    "access_key", "auth_token", "refresh_token", "private_token", "app_key",
    "auth", "authorization", "secret", "client_secret", "password", "passwd", "pwd",
    "signature", "sig", "x-api-key", "x-auth-token",
)
_KEYS = "|".join(re.escape(k) for k in sorted(_SECRET_KEYS, key=len, reverse=True))
# ?apikey=VALOR / &token=VALOR (el valor llega hasta &, espacio, comilla o fin).
_QUERY_RE = re.compile(rf"(?i)([?&;](?:{_KEYS})=)[^&\s'\"<>)]+")
# Cabeceras / pares "key: valor" o "key=valor" fuera de una URL, incl. Bearer/Basic.
_HEADER_RE = re.compile(
    rf"(?i)\b((?:{_KEYS})\s*[:=]\s*)(?:(?:bearer|basic)\s+)?[^\s,;'\"&)]+"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_USERINFO_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")

# Token de la ruta del feed ICS (/api/calendar/feed/gfc_<token>.ics): el secreto va
# en el PATH, no en la query, y uvicorn.access lo imprime. Se enmascara el token
# conservando metodo, ruta, estado e IP para que el log siga siendo util.
_FEED_TOKEN_RE = re.compile(r"(?i)(/api/calendar/feed/)gfc_[A-Za-z0-9_-]+(\.ics)?")
_GFC_RE = re.compile(r"\bgfc_[A-Za-z0-9_-]{16,}")

# Telegram embeds bot credentials in URL path segments, including /file/bot.
# Match the credential shape on any configured API host, not just api.telegram.org.
_TELEGRAM_TOKEN_RE = re.compile(r"(?i)(/bot)[0-9]+(?::|%3a)[A-Za-z0-9_-]+")


REDACTED = "[REDACTED]"


_ALREADY = {"redacted", "[redacted]", "***"}


def _mask(match: re.Match[str]) -> str:
    # Idempotente: un valor ya enmascarado por otra capa se deja como esta.
    tail = match.group(0)[len(match.group(1)):]
    return match.group(0) if tail.lower() in _ALREADY else match.group(1) + REDACTED


def redact_telegram_tokens(text: str) -> str:
    """Remove bot path credentials while retaining the endpoint for diagnosis."""
    return _TELEGRAM_TOKEN_RE.sub(lambda m: m.group(1) + REDACTED, text)


def redact(text: str) -> str:
    text = redact_telegram_tokens(text)
    text = _FEED_TOKEN_RE.sub(lambda m: m.group(1) + REDACTED + (m.group(2) or ""), text)
    text = _GFC_RE.sub(REDACTED, text)
    text = _QUERY_RE.sub(_mask, text)
    text = _USERINFO_RE.sub(lambda m: m.group(1) + REDACTED + "@", text)
    text = _BEARER_RE.sub(lambda m: m.group(1) + " " + REDACTED, text)
    return _HEADER_RE.sub(_mask, text)


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Los args se enmascaran EN SU SITIO conservando la estructura: el
        # formateador de uvicorn.access desempaqueta 5 args
        # (cliente, metodo, ruta, version, estado); vaciarlos romperia la linea.
        if isinstance(record.args, tuple) and record.args:
            # nosemgrep: gerarai-broad-except-pass -- el redactor de logs nunca puede romper el propio logging
            try:
                masked = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
                if masked != record.args:
                    record.args = masked
            except Exception:  # noqa: BLE001
                pass
        try:
            message = record.getMessage()
        except Exception:  # un record roto no debe romper el logging
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        if record.exc_info:
            try:
                rendered = logging.Formatter().formatException(record.exc_info)
            except Exception:
                rendered = ""
            if rendered:
                record.exc_text = redact(rendered)
                record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


_FILTER = SecretRedactingFilter()
_installed = False


def install() -> None:
    """Idempotente: filtra handlers existentes y futuros."""
    global _installed
    if _installed:
        return
    _installed = True
    original_init = logging.Handler.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_init(self, *args, **kwargs)
        self.addFilter(_FILTER)

    logging.Handler.__init__ = patched_init  # type: ignore[method-assign]
    for ref in list(logging._handlerList):  # noqa: SLF001 - no hay API publica
        handler = ref()
        if handler is not None and _FILTER not in handler.filters:
            handler.addFilter(_FILTER)
