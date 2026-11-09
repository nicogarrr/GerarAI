"""Bordes de ``app.core.log_redaction``: fallos internos del filtro y ref muerta.

Lo que cada test demuestra:
- Si enmascarar los args lanza una excepcion, el filtro la traga (107-108) y
  continua: la fase de mensaje redacta el secreto con el redactor real.
  (No se demuestra fail-closed: si ``redact`` fallara siempre, la llamada de
  la fase de mensaje propagaria la excepcion; eso queda fuera de este test.)
- Un mensaje con secreto queda redactado y los args se vacian (115-116).
- Si ``formatException`` falla, ``rendered`` queda vacio y el record conserva
  ``exc_info`` sin ``exc_text`` nuevo (120-121, rama 122->127).
- ``install()`` salta referencias muertas de ``logging._handlerList`` sin
  romperse (rama 151->149).

El estado global tocado por ``install()`` (``Handler.__init__``,
``_installed``, ``_handlerList`` y la lista ``filters`` de cada handler vivo)
se captura antes y se restaura al salir del test.
"""

from __future__ import annotations

import logging
import weakref

from app.core import log_redaction
from app.core.log_redaction import REDACTED, SecretRedactingFilter

SECRETO = "sk-proj-SECRETVALOR123456"


def _record(msg: str, args: object = None) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, None)


def test_args_que_lanzan_al_enmascarar_no_rompen_el_logging(monkeypatch):
    llamadas = []
    real = log_redaction.redact

    def boom_una_vez(texto):
        if not llamadas:
            llamadas.append(texto)
            raise ValueError("redactor roto")
        return real(texto)

    monkeypatch.setattr(log_redaction, "redact", boom_una_vez)
    rec = _record("%s %s", ("GET", f"/feed?apikey={SECRETO}"))
    assert SecretRedactingFilter().filter(rec) is True
    # La excepcion salto enmascarando el primer arg y se trago (107-108);
    # la fase de mensaje siguio con el redactor real y redacto el secreto.
    assert llamadas == ["GET"]  # se rompio enmascarando el primer arg
    assert SECRETO not in rec.msg
    assert rec.args == ()


def test_mensaje_con_secreto_queda_redactado_y_args_vacios():
    rec = _record(f"GET /feed?apikey={SECRETO}", None)
    assert SecretRedactingFilter().filter(rec) is True
    assert SECRETO not in rec.msg
    assert REDACTED in rec.msg
    assert rec.args == ()


def test_formateador_de_excepcion_roto_no_rompe(monkeypatch):
    import sys

    def boom(self, exc_info):
        raise ValueError("formateador roto")

    monkeypatch.setattr(logging.Formatter, "formatException", boom)
    try:
        raise RuntimeError("fallo")
    except RuntimeError:
        rec = _record("boom", None)
        rec.exc_info = sys.exc_info()
    exc_antes = rec.exc_info
    assert SecretRedactingFilter().filter(rec) is True
    assert rec.exc_info is exc_antes  # no se suelta: no hay render que usar
    assert rec.exc_text is None


def test_install_salta_referencias_muertas():
    sentinel = logging.Filter("sentinel")
    handler_vivo = logging.StreamHandler()
    handler_vivo.addFilter(sentinel)
    handler_muerto = logging.StreamHandler()
    ref_muerta = weakref.ref(handler_muerto)
    handler_muerto.close()
    del handler_muerto
    assert ref_muerta() is None

    init_antes = logging.Handler.__init__
    installed_antes = log_redaction._installed
    handler_list_antes = list(logging._handlerList)  # noqa: SLF001
    vivos_antes = [r() for r in handler_list_antes if r() is not None]
    filters_antes = {h: list(h.filters) for h in vivos_antes}
    filters_vivo_antes = list(handler_vivo.filters)
    logging._handlerList.append(ref_muerta)  # noqa: SLF001
    try:
        log_redaction._installed = False
        log_redaction.install()
        assert log_redaction._installed is True
    finally:
        logging.Handler.__init__ = init_antes
        log_redaction._installed = installed_antes
        logging._handlerList[:] = handler_list_antes  # noqa: SLF001
        for h, filtros in filters_antes.items():
            h.filters[:] = filtros
        handler_vivo.filters[:] = filters_vivo_antes
        handler_vivo.close()

    # Estado restaurado: filters de cada handler vivo igual que antes.
    assert handler_vivo.filters == filters_vivo_antes
    for h, filtros in filters_antes.items():
        assert h.filters == filtros
