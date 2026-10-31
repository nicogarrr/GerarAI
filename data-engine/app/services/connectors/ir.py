from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.data_source_health import get_data_source_registry
from app.services.public_fetch import fetch_public_url_async

_REGISTRY_KEY = "ir"
_HTML_SHAPE_RE = re.compile(r"<(?:!doctype|html|head|body|a|div|table)\b", re.IGNORECASE)


def _record_health_failure(exc: Exception) -> None:
    """5xx/401/403/429/red degradan; 400/404/410 (página IR retirada) neutros."""
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


PRESS_PAGE_RE = re.compile(
    r"(?:news(?:room|-and-events|-events)?|press(?:-releases)?|media|releases)",
    re.IGNORECASE,
)
RELEASE_LINK_RE = re.compile(
    r"(?:press[-_/ ]?release|news[-_/ ]?release|release[-_/ ]?detail|"
    r"news[-_/ ]?detail|article[-_/ ]?detail|static-files)",
    re.IGNORECASE,
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        self._href = attributes.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []


def _links(html_text: str, base_url: str) -> list[tuple[str, str]]:
    parser = _LinkParser()
    parser.feed(html_text)
    normalized: list[tuple[str, str]] = []
    for href, text in parser.links:
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        absolute, _ = urldefrag(urljoin(base_url, unescape(href)))
        if urlparse(absolute).scheme in {"http", "https"}:
            normalized.append((absolute, text))
    return normalized


def discover_press_release_pages(html_text: str, base_url: str) -> list[str]:
    """Find likely newsroom/listing pages linked from an investor-relations page."""

    base_host = urlparse(base_url).netloc.lower()
    pages: list[str] = []
    for url, text in _links(html_text, base_url):
        if urlparse(url).netloc.lower() != base_host:
            continue
        if PRESS_PAGE_RE.search(f"{text} {url}") and not RELEASE_LINK_RE.search(url):
            if url not in pages:
                pages.append(url)
    return pages


def discover_press_release_links(html_text: str, base_url: str) -> list[tuple[str, str]]:
    """Extract individual press release/article links from an IR listing."""

    releases: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, text in _links(html_text, base_url):
        label = f"{text} {url}"
        is_release = (
            RELEASE_LINK_RE.search(url) is not None
            or re.search(
                r"\bpress release\s*[:\-\u2014]\s*\w",
                text,
                re.IGNORECASE,
            )
            is not None
        )
        is_pdf_release = urlparse(url).path.lower().endswith(".pdf") and PRESS_PAGE_RE.search(label)
        if not (is_release or is_pdf_release) or url in seen:
            continue
        seen.add(url)
        releases.append((url, text or urlparse(url).path.rsplit("/", 1)[-1]))
    return releases


def _decode_html(content: bytes, content_type: str | None) -> str:
    charset = None
    if content_type:
        match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
    try:
        return content.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


class IRConnector:
    """Discover and poll public investor-relations pages for release links."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: float = 20,
        user_agent: str = "GerarAI IR Poller/1.0",
    ) -> None:
        self.client = client
        self.timeout = timeout
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        }

    async def _fetch(self, url: str) -> str:
        if self.client is not None:
            response = await self.client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.text
        # Sin cliente inyectado: pasa por public_fetch (bloquea IPs privadas,
        # fija la IP resuelta y revalida cada redirección).
        content, content_type, _final_url = await fetch_public_url_async(
            url, timeout=self.timeout, headers=self.headers
        )
        return _decode_html(content, content_type)

    async def poll(
        self,
        ir_url: str,
        *,
        ticker: str | None = None,
        max_pages: int = 4,
        max_items: int = 100,
    ) -> ConnectorResult:
        metadata: dict = {"ir_url": ir_url, "ticker": ticker, "pages_polled": []}
        errors: list[str] = []
        try:
            root_html = await self._fetch(ir_url)
            if not _HTML_SHAPE_RE.search(root_html[:2000]):
                # 200 sin estructura HTML (JSON de error, texto plano): la
                # página IR no es tal; la salud la decide solo la página raíz.
                raise ValueError("la página IR raíz no tiene estructura HTML")
        except Exception as exc:
            _record_health_failure(exc)
            return ConnectorResult.failed("ir", exc, metadata=metadata)
        get_data_source_registry().record_success(_REGISTRY_KEY)

        release_links = discover_press_release_links(root_html, ir_url)
        pages = discover_press_release_pages(root_html, ir_url)
        for page_url in pages[: max(0, max_pages)]:
            if page_url == ir_url:
                continue
            try:
                page_html = await self._fetch(page_url)
                metadata["pages_polled"].append(page_url)
                release_links.extend(discover_press_release_links(page_html, page_url))
            except Exception as exc:
                errors.append(f"{page_url}: {exc}")

        items: list[ConnectorItem] = []
        seen: set[str] = set()
        if max_items <= 0:
            return ConnectorResult(source="ir", items=[], errors=errors, metadata=metadata)
        for url, title in release_links:
            if url in seen:
                continue
            seen.add(url)
            items.append(
                ConnectorItem(
                    source="IR",
                    title=" ".join(title.split()) or f"{ticker or 'Company'} investor release",
                    url=url,
                    ticker=ticker.upper() if ticker else None,
                    item_type="press_release",
                    external_id=url,
                    metadata={"ir_url": ir_url},
                )
            )
            if len(items) >= max_items:
                break

        metadata["discovered_pages"] = pages
        return ConnectorResult(source="ir", items=items, errors=errors, metadata=metadata)
