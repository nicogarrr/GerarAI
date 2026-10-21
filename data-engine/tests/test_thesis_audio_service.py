from pathlib import Path

from app.services import thesis_audio_service as svc


def test_memo_to_speech_text_strips_markdown_and_tables():
    md = "# Tesis de EXEL\n\n| a | b |\n|---|---|\n\n**Resumen** con [fuente](http://x) y `codigo`.\n\n- punto uno\n"
    text = svc.memo_to_speech_text(md, ticker="exel", version=2)
    lines = text.split("\n")
    assert lines[0] == "Tesis de EXEL, versión 2."
    assert "Resumen con fuente y codigo." in lines
    assert "punto uno" in lines
    assert not any("|" in line or "http" in line for line in lines)


def test_audio_key_is_stable_per_version_state_and_data_day():
    a = svc.audio_key("BRK.B", 1, "texto A", data_day="20261019")
    assert a == svc.audio_key("BRK.B", 1, "texto B distinto", data_day="20261019")
    assert a != svc.audio_key("BRK.B", 2, data_day="20261019")
    assert a != svc.audio_key("BRK.B", 1, draft=True, data_day="20261019")
    assert a != svc.audio_key("BRK.B", 1, data_day="20261020")
    assert a.startswith("BRKB-v1-p-20261019-")


def test_data_day_truncates_to_the_day():
    from datetime import datetime

    assert svc.data_day(datetime(2026, 10, 19, 23, 59)) == "20261019"
    assert svc.data_day(None) == "nd"


def test_status_info_returns_generated_at(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"state": "ready", "generated_at": "2026-10-19T20:00:00+00:00"}

    monkeypatch.setattr(svc.httpx, "get", lambda *a, **k: R())
    assert svc.status_info("K") == {"state": "ready", "generated_at": "2026-10-19T20:00:00+00:00"}


def test_sidecar_expires_cache_after_24h(tmp_path, monkeypatch):
    import os
    import sys
    import time
    import types

    # El sidecar carga piper/lameenc y un modelo al importarse: se stubbean.
    fake_piper = types.ModuleType("piper")
    fake_piper.PiperVoice = type(
        "PiperVoice",
        (),
        {"load": staticmethod(lambda p: types.SimpleNamespace(config=types.SimpleNamespace(sample_rate=22050)))},
    )
    monkeypatch.setitem(sys.modules, "piper", fake_piper)
    monkeypatch.setitem(sys.modules, "lameenc", types.ModuleType("lameenc"))
    src = (Path(__file__).parent.parent / "tts_sidecar" / "server.py").read_text()
    src = src.replace('CACHE = "/w/cache"', f'CACHE = r"{tmp_path}"').replace(
        "ThreadingHTTPServer((\"0.0.0.0\", 8080), H).serve_forever()", "pass"
    )
    mod = types.ModuleType("tts_server_under_test")
    mod.__file__ = "server.py"
    exec(compile(src.split("ThreadingHTTPServer((")[0], "server.py", "exec"), mod.__dict__)  # noqa: S102
    path = mod._path("K1")
    Path(path).write_bytes(b"mp3")
    assert mod._fresh("K1") is True
    old = time.time() - 25 * 3600
    os.utime(path, (old, old))
    assert mod._fresh("K1") is False
    assert not os.path.exists(path)


def test_status_is_unavailable_when_sidecar_is_down(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(svc.httpx, "get", boom)
    monkeypatch.setattr(svc.httpx, "post", boom)
    assert svc.status("K") == "unavailable"
    assert svc.start("K", "t") == "unavailable"
    assert svc.fetch_mp3("K") is None


def _fake_route(monkeypatch, service_cls, memo_return="# Memo"):
    """ThesisService/resolve_company/build_memo_markdown stubbeados; devuelve los kwargs del memo."""
    from types import SimpleNamespace

    from app.api.routes import thesis as route

    calls = {}

    def fake_memo(db, company, thesis, **kwargs):
        calls.update(kwargs)
        return memo_return

    monkeypatch.setattr(route, "ThesisService", service_cls)
    monkeypatch.setattr(route, "resolve_company", lambda db, t: SimpleNamespace(ticker="EXEL"))
    monkeypatch.setattr(route, "build_memo_markdown", fake_memo)
    return route, calls


def test_audio_context_default_uses_latest_published_not_newer_draft(monkeypatch):
    """v13 borrador no tapa a v11 publicada: por defecto suena la publicada."""
    from types import SimpleNamespace

    seen = {}

    class FakeService:
        def latest_published(self, db, ticker):
            seen["latest_published"] = ticker
            return SimpleNamespace(status="published", version=11, company_id=1, updated_at=0)

        def by_version(self, db, ticker, version):
            raise AssertionError("por defecto no se pide por version")

        def data_freshness(self, db, company_id, as_of=None):
            assert as_of == 0, f"as_of debe ser updated_at de la publicada, no {as_of}"
            return None

    route, calls = _fake_route(monkeypatch, FakeService, "# Memo\n\nVersión 11.")
    key, text = route._audio_context(None, "EXEL")
    assert seen["latest_published"] == "EXEL"
    assert calls["draft"] is False
    assert key.startswith("EXEL-v11-p-")
    assert "versión 11" in text.lower()


def test_audio_context_default_404_without_published(monkeypatch):
    """Sin ninguna publicada no se locuta el borrador: 404."""
    import pytest
    from fastapi import HTTPException

    class FakeService:
        def latest_published(self, db, ticker):
            return None

        def data_freshness(self, db, company_id, as_of=None):
            return None

    route, _ = _fake_route(monkeypatch, FakeService)
    with pytest.raises(HTTPException) as excinfo:
        route._audio_context(None, "EXEL")
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "No published thesis for ticker"


def test_audio_status_is_missing_without_published(monkeypatch):
    """La ficha ve «sin audio» (missing), no un error, cuando no hay publicada."""
    from fastapi import HTTPException

    from app.api.routes import thesis as route

    def no_published(db, ticker, version=None):
        raise HTTPException(status_code=404, detail="No published thesis for ticker")

    monkeypatch.setattr(route, "_audio_context", no_published)
    assert route.thesis_audio_status("EXEL", None, None) == {"state": "missing", "key": None}


def test_audio_status_explicit_version_missing_404(monkeypatch):
    """?version=N inexistente: 404, no missing silencioso."""
    import pytest
    from fastapi import HTTPException

    from app.api.routes import thesis as route

    def no_version(db, ticker, version=None):
        raise HTTPException(status_code=404, detail=f"No thesis version {version} for ticker")

    monkeypatch.setattr(route, "_audio_context", no_version)
    with pytest.raises(HTTPException) as excinfo:
        route.thesis_audio_status("EXEL", 99, None)
    assert excinfo.value.status_code == 404


def test_audio_context_explicit_draft_version_keeps_draft_memo(monkeypatch):
    """?version=N de un borrador: modo borrador (sin veredicto ni cifras), clave -d-."""
    from types import SimpleNamespace

    class FakeService:
        def by_version(self, db, ticker, version):
            assert version == 13
            return SimpleNamespace(status="draft", version=13, company_id=1, updated_at=0)

        def latest_published(self, db, ticker):
            raise AssertionError("version explicita no consulta la publicada")

        def data_freshness(self, db, company_id, as_of=None):
            assert as_of == 0, f"as_of debe ser updated_at del borrador pedido, no {as_of}"
            return None

    route, calls = _fake_route(monkeypatch, FakeService, "# Memo\n\nVersión 13 sin veredicto.")
    key, text = route._audio_context(None, "EXEL", 13)
    assert calls["draft"] is True
    assert "Margen de seguridad" not in text and "Compra" not in text
    assert key.startswith("EXEL-v13-d-")


def test_audio_context_explicit_version_missing_404(monkeypatch):
    import pytest
    from fastapi import HTTPException

    class FakeService:
        def by_version(self, db, ticker, version):
            return None

        def data_freshness(self, db, company_id, as_of=None):
            return None

    route, _ = _fake_route(monkeypatch, FakeService)
    with pytest.raises(HTTPException) as excinfo:
        route._audio_context(None, "EXEL", 99)
    assert excinfo.value.status_code == 404
    assert "99" in excinfo.value.detail


def test_audio_post_does_not_requeue_while_pending(monkeypatch):
    from app.api.routes import thesis as route

    monkeypatch.setattr(route, "_audio_context", lambda db, t, v=None: ("K", "txt"))
    monkeypatch.setattr(route.thesis_audio_service, "status", lambda k: "pending")
    monkeypatch.setattr(
        route.thesis_audio_service, "start", lambda k, t: (_ for _ in ()).throw(AssertionError("requeued"))
    )
    assert route.thesis_audio_generate("EXEL", None, None) == {"state": "pending", "key": "K"}
