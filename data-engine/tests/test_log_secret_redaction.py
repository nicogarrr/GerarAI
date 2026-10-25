import io
import logging

import httpx

from app.core import log_redaction
from app.core.log_redaction import redact

FAKE = "SYNTH-SECRET-0123456789"


def _logger() -> tuple[logging.Logger, io.StringIO]:
    log_redaction.install()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)  # creado tras install(): lleva el filtro
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("synthetic.redaction." + str(id(stream)))
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    return logger, stream


def test_query_param_keys_are_redacted_in_message() -> None:
    logger, out = _logger()
    logger.info('HTTP Request: GET https://x.test/q?symbol=AAPL&apikey=%s "HTTP/1.1 200"', FAKE)
    logger.info("GET https://y.test/quote?symbol=BABA&token=%s", FAKE)
    text = out.getvalue()
    assert FAKE not in text
    assert "symbol=AAPL" in text and "symbol=BABA" in text
    assert "apikey=[REDACTED]" in text and "token=[REDACTED]" in text


def test_args_headers_and_bearer_are_redacted() -> None:
    logger, out = _logger()
    logger.warning("req %s", "https://z.test/a?api_key=" + FAKE)
    logger.warning("headers Authorization: Bearer %s x-api-key: %s", FAKE, FAKE)
    logger.warning("url https://user:%s@host.test/path", FAKE)
    assert FAKE not in out.getvalue()


def test_exception_text_with_url_is_redacted() -> None:
    logger, out = _logger()
    request = httpx.Request("GET", f"https://api.test/v1/quote?symbol=CB&apikey={FAKE}")
    response = httpx.Response(429, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        logger.exception("provider failed")
    text = out.getvalue()
    assert "provider failed" in text and "429" in text
    assert FAKE not in text


def test_non_secret_text_is_unchanged() -> None:
    msg = "HTTP Request: GET https://example.com/api?symbol=AAPL&limit=5 ok"
    assert redact(msg) == msg


def test_filter_covers_existing_httpx_handler_path() -> None:
    log_redaction.install()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("httpx")
    previous = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info('HTTP Request: GET https://p.test/s?symbol=ASTS&apikey=%s "HTTP/1.1 429"', FAKE)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert FAKE not in stream.getvalue()
    assert "apikey=[REDACTED]" in stream.getvalue()
