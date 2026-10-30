"""Seguimiento de errores 500 sin dependencias (protocolo store de Sentry/GlitchTip)."""

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core import error_reporting as er


def _boom():
    raise RuntimeError("fallo con https://api.example.com/x?apikey=SECRETO123 dentro")


def _exc():
    try:
        _boom()
    except RuntimeError as exc:
        return exc


def _reset():
    er._recent.clear()
    er._window_start = 0.0
    er._window_count = 0


def test_parse_dsn():
    assert er.parse_dsn(None) is None
    assert er.parse_dsn("no es un dsn") is None
    assert er.parse_dsn("https://host.example/12") is None  # sin clave
    assert er.parse_dsn("ftp://k@host/1") is None
    url, auth = er.parse_dsn("https://abc123@glitchtip.example.com/7")
    assert url == "https://glitchtip.example.com/api/7/store/"
    assert "sentry_key=abc123" in auth
    url, _ = er.parse_dsn("http://k@localhost:8000/sub/42")
    assert url == "http://localhost:8000/sub/api/42/store/"


def test_sin_dsn_no_envia_nada():
    _reset()
    sent = []
    settings = SimpleNamespace(error_tracking_dsn=None, app_env="test")
    assert er.report_exception(_exc(), ref="r1", settings=settings, sender=lambda: sent.append(1)) is False
    assert sent == []


def test_evento_redactado_y_limitado():
    _reset()
    event = er.build_event(_exc(), ref="abc", method="GET", path="/api/x", environment="prod")
    text = str(event)
    assert "SECRETO123" not in text
    assert event["tags"] == {"ref": "abc"}
    assert event["transaction"] == "GET /api/x"
    assert event["exception"]["values"][0]["type"] == "RuntimeError"

    settings = SimpleNamespace(error_tracking_dsn="https://k@h.example/1", error_tracking_environment=None, app_env="prod")
    done = threading.Event()
    assert er.report_exception(_exc(), ref="a", settings=settings, sender=done.set) is True
    assert done.wait(2)
    # misma firma en el mismo minuto: no se repite
    assert er.report_exception(_exc(), ref="b", settings=settings, sender=lambda: None) is False


def test_tope_por_minuto():
    _reset()
    settings = SimpleNamespace(error_tracking_dsn="https://k@h.example/1", error_tracking_environment="x", app_env="x")
    sent = 0
    for i in range(er.MAX_EVENTS_PER_MINUTE + 10):
        exc = _exc()
        er._recent.clear()  # firmas distintas a efectos del tope global
        if er.report_exception(exc, ref=str(i), settings=settings, sender=lambda: None):
            sent += 1
    assert sent == er.MAX_EVENTS_PER_MINUTE


def test_un_500_real_se_reporta_con_su_ref(monkeypatch):
    _reset()
    import main

    calls = []
    monkeypatch.setattr(er, "report_exception", lambda exc, **kw: calls.append((type(exc).__name__, kw)))

    @main.app.get("/__test_error_tracking_boom")
    def _route():
        raise RuntimeError("x")

    try:
        response = TestClient(main.app, raise_server_exceptions=False).get("/__test_error_tracking_boom")
    finally:
        main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != "/__test_error_tracking_boom"]
    assert response.status_code == 500
    assert calls and calls[0][0] == "RuntimeError"
    ref = response.json()["detail"].rsplit("ref: ", 1)[-1].rstrip(")")
    assert calls[0][1]["ref"] == ref
    assert calls[0][1]["path"] == "/__test_error_tracking_boom"
