"""Ninguna excepcion de infraestructura puede llegar al cliente ni al log.

Dos superficies:

1. Los `detail=str(exc)` que se lanzan tras un `except Exception` /
   `RuntimeError` / `IntegrityError` devuelven el traceback entero (SQL,
   DSN, rutas del host, y la URL del proveedor con su api key en la query).
   Los `except ValueError` que validan rangos de fecha o parametros de
   busqueda si sonintencionales y se dejan intactos: esos mensajes son la
   validacion que el usuario necesita ver.

2. Lo que se loguea. httpx y fetch ponen la URL completa en el texto de sus
   excepciones, y en los clientes de mercado la key va en la query
   (?token=, ?apikey=). Un warning de "fallo al llamar a Finnhub" con `exc`
   crudo escribia la key en el log de la aplicacion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.errors import redact_secrets, safe_detail

ROUTES = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"

# Tipos de excepcion que representan validacion deliberada del autor de la
# ruta: su texto es el mensaje de error que el usuario debe ver.
_USER_FACING_EXCEPTIONS = {"ValueError", "ValidationError"}

# Tipos que vienen de la infraestructura y cuyo texto no es apto para el
# cliente: traceback de SQL, URL del proveedor con credenciales, DSN.
_INFRASTRUCTURE_EXCEPTIONS = {
    "Exception",
    "BaseException",
    "RuntimeError",
    "IntegrityError",
    "OperationalError",
    "ProgrammingError",
    "DataError",
    "HTTPError",
    "HTTPStatusError",
    "ConnectError",
    "ReadTimeout",
    "TimeoutException",
    "ConnectionError",
    "OSError",
    "EsefError",
    "CNMVParseError",
    "LLMError",
    "RateLimitBackendUnavailable",
    "NonceBackendUnavailable",
}

_DETAIL_RAISE = re.compile(r"detail\s*=\s*(.+?)\)\s*from\s")
_EXCEPT_LINE = re.compile(r"^\s*except\s+(.+?):")
_AS_ALIAS = re.compile(r"\s+as\s+\w+$")


def _except_types(line: str) -> set[str]:
    match = _EXCEPT_LINE.match(line)
    if not match:
        return set()
    body = _AS_ALIAS.sub("", match.group(1)).strip().strip("()")
    if not body or body == "Exception":
        return set()
    return {part.strip().split(".")[-1] for part in body.split(",") if part.strip()}


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_infrastructure_detail_reaches_the_client():
    offenders: list[str] = []
    for path in _python_files(ROUTES):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "detail=" not in line:
                continue
            if "safe_detail(" in line:
                continue
            if not re.search(r"detail\s*=\s*.*\{exc\}", line):
                continue
            # Busca hacia atras el except que corresponde.
            caught: set[str] = set()
            for back in range(index, max(-1, index - 12), -1):
                caught |= _except_types(lines[back])
            if not caught:
                offenders.append(f"{path.name}:{index + 1} sin except reconocible")
                continue
            infra = caught & _INFRASTRUCTURE_EXCEPTIONS
            if infra:
                offenders.append(
                    f"{path.name}:{index + 1} detail con {sorted(infra)}: {line.strip()}"
                )
    assert offenders == [], "exception de infraestructura en el detalle HTTP:\n" + "\n".join(
        offenders
    )


def test_redact_secrets_strips_provider_keys():
    for template in (
        "https://finnhub.io/api/v1/quote?symbol=AAPL&token=SECRETVALUE",
        "https://financialmodelingprep.com/api/v3/x?apikey=SECRETVALUE",
        "url=redis://user:pass@cache:6379&api_key=SECRETVALUE",
    ):
        cleaned = redact_secrets(template)
        assert "SECRETVALUE" not in cleaned, template
        assert "REDACTED" in cleaned, template


def test_redact_secrets_leaves_harmless_text_alone():
    for text in (
        "SELECT 1",
        "Ticker AAPL not found",
        "https://example.com/path?symbol=AAPL&from=2024-01-01",
    ):
        assert redact_secrets(text) == text


def test_redact_secrets_is_case_insensitive():
    cleaned = redact_secrets("https://x/?Token=SECRETVALUE&API_KEY=SECRETVALUE2")
    assert "SECRETVALUE" not in cleaned
    assert "SECRETVALUE2" not in cleaned


def test_safe_detail_never_returns_the_exception_text(caplog):
    exc = RuntimeError("upstream failed: https://fmp?apikey=SECRETVALUE")
    with caplog.at_level("ERROR", logger="cavaai.request_errors"):
        detail = safe_detail(exc, 424)
    assert "SECRETVALUE" not in detail
    assert "ref:" in detail
    assert detail.startswith("Upstream dependency failed")
    # El log lleva el detalle (redactado) para poder diagnosticar.
    assert "SECRETVALUE" not in caplog.text


def test_service_error_payloads_are_redacted():
    """Los dicts de error que se devuelven como cuerpo de respuesta."""
    offenders: list[str] = []
    for path in _python_files(SERVICES):
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if '"error"' not in line and '"reason"' not in line:
                continue
            if "{exc}" in line and "redact_secrets" not in line:
                offenders.append(f"{path.name}:{index + 1}: {line.strip()}")
    # No todos los motivos son de infraestructura (algunos son texto fijo), asi
    # que se listan pero solo se exige el patron en los que interpolan exc.
    assert offenders == [], "payload de servicio con texto de excepcion sin redactar:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, "Invalid request"),
        (404, "Resource not found"),
        (424, "Upstream dependency failed"),
        (500, "Internal server error"),
        (502, "Upstream error"),
        (503, "Service unavailable"),
    ],
)
def test_safe_detail_status_defaults(status, expected):
    detail = safe_detail(RuntimeError("boom"), status)
    assert detail.startswith(expected)


def test_redact_secrets_strips_url_userinfo_passwords():
    # Un DSN lleva la password en el userinfo, no en la query: los pares
    # clave=valor no la alcanzan y el traceback de un fallo de Redis/Postgres
    # la publicaba entera.
    assert "VERYSECRET" not in redact_secrets("redis://worker:VERYSECRET@cache:6379/0")
    assert "VERYSECRET" not in redact_secrets("postgresql://user:VERYSECRET@db:5432/cavaai")
    # El usuario no es secreto y ayuda a correlacionar: se conserva.
    assert redact_secrets("redis://worker:VERYSECRET@cache:6379/0") == (
        "redis://worker:REDACTED@cache:6379/0"
    )


def test_safe_detail_redacts_the_userinfo_password_in_the_log(caplog):
    # El peor caso real: el catch de knowledge.extract_principles registra
    # via safe_detail precisamente un error de Redis, cuyo texto lleva el
    # DSN con la password.
    import logging

    with caplog.at_level(logging.ERROR, logger="cavaai.request_errors"):
        try:
            raise ConnectionError(
                "Error -5 connecting to redis://worker:VERYSECRET@cache:6379/0. Name or service not known."
            )
        except ConnectionError as exc:
            detail = safe_detail(exc, 503)
    assert "VERYSECRET" not in caplog.text
    assert "REDACTED" in caplog.text
    assert "VERYSECRET" not in detail


def test_redact_secrets_covers_uppercase_and_duplicate_params():
    cleaned = redact_secrets("https://x/?TOKEN=VERYSECRET&token=AGAINSECRET")
    assert "VERYSECRET" not in cleaned
    assert "AGAINSECRET" not in cleaned
    assert cleaned.count("REDACTED") == 2
