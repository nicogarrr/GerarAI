"""Diagnostico acotado de una salida invalida del modelo en la extraccion."""

from types import SimpleNamespace

from app.llm.errors import StructuredOutputError
from app.services.knowledge_library_service import (
    extraction_diagnostic,
    extraction_error_message,
)


def _response(text="", finish="length", degraded=False, out=3000):
    return SimpleNamespace(
        text=text,
        finish_reason=finish,
        degraded=degraded,
        usage=SimpleNamespace(output_tokens=out),
    )


def test_diagnostic_has_measured_fields_and_no_text():
    secret = "TEXTO-PRIVADO-" * 50
    diag = extraction_diagnostic(
        StructuredOutputError("x"),
        response=_response(text=secret),
        batch_index=2,
        batch_count=3,
        source_chars=24000,
        max_tokens=3000,
    )
    assert diag == {
        "error_type": "StructuredOutputError",
        "batch_index": 2,
        "batch_count": 3,
        "finish_reason": "length",
        "degraded": False,
        "response_chars": len(secret),
        "output_tokens": 3000,
        "max_tokens": 3000,
        "source_chars": 24000,
    }
    assert "PRIVADO" not in repr(diag)


def test_empty_response_reports_zero_chars_and_degraded():
    diag = extraction_diagnostic(
        ValueError("v"),
        response=_response(text="", finish="stop", degraded=True, out=0),
        batch_index=1,
        batch_count=1,
        source_chars=10,
        max_tokens=3000,
    )
    assert diag["response_chars"] == 0
    assert diag["degraded"] is True
    assert diag["finish_reason"] == "stop"


def test_error_message_uses_diagnostic_in_spanish_not_provider_down():
    exc = StructuredOutputError("x")
    exc.diagnostic = {"batch_index": 2, "batch_count": 3, "finish_reason": "length"}
    msg = extraction_error_message(exc)
    assert "lote 2/3" in msg
    assert "length" in msg
    assert "no está disponible" not in msg


def test_error_message_without_diagnostic_is_unchanged():
    assert "no respondió" in extraction_error_message(StructuredOutputError("x"))


def test_unknown_finish_reason_is_explicit():
    exc = ValueError("v")
    exc.diagnostic = {"batch_index": 1, "batch_count": 1, "finish_reason": None}
    assert "desconocido" in extraction_error_message(exc)
