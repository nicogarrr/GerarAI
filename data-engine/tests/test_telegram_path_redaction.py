"""Synthetic credentials only: Telegram puts credentials in path, not query."""
import io
import logging

import pytest

from app.core.errors import redact_secrets, safe_detail
from app.core.log_redaction import install, redact

TOKEN = "123456789:synthetic_bot_token_NotARealCredential"


@pytest.mark.parametrize("path", [
    f"/bot{TOKEN}/sendMessage", f"/bot{TOKEN}/getUpdates",
    f"/bot{TOKEN}/answerCallbackQuery", f"/file/bot{TOKEN}/photos/example.jpg",
    f"/bot{TOKEN.replace(':', '%3A')}/sendMessage",
])
@pytest.mark.parametrize("scrub", [redact, redact_secrets])
def test_bot_path_redacts_in_logs_and_error_details(path, scrub):
    raw = f"POST https://telegram-proxy.example{path}?timeout=20 HTTP/1.1 502"
    result = scrub(raw)
    assert TOKEN not in result
    assert "synthetic_bot_token" not in result
    assert "telegram-proxy.example" in result
    assert path.rsplit("/", 1)[1] in result
    assert "timeout=20" in result
    assert scrub(result) == result


def test_installed_handler_redacts_formatted_args_traceback_and_stack():
    install()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("test.telegram.synthetic")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        try:
            raise RuntimeError(f"https://api.telegram.org/bot{TOKEN}/sendMessage")
        except RuntimeError:
            logger.exception("POST %s", f"/bot{TOKEN}/sendMessage", stack_info=True)
        text = stream.getvalue()
        assert TOKEN not in text
        assert "[REDACTED]" in text
        assert "sendMessage" in text
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_safe_detail_own_log_is_redacted_even_without_installed_filter():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    # This check covers safe_detail's own sanitizer independently of install().
    handler.filters.clear()
    logger = logging.getLogger("gerarai.request_errors")
    logger.addHandler(handler)
    try:
        detail = safe_detail(RuntimeError(f"GET /bot{TOKEN}/getUpdates"), 502)
        assert TOKEN not in detail
        assert TOKEN not in stream.getvalue()
        assert "getUpdates" in stream.getvalue()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_regular_paths_and_existing_markers_remain_unchanged():
    for text in ["/botanical/news", "/bot[REDACTED]/sendMessage", "/robots.txt"]:
        assert redact(text) == text
        assert redact_secrets(text) == text


def test_approval_transport_error_never_returns_bot_token(monkeypatch):
    from types import SimpleNamespace

    from app.services import thesis_approval_service as approval

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            raise ConnectionError(f"POST {url} upstream failed")

    monkeypatch.setattr(approval.httpx, "Client", FailingClient)
    settings = SimpleNamespace(
        telegram_enabled=True, telegram_approval_enabled=True,
        telegram_bot_token=TOKEN, telegram_chat_id="synthetic-chat",
        telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=1,
    )
    thesis = SimpleNamespace(id=1, version=1, status="final", executive_summary="Synthetic test")
    # Failure occurs before any persistence. No real Telegram or approval mutation.
    result = approval.send_thesis_approval_request(None, thesis, "TEST", settings)
    assert result["status"] == "failed"
    assert TOKEN not in result["error"]
    assert "synthetic_bot_token" not in result["error"]
    assert "sendMessage" in result["error"]
