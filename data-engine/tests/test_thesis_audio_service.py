from app.services import thesis_audio_service as svc


def test_memo_to_speech_text_strips_markdown_and_tables():
    md = "# Tesis de EXEL\n\n| a | b |\n|---|---|\n\n**Resumen** con [fuente](http://x) y `codigo`.\n\n- punto uno\n"
    text = svc.memo_to_speech_text(md, ticker="exel", version=2)
    lines = text.split("\n")
    assert lines[0] == "Tesis de EXEL, versión 2."
    assert "Resumen con fuente y codigo." in lines
    assert "punto uno" in lines
    assert not any("|" in line or "http" in line for line in lines)


def test_audio_key_changes_with_text_and_version():
    a = svc.audio_key("BRK.B", 1, "hola")
    assert a == svc.audio_key("BRK.B", 1, "hola")
    assert a != svc.audio_key("BRK.B", 1, "hola!")
    assert a != svc.audio_key("BRK.B", 2, "hola")
    assert a.startswith("BRKB-v1-")


def test_status_is_unavailable_when_sidecar_is_down(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(svc.httpx, "get", boom)
    monkeypatch.setattr(svc.httpx, "post", boom)
    assert svc.status("K") == "unavailable"
    assert svc.start("K", "t") == "unavailable"
    assert svc.fetch_mp3("K") is None
