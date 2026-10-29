"""Conector StockTwits: conversación social por símbolo (API pública, gratis, sin clave).

Es la vía gratuita más cercana a «Twitter/X» para titulares sociales por acción
(la API de X es de pago y Nitter es inestable). Endpoint público sin auth:
GET https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json (verificado
29-oct-2026: 200 con {symbol, cursor, messages[]}).

Diseño del conector (no constituye una autorización de despliegue):
- La fuente es SIEMPRE «StockTwits (social)» y el conector «stocktwits»:
  queda fuera del allowlist de alertas (gdelt/rss/ir/sec), de los clústeres
  de historia y, vía tier_8_social, de la materialidad y del conteo de
  fuentes verificadas.
- Fail-closed: si la API cambia de esquema o falla, el resultado es error y
  no se ingiere nada. Nada se inventa: sin created_at, published_at None.
- El sentimiento «Bullish/Bearish» lo declara el AUTOR del mensaje; se guarda
  como cita atribuida en el resumen, nunca como dato propio.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.public_fetch import fetch_public_url_async

API_BASE = "https://api.stocktwits.com/api/2/streams/symbol"
SOURCE_LABEL = "StockTwits (social)"
USER_AGENT = "GerarAI Feed Poller/1.0"
MAX_BODY = 500
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_body(value: str) -> str:
    # Los cuerpos traen a veces HTML básico de enlaces; texto plano siempre.
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", value))).strip()


def _created_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class StockTwitsConnector:
    """Poll del stream público de un símbolo. Un poll = una petición.

    ``fetch`` inyectable solo para tests (misma firma que fetch_public_url_async).
    """

    def __init__(self, *, timeout: float = 20, fetch: Any = None) -> None:
        self.timeout = timeout
        self._fetch_impl = fetch or fetch_public_url_async

    async def poll(self, symbol: str, *, max_items: int = 30) -> ConnectorResult:
        symbol = (symbol or "").strip().upper()
        metadata: dict[str, Any] = {"symbol": symbol}
        if not symbol:
            return ConnectorResult.failed("stocktwits", "missing symbol", metadata=metadata)
        url = f"{API_BASE}/{symbol}.json"
        try:
            content, _content_type, _final_url = await self._fetch_impl(
                url,
                timeout=self.timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            import json

            payload = json.loads(content)
        except Exception as exc:
            return ConnectorResult.failed("stocktwits", exc, metadata=metadata)

        # Esquema estricto: si la API deja de devolver lo esperado, error y
        # nada entra (fail-closed), en vez de reinterpretar campos a ciegas.
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
            return ConnectorResult.failed(
                "stocktwits",
                "unexpected schema: missing messages list",
                metadata=metadata,
            )

        items: list[ConnectorItem] = []
        errors: list[str] = []
        for message in payload["messages"]:
            try:
                if not isinstance(message, dict):
                    raise TypeError("message is not an object")
                message_id = message.get("id")
                body = message.get("body")
                user = message.get("user")
                username = user.get("username") if isinstance(user, dict) else None
                if not isinstance(message_id, int) or not isinstance(body, str) or not body.strip():
                    raise TypeError("message missing id/body")
                if not isinstance(username, str) or not username.strip():
                    raise TypeError("message missing user.username")
                username = username.strip()
                title = _clean_body(body)[:MAX_BODY]
                if len(title) < 3:
                    continue
                # Sentimiento declarado por el propio autor (cita atribuida).
                declared = None
                entities = message.get("entities")
                if isinstance(entities, dict):
                    sentiment = entities.get("sentiment")
                    if isinstance(sentiment, dict) and sentiment.get("basic") in ("Bullish", "Bearish"):
                        declared = sentiment["basic"]
                summary = f"Publicación de @{username} en StockTwits."
                if declared:
                    summary += f" El autor se declara: {declared}."
                items.append(
                    ConnectorItem(
                        source=SOURCE_LABEL,
                        title=title,
                        url=f"https://stocktwits.com/{username}/message/{message_id}",
                        summary=summary,
                        published_at=_created_at(message.get("created_at")),
                        ticker=symbol,
                        external_id=f"stocktwits:{message_id}",
                        headline_from_source=True,
                    )
                )
                if len(items) >= max_items:
                    break
            except Exception as exc:  # noqa: BLE001 — un mensaje raro no tira el lote
                errors.append(f"message skipped: {type(exc).__name__}: {exc}")
        return ConnectorResult(source="stocktwits", items=items, errors=errors, metadata=metadata)
