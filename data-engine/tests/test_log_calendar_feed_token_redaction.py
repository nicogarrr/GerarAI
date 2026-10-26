import io
import logging

import pytest

from app.core import log_redaction
from app.core.log_redaction import redact

TOKEN = "gfc_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v"


def test_redact_ruta_feed_conserva_resto():
    out = redact(f'1.2.3.4:5 - "GET /api/calendar/feed/{TOKEN}.ics HTTP/1.1" 200')
    assert TOKEN not in out and "/api/calendar/feed/[REDACTED].ics" in out
    assert "GET" in out and "200" in out and "1.2.3.4" in out


def test_redact_idempotente_y_sin_falsos_positivos():
    once = redact(f"/api/calendar/feed/{TOKEN}.ics")
    assert redact(once) == once
    assert redact("/api/calendar/earnings?desde=2026-01-01") == "/api/calendar/earnings?desde=2026-01-01"
    assert redact("/api/calendar/feed") == "/api/calendar/feed"


def test_token_gfc_suelto_en_cualquier_texto():
    assert TOKEN not in redact(f"fallo con {TOKEN} en la peticion")


def test_uvicorn_access_log_real_se_enmascara_y_sigue_formateando():
    uvicorn_logging = pytest.importorskip("uvicorn.logging")
    log_redaction.install()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)  # creado tras install(): lleva el filtro
    handler.setFormatter(uvicorn_logging.AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    lg = logging.getLogger("uvicorn.access.test_feed")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    lg.addHandler(handler)
    lg.info('%s - "%s %s HTTP/%s" %d', "10.0.0.9:1234", "GET", f"/api/calendar/feed/{TOKEN}.ics", "1.1", 200)
    out = buf.getvalue()
    assert TOKEN not in out
    assert 'GET /api/calendar/feed/[REDACTED].ics HTTP/1.1' in out and " 200" in out and "10.0.0.9:1234" in out
    assert "Logging error" not in out


def test_uvicorn_access_log_handler_existente_antes_de_install():
    uvicorn_logging = pytest.importorskip("uvicorn.logging")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(uvicorn_logging.AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    lg = logging.getLogger("uvicorn.access.test_feed2")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    lg.addHandler(handler)
    log_redaction.install()
    handler.addFilter(log_redaction._FILTER)  # install() solo recorre los de _handlerList en la 1a llamada
    lg.info('%s - "%s %s HTTP/%s" %d', "10.0.0.9:1234", "GET", f"/api/calendar/feed/{TOKEN}.ics?x=1", "1.1", 404)
    assert TOKEN not in buf.getvalue() and "404" in buf.getvalue()
