from app.services.langfuse_client import _safe_status_message


def test_exception_class_name_passes():
    assert _safe_status_message("ValueError") == "ValueError"


def test_free_text_error_never_leaves_the_process():
    assert _safe_status_message("boom: api_key=abc123 for user@example.com") == "error"
    assert _safe_status_message("Traceback\nprompt: secret") == "error"


def test_empty_error_is_none():
    assert _safe_status_message(None) is None
    assert _safe_status_message("") is None
