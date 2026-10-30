"""El filtro de logs tapa secretos en dicts/JSON, en variables con prefijo y sueltos.

Antes solo veia ``clave=valor`` / ``clave: valor`` con la clave pegada al
separador, asi que ``{'api_key': '...'}`` (un dict logueado), ``"X-Finnhub-Token":
"..."`` (cabeceras como JSON), ``OPENAI_API_KEY=...`` o la clave suelta en el
mensaje de error de un SDK ("Incorrect API key provided: sk-...") salian tal cual
en ``docker logs`` y en el traceback del seguimiento de errores.

Los valores se montan concatenando para que este fichero no sea un hallazgo
de gitleaks.
"""

from __future__ import annotations

import logging

import pytest

from app.core.errors import redact_secrets
from app.core.log_redaction import REDACTED, SecretRedactingFilter, redact

SK = "sk-" + "proj-" + "Ab12Cd34Ef56Gh78Ij90"
GROQ = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
GOOGLE = "AIza" + "Sy" + "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6R"
PLAIN = "abcd1234" + "efgh5678"


@pytest.mark.parametrize(
    "text, secret",
    [
        ("{'api_key': '" + SK + "'}", SK),
        ('{"api_key": "' + SK + '"}', SK),
        ("{'X-Finnhub-Token': '" + PLAIN + "'}", PLAIN),
        ('{"Authorization": "Bearer ' + PLAIN + '"}', PLAIN),
        ("{'token': '" + PLAIN + "'}", PLAIN),
        ("OPENAI_API_KEY=" + PLAIN, PLAIN),
        ("OPENCODE_API_KEY='" + PLAIN + "'", PLAIN),
        ("TELEGRAM_BOT_TOKEN: " + PLAIN, PLAIN),
        ("Error code: 401 - Incorrect API key provided: " + SK, SK),
        ("groq rejected " + GROQ, GROQ),
        ("gemini key " + GOOGLE + " invalid", GOOGLE),
    ],
)
def test_secret_is_masked(text: str, secret: str) -> None:
    out = redact(text)
    assert secret not in out
    assert REDACTED in out


@pytest.mark.parametrize(
    "text",
    [
        "tokens used: 1234",
        "max_tokens=200",
        "ticker AAPL price 123.45",
        "GET /api/companies/AAPL 200",
        "skipped 3 rows",
    ],
)
def test_ordinary_lines_are_untouched(text: str) -> None:
    assert redact(text) == text


def test_redaction_is_idempotent() -> None:
    once = redact("{'api_key': '" + SK + "'} OPENAI_API_KEY=" + PLAIN)
    assert redact(once) == once


def test_error_tracker_traceback_uses_the_same_masks() -> None:
    out = redact_secrets("ValueError: bad payload {'api_key': '" + SK + "'}")
    assert SK not in out


def test_logging_filter_masks_dict_args() -> None:
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "payload=%s", ({"api_key": SK},), None)
    SecretRedactingFilter().filter(record)
    assert SK not in record.getMessage()
