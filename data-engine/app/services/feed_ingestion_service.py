from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.services.connectors import (
    ConnectorResult,
    GDELTConnector,
    IRConnector,
    RSSConnector,
    SECClient,
)
from app.services.document_ingestion_service import MAX_DOCUMENT_BYTES
from app.services.public_fetch import fetch_public_url_async


@dataclass(frozen=True, slots=True)
class RSSFeed:
    url: str
    ticker: str | None = None
    # Etiqueta de atribución para la UI: si está, sustituye al <title> del
    # canal como `source` del evento («All News Releases» no dice nada; la
    # agencia sí). El <title> original queda en metadata del poll.
    label: str | None = None
    # Carril opcional («gobierno»): eventos sin empresa detectada
    # (fail-closed, como el carril macro), etiquetados en metadata.
    lane: str | None = None


def configured_rss_feeds(value: str | None = None) -> list[RSSFeed]:
    """Parse RSS_FEEDS as JSON or comma/newline separated URL[|TICKER] values."""

    raw = value if value is not None else os.getenv("RSS_FEEDS", "")
    if not raw.strip():
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None

    feeds: list[RSSFeed] = []
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, str):
                feeds.extend(configured_rss_feeds(entry))
            elif isinstance(entry, dict) and entry.get("url"):
                ticker = str(entry["ticker"]).upper() if entry.get("ticker") else None
                label = str(entry["label"]).strip() if entry.get("label") else None
                feeds.append(RSSFeed(url=str(entry["url"]), ticker=ticker, label=label))
        return _unique_feeds(feeds)

    for entry in raw.replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry:
            continue
        first, separator, second = entry.partition("|")
        if separator and not first.lower().startswith(("http://", "https://")):
            ticker, url = first.upper(), second
        else:
            url, ticker = first, second.upper() if separator and second else None
        if url.lower().startswith(("http://", "https://")):
            feeds.append(RSSFeed(url=url, ticker=ticker or None))
    return _unique_feeds(feeds)


# Notas de prensa de agencia (RSS público, gratis). Atribución: el <title>
# del canal se guarda como `source` del evento (p. ej. «Business Wire
# Communications News»), visible en la ficha. Verificados el 19-oct-2026 con
# el UA del poller («GerarAI Feed Poller/1.0»):
# - Business Wire no publica un feed «todo» gratuito; hay feeds por industria.
#   Se incluyen Communications y Technology: Telecommunications (ambos
#   trajeron la nota AST SpaceMobile del 19-oct-2026). Más temas vía RSS_FEEDS.
# - GlobeNewswire devuelve 403 (Akamai) en www.globenewswire.com a clientes
#   servidor; el espejo rss.globenewswire.com sirve el mismo feed con 200.
PRESS_WIRE_RSS_FEEDS: tuple[RSSFeed, ...] = (
    RSSFeed("https://www.prnewswire.com/rss/news-releases-list.rss", label="PR Newswire"),
    RSSFeed(
        "https://rss.globenewswire.com/RssFeed/orgclass/1/feedTitle/"
        "GlobeNewswire%20-%20News%20about%20Public%20Companies",
        label="GlobeNewswire",
    ),
    RSSFeed("https://feeds.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFpRVQ==", label="Business Wire"),
    RSSFeed("https://feeds.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQXw==", label="Business Wire"),
)

# Fuentes que son nota de prensa de agencia: las etiquetas actuales y los
# <title> de canal con que se guardaron los eventos históricos. La portada
# oculta las que no citan empresa conocida (ruido producto/lifestyle, medido
# en prod 19-oct-2026: 24/30 eventos de «Todas» eran agencia, 23/30 sin
# empresa); la ficha de empresa y el carril macro no se tocan.
PRESS_WIRE_SOURCES: frozenset[str] = frozenset(
    {
        "PR Newswire",
        "GlobeNewswire",
        "Business Wire",
        "All News Releases",
        "GlobeNewswire - News about Public Companies",
        "Business Wire Communications News",
        "Business Wire Technology: Telecommunications News",
    }
)


# Fuentes oficiales de gobierno y bancos centrales (RSS público, gratis, sin
# clave). URLs verificadas una a una el 29-oct-2026 (200 + application/rss+xml
# o text/xml con <rss>): whitehouse.gov/feed/ devuelve 404, el feed vivo es
# /news/feed/. Van al carril «gobierno»: news_lane en metadata, company_id
# NULL siempre (fail-closed, misma regla que el carril macro: un comunicado
# oficial no se vincula a una empresa sin evidencia primaria) y nunca
# disparan alertas de noticias seguidas.
GOV_NEWS_LANE = "gobierno"

GOV_RSS_FEEDS: tuple[RSSFeed, ...] = (
    RSSFeed("https://www.federalreserve.gov/feeds/press_all.xml", label="Reserva Federal (oficial)", lane=GOV_NEWS_LANE),
    RSSFeed("https://www.ecb.europa.eu/rss/press.html", label="BCE (oficial)", lane=GOV_NEWS_LANE),
    RSSFeed("https://www.whitehouse.gov/news/feed/", label="Casa Blanca (oficial)", lane=GOV_NEWS_LANE),
    RSSFeed("https://www.bankofengland.co.uk/rss/news", label="Banco de Inglaterra (oficial)", lane=GOV_NEWS_LANE),
    RSSFeed(
        "https://ec.europa.eu/commission/presscorner/api/rss?language=en",
        label="Comisión Europea (oficial)",
        lane=GOV_NEWS_LANE,
    ),
    RSSFeed(
        "https://www.bde.es/wbe/es/inicio/rss/rss-noticias/",
        label="Banco de España (oficial)",
        lane=GOV_NEWS_LANE,
    ),
    RSSFeed("https://www.lamoncloa.gob.es/Paginas/RSS.aspx", label="La Moncloa (oficial)", lane=GOV_NEWS_LANE),
)


def all_rss_feeds(value: str | None = None) -> list[RSSFeed]:
    """Agencias + fuentes oficiales de gobierno incluidas + RSS_FEEDS, sin duplicados."""

    return _unique_feeds([*PRESS_WIRE_RSS_FEEDS, *GOV_RSS_FEEDS, *configured_rss_feeds(value)])


def _unique_feeds(feeds: list[RSSFeed]) -> list[RSSFeed]:
    unique: list[RSSFeed] = []
    seen: set[tuple[str, str | None]] = set()
    for feed in feeds:
        key = (feed.url, feed.ticker)
        if key not in seen:
            seen.add(key)
            unique.append(feed)
    return unique


def _release_before_fetch(db) -> None:
    """Commit pending writes and return connection before network I/O.

    Fail closed on commit failure: do not discard caller writes and fetch
    anyway. Session identity and tenant scope survive the boundary.
    """
    if db is not None and hasattr(db, "in_transaction") and db.in_transaction():
        db.commit()


# Formularios SEC que entran al feed de noticias: los periodicos/corrientes
# (10-K/10-Q/8-K/20-F/6-K) mas SC 13D/13G y sus enmiendas (titulares >5%,
# fuente primaria de propiedad; EDGAR usa las dos familias de nombre).
DEFAULT_SEC_NEWS_FORMS: frozenset[str] = frozenset(
    {
        "10-K",
        "10-Q",
        "8-K",
        "20-F",
        "6-K",
        "SC 13D",
        "SC 13D/A",
        "SC 13G",
        "SC 13G/A",
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
    }
)


class FeedIngestionService:
    """Poll connectors and adapt their common result into existing ingestion services."""

    def __init__(self, *, sec_client: SECClient | None = None) -> None:
        self._sec_client = sec_client

    async def poll_rss(
        self,
        url: str,
        *,
        ticker: str | None = None,
        max_items: int = 100,
        connector: RSSConnector | None = None,
        source_label: str | None = None,
    ) -> ConnectorResult:
        result = await (connector or RSSConnector()).poll(
            url,
            ticker=ticker,
            max_items=max_items,
        )
        if source_label and result.items:
            result = replace(
                result,
                items=[replace(item, source=source_label) for item in result.items],
            )
        return result

    async def poll_gdelt(
        self,
        query: str,
        *,
        ticker: str | None = None,
        max_records: int = 50,
        connector: GDELTConnector | None = None,
    ) -> ConnectorResult:
        return await (connector or GDELTConnector()).poll(
            query,
            ticker=ticker,
            max_records=max_records,
        )

    async def poll_sec(
        self,
        cik: str,
        *,
        ticker: str | None = None,
        forms: set[str] | None = None,
        limit: int = 40,
        client: SECClient | None = None,
    ) -> ConnectorResult:
        sec = client or self._sec_client
        if sec is None:
            sec = SECClient()
            self._sec_client = sec
        return await sec.recent_filings(
            cik,
            forms=forms or DEFAULT_SEC_NEWS_FORMS,
            limit=limit,
            ticker=ticker,
        )

    async def poll_ir(
        self,
        ir_url: str,
        *,
        ticker: str | None = None,
        max_items: int = 100,
        connector: IRConnector | None = None,
    ) -> ConnectorResult:
        return await (connector or IRConnector()).poll(
            ir_url,
            ticker=ticker,
            max_items=max_items,
        )

    def ingest_news_result(
        self,
        db,
        result: ConnectorResult,
        *,
        ticker: str | None = None,
        news_lane: str | None = None,
        macro_theme: str | None = None,
        detect_company: bool = True,
        llm_deadline: float | None = None,
    ) -> dict:
        """Ingest connector items without importing model-dependent services at startup."""

        if not result.items:
            return {
                "status": result.status,
                "source": result.source,
                "received": 0,
                "created": 0,
                "skipped_duplicates": 0,
                "requires_update": 0,
                "errors": list(result.errors),
            }

        from app.schemas import NewsFeedItem
        from app.services.news_service import NewsService

        news_items = [
            NewsFeedItem(
                title=item.title,
                text=item.summary or None,
                ticker=item.ticker or ticker,
                url=item.url,
                source=item.source or result.source,
                published_at=item.published_at,
                headline_from_source=item.headline_from_source,
            )
            for item in result.items
        ]
        # Procedencia en la creación (misma transacción): connector = conector
        # real de la ingesta (gdelt/rss/ir/sec; fail-closed para alertas).
        # Un duplicado URL previo se salta y conserva su connector original.
        # GDELT: su published_at es seendate = primera detección, declarado
        # como gdelt_first_seen; si falta, queda ingested_at_fallback y NUNCA
        # se promociona. Históricos previos a la etiqueta quedan fuera.
        response = NewsService().ingest_news_items(
            db,
            news_items,
            default_source=result.source,
            connector=result.source,
            date_source_label="gdelt_first_seen" if result.source == "gdelt" else None,
            news_lane=news_lane,
            macro_theme=macro_theme,
            detect_company=detect_company,
            llm_deadline=llm_deadline,
        )
        payload = response.model_dump(mode="json")
        payload["source"] = result.source
        payload["connector_errors"] = list(result.errors)
        return payload

    async def ingest_document_url(
        self,
        db,
        *,
        ticker: str,
        title: str,
        url: str,
        source_type: str,
        published_at=None,
        filing_metadata: dict | None = None,
    ) -> dict:
        """Download a discovered document, preserving SEC request policy when needed."""

        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError("Only http(s) URLs can be ingested")
        is_sec_host = (parsed_url.hostname or "").lower() in {"sec.gov", "www.sec.gov"}
        final_url = url

        _release_before_fetch(db)
        if is_sec_host:
            content, content_type = await (self._sec_client or SECClient()).filing_document(url)
        else:
            content, content_type, final_url = await fetch_public_url_async(
                url, max_bytes=MAX_DOCUMENT_BYTES, timeout=30
            )

        from app.services.document_ingestion_service import DocumentIngestionService

        filename = PurePosixPath(parsed_url.path).name or f"{parsed_url.hostname}.html"
        result = DocumentIngestionService().ingest_bytes(
            db,
            ticker=ticker,
            title=title,
            content=content,
            filename=filename,
            source_type=source_type,
            source_url=final_url if not is_sec_host else url,
            content_type=content_type,
            published_at=published_at,
            filing_metadata=filing_metadata,
        )

        # 8-K Item 2.02 is often just a pointer. Fetch only earnings exhibits
        # declared in the official index, at most three, with the SEC client.
        if is_sec_host and (filing_metadata or {}).get("form") == "8-K":
            result["earnings_exhibits"] = await self._earnings_exhibits(
                db, ticker=ticker, url=url, published_at=published_at,
                filing_metadata=filing_metadata or {},
            )
        return result

    async def _earnings_exhibits(self, db, *, ticker, url, published_at, filing_metadata) -> list[dict]:
        from app.services.sec_filing_evidence import derive_index_url, parse_index

        accession = filing_metadata.get("accession_number")
        cik = filing_metadata.get("cik")
        if not accession or not cik:
            return [{"status": "insufficient_data", "reason": "Sin accession o CIK del 8-K."}]
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(accession)) or not str(cik).isdigit():
            return [{"status": "insufficient_data", "reason": "Identidad SEC inválida."}]
        sec = self._sec_client or SECClient()
        try:
            index_url = derive_index_url(str(cik), str(accession))
            _release_before_fetch(db)
            raw, _ = await sec.filing_document(index_url)
            index = parse_index(raw.decode("utf-8", errors="replace"))
            if index.accession != accession or int(index.cik) != int(cik):
                raise ValueError("SEC index identity mismatch")
            prefix = SECClient.filing_index_url(str(cik), str(accession))
            if not url.startswith(prefix):
                raise ValueError("8-K URL does not match index")
            results = []
            for filename, (form, _) in index.documents.items():
                if not form.startswith("EX-99"):
                    continue
                if len(results) >= 3:
                    results.append({"status": "partial", "reason": "Máximo de tres anexos por 8-K."})
                    break
                results.append(await self.ingest_document_url(
                    db, ticker=ticker, title=f"Comunicado adjunto al 8-K: {filename}",
                    url=SECClient.filing_document_url(str(cik), str(accession), filename),
                    source_type="SEC", published_at=published_at,
                    filing_metadata={**filing_metadata, "form": form, "parent_form": "8-K"},
                ))
            return results or [{"status": "insufficient_data", "reason": "Sin anexos EX-99 en el índice SEC."}]
        except Exception as exc:
            return [{"status": "unavailable", "error": type(exc).__name__}]
