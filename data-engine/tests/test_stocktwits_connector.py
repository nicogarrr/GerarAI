"""Conector StockTwits (carril social): parseo, atribución y fail-closed."""

import asyncio
import json

from app.services.connectors.stocktwits import SOURCE_LABEL, StockTwitsConnector


def run_async(coroutine):
    return asyncio.run(coroutine)


def _payload(messages):
    return json.dumps({"symbol": {"symbol": "AAPL"}, "cursor": {"more": True}, "messages": messages}).encode()


def _connector(payload_bytes):
    async def fake_fetch(url, *, timeout, headers):
        return payload_bytes, "application/json", url

    return StockTwitsConnector(fetch=fake_fetch)


def test_poll_parses_messages_with_attribution_and_declared_sentiment():
    payload = _payload(
        [
            {
                "id": 667674140,
                "body": "$AAPL might be the biggest <a href='https://x.test'>bubble</a> now.",
                "created_at": "2026-10-29T18:26:27Z",
                "entities": {"sentiment": {"basic": "Bearish"}},
                "user": {"username": "JLInvest"},
            },
            {
                "id": 667674141,
                "body": "$AAPL earnings next week, loading up",
                "created_at": "2026-10-29T18:20:00Z",
                "entities": {"sentiment": None},
                "user": {"username": "bullcase"},
            },
        ]
    )
    result = run_async(_connector(payload).poll("aapl"))

    assert result.status == "ok"
    assert result.source == "stocktwits"
    assert len(result.items) == 2
    first = result.items[0]
    assert first.source == SOURCE_LABEL
    assert first.ticker == "AAPL"
    # HTML limpio y URL canónica de mensaje
    assert first.title == "$AAPL might be the biggest bubble now."
    assert first.url == "https://stocktwits.com/JLInvest/message/667674140"
    assert first.external_id == "stocktwits:667674140"
    assert first.published_at.isoformat() == "2026-10-29T18:26:27+00:00"
    # El sentimiento es declaración del autor, citada como tal.
    assert "El autor se declara: Bearish." in first.summary
    assert "@JLInvest" in first.summary
    # Sin sentimiento declarado no se inventa.
    assert "declara" not in result.items[1].summary


def test_poll_is_fail_closed_on_schema_change():
    result = run_async(_connector(b'{"error": "rate limited"}').poll("AAPL"))
    assert result.status == "error"
    assert result.items == []
    assert any("schema" in error for error in result.errors)


def test_poll_skips_broken_messages_but_keeps_valid_batch():
    payload = _payload(
        [
            {"id": "no-int", "body": "broken", "user": {"username": "x"}},
            {"id": 1, "body": "", "user": {"username": "x"}},
            {"id": 2, "body": "ab", "user": {"username": "x"}},  # titular < 3: se omite
            {"id": 3, "body": "$AAPL fine post", "created_at": "not-a-date", "user": {"username": "x"}},
        ]
    )
    result = run_async(_connector(payload).poll("AAPL"))
    assert result.status == "partial"
    assert len(result.items) == 1
    # Fecha inválida: published_at None, nunca inventada.
    assert result.items[0].published_at is None


def test_poll_missing_symbol_is_fail_closed():
    result = run_async(_connector(_payload([])).poll(""))
    assert result.status == "error"
    assert result.items == []


def test_poll_http_failure_is_fail_closed():
    async def failing_fetch(url, *, timeout, headers):
        raise TimeoutError("boom")

    result = run_async(StockTwitsConnector(fetch=failing_fetch).poll("AAPL"))
    assert result.status == "error"
    assert result.items == []
