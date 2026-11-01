from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree  # nosec B314  # stdlib solo para tipos (Element) y ParseError: defusedxml no los exporta; el parseo usa defusedxml

import httpx

# Feeds RSS/Atom externos: defusedxml solo para PARSEAR - entidades/DTD
# rechazadas sin expandir; ParseError/Element siguen del stdlib.
from defusedxml import ElementTree as DefusedElementTree

from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.data_source_health import get_data_source_registry
from app.services.public_fetch import fetch_public_url_async

_REGISTRY_KEY = "rss"
# Raíces válidas de un feed: Atom (<feed>), RSS 2.0 (<rss>) y RSS 1.0/RDF (<RDF>).
_FEED_ROOTS = {"feed", "rss", "rdf"}


def _record_health_failure(exc: Exception) -> None:
    """5xx/401/403/429/red/documento inválido degradan; 400/404/410 (feed
    retirado o movido) son del feed concreto, no de la fuente: neutros."""
    registry = get_data_source_registry()
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (400, 404, 410):
            return
        registry.record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        return
    if isinstance(exc, httpx.TransportError):
        registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        return
    registry.record_failure(_REGISTRY_KEY, f"documento inválido: {type(exc).__name__}")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ElementTree.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in element:
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(text).split())


def _published_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class RSSConnector:
    """Small RSS 2.0 / Atom poller implemented with the standard XML parser."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: float = 20,
        user_agent: str = "GerarAI Feed Poller/1.0",
    ) -> None:
        self.client = client
        self.timeout = timeout
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml",
        }

    async def _fetch(self, url: str) -> bytes:
        if self.client is not None:
            response = await self.client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.content
        # Sin cliente inyectado: pasa por public_fetch (bloquea IPs privadas,
        # fija la IP resuelta y revalida cada redirección).
        content, _content_type, _final_url = await fetch_public_url_async(
            url, timeout=self.timeout, headers=self.headers
        )
        return content

    async def poll(
        self,
        url: str,
        *,
        ticker: str | None = None,
        max_items: int = 100,
    ) -> ConnectorResult:
        metadata: dict[str, Any] = {"feed_url": url, "ticker": ticker}
        try:
            content = await self._fetch(url)
            root = DefusedElementTree.fromstring(content)
            if _local_name(root.tag) not in _FEED_ROOTS:
                # 200 bien formado que no es un feed (challenge HTML, sitemap,
                # página de error): deriva de formato, no éxito.
                raise ValueError(f"el documento no es un feed RSS/Atom (raíz <{_local_name(root.tag)}>)")
            feed_title, entries = self._entries(root)
            metadata["feed_title"] = feed_title
            items: list[ConnectorItem] = []
            seen: set[str] = set()
            if max_items <= 0:
                return ConnectorResult(source="rss", items=[], metadata=metadata)
            for entry in entries:
                item = self._parse_entry(entry, url, feed_title, ticker)
                key = item.external_id or item.url or f"{item.title}:{item.published_at}"
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
                if len(items) >= max_items:
                    break
            metadata["format"] = "atom" if _local_name(root.tag) == "feed" else "rss"
            get_data_source_registry().record_success(_REGISTRY_KEY)
            return ConnectorResult(source="rss", items=items, metadata=metadata)
        except Exception as exc:
            _record_health_failure(exc)
            return ConnectorResult.failed("rss", exc, metadata=metadata)

    def _entries(self, root: ElementTree.Element) -> tuple[str, list[ElementTree.Element]]:
        if _local_name(root.tag) == "feed":
            return _child_text(root, "title"), [child for child in root if _local_name(child.tag) == "entry"]

        channel = next(
            (child for child in root if _local_name(child.tag) == "channel"),
            root,
        )
        return _child_text(channel, "title"), [child for child in channel if _local_name(child.tag) == "item"]

    def _parse_entry(
        self,
        entry: ElementTree.Element,
        feed_url: str,
        feed_title: str,
        ticker: str | None,
    ) -> ConnectorItem:
        title = _clean_html(_child_text(entry, "title")) or "Untitled feed item"
        summary = _clean_html(_child_text(entry, "description", "summary", "content"))
        link = _child_text(entry, "link")
        if not link:
            for child in entry:
                if _local_name(child.tag) != "link":
                    continue
                rel = child.attrib.get("rel", "alternate")
                if rel == "alternate" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        link = urljoin(feed_url, link) if link else None
        external_id = _child_text(entry, "guid", "id") or link
        published = _published_at(_child_text(entry, "pubdate", "published", "updated", "date"))
        author = _child_text(entry, "author", "creator")
        return ConnectorItem(
            source=feed_title or "rss",
            title=title,
            url=link,
            summary=summary,
            published_at=published,
            ticker=ticker.upper() if ticker else None,
            item_type="news",
            external_id=external_id,
            metadata={"feed_url": feed_url, "author": author or None},
        )
