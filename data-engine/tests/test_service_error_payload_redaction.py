"""Payloads de error de servicios: el texto de la excepcion llega redactado.

Un fallo de httpx trae la URL completa en su texto, y en los feeds de mercado la
key viaja en la query (``?token=``). Estos payloads acaban en respuestas, en el
resumen del barrido y en la cadena de fuentes de la tesis.
"""
from __future__ import annotations

from app.services import ticker_news_lane

LEAK = "Client error '401 Unauthorized' for url 'https://feed.example/news?symbol=ACME&token=SECRET123TOKEN'"


class _Company:
    ticker = "ACME"


class _Deadline:
    def expired(self) -> bool:
        return False


def test_news_sweep_error_message_does_not_carry_the_feed_token():
    def fetch(company, lane, url):
        raise RuntimeError(LEAK)

    result = ticker_news_lane.sweep(
        [_Company()],
        lanes_for=lambda company: [("finnhub", "https://feed.example/news")],
        fetch=fetch,
        ingest=lambda company, part: {"created": 0},
        deadline=_Deadline(),
    )
    (error,) = result["errors"]
    assert error["ticker"] == "ACME" and error["type"] == "RuntimeError"
    assert "SECRET123TOKEN" not in error["message"]
    assert "401 Unauthorized" in error["message"]
