"""Idioma de generación por petición (chat, tesis, narrativas, errores visibles).

Regla de oro: con el flag ``I18N_GENERATION_ENABLED`` apagado (defecto) TODO se
genera en español, byte a byte como antes del i18n: mismos prompts, mismos
validadores y mismos ``detail=`` de HTTPException. El flag solo abre la puerta
a que UNA cabecera firmada fije el idioma de la petición.

Origen de la preferencia: el puente frontend -> data-engine reenvía la cookie
``gerarai_locale`` como cabecera ``X-GerarAI-Language`` (es/en) dentro del
mismo canal firmado HMAC que ya autentica tenant y usuario. Sin cabecera, o
con un valor que no es es/en, la petición genera en español. No hay tercer
idioma: ``SUPPORTED_LANGUAGES`` es cerrado a propósito.

La preferencia vive en dos sitios a la vez, porque la generación corre en
hilos y puentes donde el contextvar no siempre llega:

- un contextvar (rápido, para servicios que corren en la petición);
- ``db.info["language"]`` (para servicios que reciben la sesión y puentean
  hilos propios, como el chat: ``chat.py`` copia ``db.info`` al hilo worker).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar

from fastapi import Request

from app.core.config import get_settings

SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "en")
DEFAULT_LANGUAGE = "es"

#: Cabecera (ya dentro del canal firmado) con el idioma elegido por el
#: usuario. El puente la construye desde la cookie `gerarai_locale`.
LANGUAGE_HEADER = "x-gerarai-language"

_request_language: ContextVar[str] = ContextVar(
    "gerarai_request_language", default=DEFAULT_LANGUAGE
)


def resolve_language(value: str | None) -> str:
    """Normaliza una preferencia bruta ("en-US", "EN", "es_ES") a es/en.

    Todo lo no soportado cae al español por defecto: nunca se genera en un
    idioma a medias por una cabecera rara.
    """
    if not value:
        return DEFAULT_LANGUAGE
    code = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def language_enabled() -> bool:
    """True solo si el operador activó la generación multidioma."""
    return bool(get_settings().i18n_generation_enabled)


def current_language() -> str:
    """Idioma de generación de la petición (o del scope) actual."""
    if not language_enabled():
        return DEFAULT_LANGUAGE
    return _request_language.get()


def set_language_scope(language: str):
    """Fija el idioma del contexto actual; devuelve el token para reponerlo.

    Pensado para workers y jobs: ``token = set_language_scope("en")`` ...
    ``_request_language.reset(token)``. Las rutas no lo usan: su idioma lo
    fija la dependencia ``bind_request_language``.
    """
    return _request_language.set(resolve_language(language))


def reset_language_scope(token) -> None:
    _request_language.reset(token)


def language_from_db(db) -> str:
    """Idioma guardado en la sesión (lo puso ``get_db`` al abrirla)."""
    if not language_enabled():
        return DEFAULT_LANGUAGE
    info = getattr(db, "info", None) or {}
    return resolve_language(info.get("language"))


def tenant_stored_language(db) -> str | None:
    """Preferencia persistida del tenant (metadata["language"]) o None.

    La escribe PUT /api/settings/language y la leen los flujos sin cabecera:
    trabajos de fondo (workers), que no tienen peticion.
    """
    info = getattr(db, "info", None) or {}
    if info.get("tenant_id") is None:
        return None
    try:
        from sqlalchemy import select

        from app.models import Tenant

        tenant = db.scalar(select(Tenant).where(Tenant.id == info["tenant_id"]))
    except Exception:  # noqa: BLE001 - sin preferencia legible no se bloquea nada
        return None
    if tenant is None:
        return None
    meta = tenant.metadata_ or {}
    raw = meta.get("language")
    if not raw:
        return None
    language = resolve_language(str(raw))
    return language if language in SUPPORTED_LANGUAGES else None


def generation_language(db=None) -> str:
    """Idioma efectivo de generacion: peticion (contextvar), sesion o tenant.

    Con el flag apagado es siempre "es". Con el flag encendido manda la
    cabecera de la peticion; si no la hay (workers), la preferencia guardada
    del tenant; si tampoco, espanol.
    """
    if not language_enabled():
        return DEFAULT_LANGUAGE
    scoped = _request_language.get()
    if scoped != DEFAULT_LANGUAGE:
        return scoped
    if db is not None:
        from_db = language_from_db(db)
        if from_db != DEFAULT_LANGUAGE:
            return from_db
        stored = tenant_stored_language(db)
        if stored is not None:
            return stored
    return DEFAULT_LANGUAGE


async def bind_request_language(request: Request) -> AsyncIterator[None]:
    """Dependencia de router: fija el idioma de la petición desde la cabecera.

    Con el flag apagado no lee ni la cabecera: el contexto queda en español,
    que es además el valor por defecto del contextvar.
    """
    language = DEFAULT_LANGUAGE
    if language_enabled():
        language = resolve_language(request.headers.get(LANGUAGE_HEADER))
    token = _request_language.set(language)
    try:
        yield
    finally:
        _request_language.reset(token)
