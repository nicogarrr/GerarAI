"""Filtro SecretRedactingFilter e instalacion global de app/core/log_redaction.py.

Los tests existentes cubren ``redact()`` como funcion pura; aqui se cubre el
filtro de logging aplicado a LogRecord (args en su sitio, excepciones, stack)
y el ``install()`` que lo cablea en todos los handlers. ``install()`` ya corre
al importar app.core.config en la sesion de tests: es seguro llamarlo de
nuevo porque es idempotente, y cualquier handler creado despues hereda el
filtro por el __init__ parcheado.
"""
from __future__ import annotations

import logging

from app.core import log_redaction
from app.core.log_redaction import REDACTED, SecretRedactingFilter

SECRETO = "sk-proj-SECRETVALOR123456"


def _record(msg: str, args: object = None) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, None)


def test_args_en_tupla_se_enmascaran_en_su_sitio() -> None:
    """uvicorn.access desempaqueta 5 args: la tupla conserva forma y orden."""
    rec = _record("%s %s %s", ("GET", f"/feed?apikey={SECRETO}", 200))
    assert SecretRedactingFilter().filter(rec) is True
    assert isinstance(rec.args, tuple) and len(rec.args) == 3
    assert rec.args[0] == "GET" and rec.args[2] == 200
    assert SECRETO not in rec.args[1] and REDACTED in rec.args[1]


def test_args_sin_secretos_no_se_tocan() -> None:
    rec = _record("%s %s", ("GET", "/api/health"))
    SecretRedactingFilter().filter(rec)
    assert rec.args == ("GET", "/api/health")


def test_record_roto_no_rompe_el_logging() -> None:
    """Un mensaje que no formatea con sus args devuelve True sin lanzar."""
    rec = _record("%d %d", ("no-es-numero",))
    assert SecretRedactingFilter().filter(rec) is True


def test_exc_info_se_renderiza_enmascara_y_se_suelta() -> None:
    try:
        raise RuntimeError(f"fallo llamando a https://h/?token={SECRETO}")
    except RuntimeError:
        import sys

        rec = _record("boom", None)
        rec.exc_info = sys.exc_info()
    SecretRedactingFilter().filter(rec)
    assert rec.exc_info is None
    assert rec.exc_text is not None
    assert SECRETO not in rec.exc_text and REDACTED in rec.exc_text


def test_exc_text_y_stack_info_se_enmascaran() -> None:
    rec = _record("ok", None)
    rec.exc_text = f"Traceback ... api_key={SECRETO}"
    rec.stack_info = f"Stack ... Authorization: Bearer {SECRETO}"
    SecretRedactingFilter().filter(rec)
    assert SECRETO not in rec.exc_text
    assert SECRETO not in rec.stack_info


def test_valor_ya_enmascarado_es_idempotente() -> None:
    rec = _record("GET /feed?apikey=[REDACTED]", None)
    SecretRedactingFilter().filter(rec)
    assert rec.getMessage().count(REDACTED) == 1


def test_install_es_idempotente_y_los_handlers_nuevos_heredan_filtro() -> None:
    log_redaction.install()
    log_redaction.install()
    handler = logging.StreamHandler()
    filtros = [f for f in handler.filters if isinstance(f, SecretRedactingFilter)]
    assert len(filtros) == 1
    handler.close()
