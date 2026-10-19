from app.services import thesis_audio_service as svc


def test_memo_to_speech_text_strips_markdown_and_tables():
    md = "# Tesis de EXEL\n\n| a | b |\n|---|---|\n\n**Resumen** con [fuente](http://x) y `codigo`.\n\n- punto uno\n"
    text = svc.memo_to_speech_text(md, ticker="exel", version=2)
    lines = text.split("\n")
    assert lines[0] == "Tesis de EXEL, versión 2."
    assert "Resumen con fuente y codigo." in lines
    assert "punto uno" in lines
    assert not any("|" in line or "http" in line for line in lines)


def test_audio_key_is_stable_per_version_and_state():
    a = svc.audio_key("BRK.B", 1, "texto A")
    assert a == svc.audio_key("BRK.B", 1, "texto B distinto")
    assert a != svc.audio_key("BRK.B", 2)
    assert a != svc.audio_key("BRK.B", 1, draft=True)
    assert a.startswith("BRKB-v1-p-")


def test_status_is_unavailable_when_sidecar_is_down(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(svc.httpx, "get", boom)
    monkeypatch.setattr(svc.httpx, "post", boom)
    assert svc.status("K") == "unavailable"
    assert svc.start("K", "t") == "unavailable"
    assert svc.fetch_mp3("K") is None


def test_audio_context_uses_draft_memo_for_unpublished_thesis(monkeypatch):
    from types import SimpleNamespace

    from app.api.routes import thesis as route

    calls = {}

    class FakeService:
        def latest(self, db, ticker):
            return SimpleNamespace(status="draft", version=3, company_id=1, updated_at=0)

        def data_freshness(self, db, company_id):
            return None

    def fake_memo(db, company, thesis, **kwargs):
        calls.update(kwargs)
        return "# Memo\n\nVersión 3 sin veredicto."

    monkeypatch.setattr(route, "ThesisService", FakeService)
    monkeypatch.setattr(route, "resolve_company", lambda db, t: SimpleNamespace(ticker="EXEL"))
    monkeypatch.setattr(route, "build_memo_markdown", fake_memo)
    key, text = route._audio_context(None, "EXEL")
    assert calls["draft"] is True
    assert "Margen de seguridad" not in text and "Compra" not in text
    assert key.startswith("EXEL-v3-d-")


def test_audio_post_does_not_requeue_while_pending(monkeypatch):
    from app.api.routes import thesis as route

    monkeypatch.setattr(route, "_audio_context", lambda db, t: ("K", "txt"))
    monkeypatch.setattr(route.thesis_audio_service, "status", lambda k: "pending")
    monkeypatch.setattr(
        route.thesis_audio_service, "start", lambda k, t: (_ for _ in ()).throw(AssertionError("requeued"))
    )
    assert route.thesis_audio_generate("EXEL", None) == {"state": "pending", "key": "K"}
