"""Herramientas en vivo del Cerebro: cotización y noticias pedidas al proveedor.

El Cerebro responde por defecto con los datos guardados (siempre fechados y
con su fuente); estas herramientas consultan el proveedor gratuito EN EL
MOMENTO de la pregunta cuando el usuario pide el precio o las noticias de
ahora de una empresa del catálogo.

Fail-closed: proveedor caído, lento o sin dato devuelve ``None`` y la
pregunta cae en la ruta determinista de datos guardados, que ya etiqueta
que no es en directo. Nunca se inventa una cotización ni un titular: cada
cifra viaja con su fuente y su marca temporal, y un precio con el mercado
cerrado se presenta como cierre fechado, no como cotización actual.
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import current_language_is_english as _english
from app.core.local_date import USER_TIMEZONE
from app.models import Company
from app.schemas import ChatResponse
from app.services.brain_data_tools import (
    _NAME_NOISE,
    _company_in_question,
    _date_en,
    _money,
    _squash,
)
from app.services.connectors.gdelt import (
    GDELT_ALLOWED_LANGUAGES,
    GDELTClient,
    _gdelt_datetime,
)
from app.services.connectors.yahoo import yahoo_chart_symbol
from app.services.display_es import fecha_es as _fecha_es
from app.services.extended_quote_service import ExtendedQuote, extended_quote_service

_QUOTE_TIMEOUT_SECONDS = 6.0
_NEWS_TIMEOUT_SECONDS = 8.0
_MAX_COMPANIES = 4
_MAX_LIVE_NEWS = 5
_NEWS_FETCH_RECORDS = 10

_PRICE_ASK_RE = re.compile(
    r"(?i)\b(?:precio|cotiza\w*|cu[aá]nto\s+vale|a\s+cu[aá]nto\s+est[aá]n?|"
    r"a\s+c[oó]mo\s+est[aá]n?|c[oó]mo\s+(?:va|cotiza)|price\s+of|quote\s+for)\b"
)
# El coste de compra, la valoración y los fundamentales (PER/BPA) los
# responden las rutas de datos guardados: no son una cotización en vivo.
_PRICE_EXCLUDE_RE = re.compile(
    r"(?i)\b(?:compra|comprar|compr[eé]|pagu[eé]|vende|vender|ejecuta|buy|sell|"
    r"medio|coste|peso|posici[oó]n|cartera|tengo)\b|\bprecio\s+de\s+compra\b|"
    r"\bprecio\s+objetivo\b|\bvalor\s+(?:justo|intr[ií]nseco|esperado|objetivo)\b|"
    r"\bmargen\s+de\s+seguridad\b|\bPER\b|\bBPA\b|\btarget\s+price\b|"
    # Preguntas mixtas con fundamentales (margen FCF, ingresos...): las
    # responde la ruta guardada, que contesta las dos partes con fuentes.
    r"\bmargen|fcf|free\s+cash|ingresos?|revenue|beneficio|deuda|crecimiento|"
    r"ebitda|flujo|ventas|resultados\b"
)
_NEWS_ASK_RE = re.compile(
    r"(?i)\b(?:noticias?|novedades?|[úu]ltima\s+hora|qu[eé]\s+ha\s+pasado|"
    r"qu[eé]\s+pasa\s+con|news\s+(?:on|about)|latest\s+on)\b"
)
# «Noticias de mis empresas / mi cartera» ya las responde la ruta guardada
# acotada a las posiciones abiertas del tenant.
_NEWS_EXCLUDE_RE = re.compile(
    r"(?i)\bmis\s+(?:empresas|acciones|posiciones)\b|\bmi\s+cartera\b|"
    r"\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b"
)


def _live_calls_allowed() -> bool:
    """APP_ENV=test nunca sale a red: determinismo de la suite.

    Los tests de esta herramienta sustituyen esta guarda (monkeypatch) e
    inyectan el proveedor; el resto de la suite conserva el comportamiento
    determinista de siempre. En local y prod la consulta en vivo sí corre.
    """
    return get_settings().app_env.strip().lower() != "test"

_SESSION_LABELS = {
    "pre": ("preapertura", "pre-market"),
    "regular": ("mercado abierto", "market open"),
    "post": ("post-mercado", "post-market"),
    "cerrado": ("mercado cerrado", "market closed"),
}


def _pct(value: float, english: bool) -> str:
    rendered = f"{value:+.2f}"
    return rendered if english else rendered.replace(".", ",")


def _instante(epoch: int, english: bool) -> str:
    """«15 nov 2026, 22:34» / «Nov 15, 2026, 16:34», hora de Madrid (la del usuario)."""
    instant = datetime.fromtimestamp(epoch, UTC).astimezone(USER_TIMEZONE)
    day = _date_en(instant) if english else _fecha_es(instant)
    return f"{day}, {instant:%H:%M}"


def _companies_in_question(
    db: Session, question: str, page_company: Company | None
) -> list[Company]:
    """Empresas del catálogo nombradas (ticker o nombre), o la de la página.

    Misma regla que la ruta guardada: tickers exactos del master en el orden
    en que los nombra el usuario; si no, el nombre exacto único; si no, la
    empresa de la pastilla «Viendo X». Nunca se adivina una empresa.
    """
    tokens = re.findall(r"\b[A-Z][A-Z0-9.-]{1,14}\b", question)
    # Cobertura completa o nada antes de consultar proveedores: ni un ticker
    # desconocido ni el límite operativo pueden desaparecer de la respuesta.
    if len(set(tokens)) > _MAX_COMPANIES:
        return []
    companies = (
        list(db.scalars(select(Company).where(Company.ticker.in_(set(tokens)))).all())
        if tokens
        else []
    )
    if tokens and {item.ticker for item in companies} != set(tokens):
        return []
    if companies:
        order = {ticker: index for index, ticker in reversed(list(enumerate(tokens)))}
        companies.sort(key=lambda item: order.get(item.ticker, len(tokens)))
    else:
        named = _company_in_question(db, question)
        companies = [named] if named is not None else []
    if not companies and page_company is not None and not tokens:
        companies = [page_company]
    return companies


def _quote_line(company: Company, quote: ExtendedQuote, english: bool) -> str:
    price_value, timestamp = quote.price, quote.timestamp
    if price_value is None or timestamp is None:
        # El filtro de _live_quote_answer ya lo exige; la guarda tipa el acceso.
        return ""
    session_es, session_en = _SESSION_LABELS[quote.session]
    session = session_en if english else session_es
    price = _money(price_value, quote.currency or company.currency)
    instant = _instante(timestamp, english)
    if quote.session == "cerrado" and quote.price_session in {"pre", "post"}:
        price_session = _SESSION_LABELS[quote.price_session][1 if english else 0]
        if english:
            return (f"**{company.ticker} · {company.name}**: {price}, last {price_session} quote "
                    f"({instant}; {quote.source}). Market closed.")
        return (f"**{company.ticker} · {company.name}**: {price}, última cotización de {price_session} "
                f"({instant}; {quote.source}). Mercado cerrado.")
    if quote.session == "cerrado":
        if english:
            return (f"**{company.ticker} · {company.name}**: {price} at the close "
                    f"({instant}; {quote.source}). Market closed.")
        return (f"**{company.ticker} · {company.name}**: {price} al cierre "
                f"({instant}; {quote.source}). Mercado cerrado.")
    change = ""
    if quote.change_percent is not None:
        change = f"{_pct(quote.change_percent, english)} % {'in the session, ' if english else 'en la sesión, '}"
    delayed = ""
    if quote.status == "retrasado":
        delayed = " Delayed quote." if english else " Cotización con retraso."
    if english:
        return (f"**{company.ticker} · {company.name}**: {price} ({change}at {instant}, "
                f"{session}; {quote.source}).{delayed}")
    return (f"**{company.ticker} · {company.name}**: {price} ({change}a las {instant}, "
            f"{session}; {quote.source}).{delayed}")


async def _live_quote_answer(companies: list[Company]) -> ChatResponse | None:
    english = _english()

    async def fetch(ticker: str) -> ExtendedQuote:
        try:
            return await asyncio.wait_for(
                extended_quote_service.get(ticker), timeout=_QUOTE_TIMEOUT_SECONDS
            )
        except Exception:  # noqa: BLE001 - fail-closed: esa empresa queda sin dato en vivo
            return ExtendedQuote(ticker=ticker, fetched_at=int(datetime.now(UTC).timestamp()))

    quotes = await asyncio.gather(*(fetch(company.ticker) for company in companies))
    # Precio sin marca temporal no se muestra: nunca una cifra sin su fecha.
    live = [
        (company, quote)
        for company, quote in zip(companies, quotes, strict=True)
        if quote.price is not None and quote.timestamp is not None and quote.status != "unavailable"
    ]
    if not live:
        return None
    failed = [company for company, quote in zip(companies, quotes, strict=True)
              if quote.price is None or quote.timestamp is None or quote.status == "unavailable"]
    lines = [line for company, quote in live if (line := _quote_line(company, quote, english))]
    for company in failed:
        lines.append(
            f"**{company.ticker} · {company.name}**: no live quote right now "
            "(the provider did not answer)."
            if english else
            f"**{company.ticker} · {company.name}**: sin cotización en directo "
            "ahora (el proveedor no ha respondido)."
        )
    sources = [
        {
            "type": "live_quote",
            "id": quote.timestamp or 0,
            "title": f"Quote {company.ticker} · Yahoo Finance" if english
                     else f"Cotización {company.ticker} · Yahoo Finance",
            "url": f"https://finance.yahoo.com/quote/{yahoo_chart_symbol(company.ticker)}",
        }
        for company, quote in live
    ]
    return ChatResponse(
        answer="\n\n".join(lines),
        sources=sources,
        model="deterministic",
        prompt_version="brain-live-v1",
        confidence=0.9,
        llm_trace={"path": "live_quote", "provider_calls": 0, "generated": False},
    )


async def _live_news_answer(company: Company) -> ChatResponse | None:
    english = _english()
    try:
        payload = await asyncio.wait_for(
            GDELTClient().news_search(f'"{company.name}"', max_records=_NEWS_FETCH_RECORDS),
            timeout=_NEWS_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 - fail-closed (429, red, JSON roto): cae a los guardados
        return None
    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        return None
    core = _squash(" ".join(
        word for word in re.split(r"[\s,.]+", company.name.lower())
        if word and word not in _NAME_NOISE
    ))
    seen: set[str] = set()
    items: list[tuple[str, str, datetime | None, str]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        language = article.get("language")
        if isinstance(language, str) and language.lower() not in GDELT_ALLOWED_LANGUAGES:
            continue
        raw_title, raw_url = article.get("title"), article.get("url")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        url = raw_url.strip() if isinstance(raw_url, str) else ""
        if not title or not url:
            continue
        try:
            parsed_url = urlsplit(url)
            if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
                continue
        except ValueError:
            continue
        # Relevancia fail-closed: solo titulares que citan a la empresa por
        # ticker o por nombre; GDELT ordena por relevancia híbrida y a veces
        # cuela noticias de otra empresa.
        ticker_named = re.search(
            rf"(?i)(?<![A-Za-z0-9]){re.escape(company.ticker)}(?![A-Za-z0-9])", title
        ) is not None
        if not ticker_named and (len(core) < 4 or core not in _squash(title)):
            continue
        key = " ".join(title.lower().split())
        if key in seen:
            continue
        seen.add(key)
        raw_date, raw_domain = article.get("seendate"), article.get("domain")
        seen_at = _gdelt_datetime(raw_date) if isinstance(raw_date, str) else None
        domain = raw_domain.strip() if isinstance(raw_domain, str) else ""
        items.append((title, url, seen_at, domain))
        if len(items) == _MAX_LIVE_NEWS:
            break
    if not items:
        return None
    items.sort(key=lambda item: item[2] or datetime.min.replace(tzinfo=UTC), reverse=True)
    lines = [
        f"Live news on {company.name} (GDELT search run now; headlines in their original language):"
        if english else
        f"Noticias en vivo sobre {company.name} (búsqueda GDELT de ahora; titulares en su idioma original):"
    ]
    sources: list[dict] = []
    for title, url, seen_at, domain in items:
        if seen_at is not None:
            stamp = _date_en(seen_at) if english else _fecha_es(seen_at)
        else:
            stamp = "undated" if english else "sin fecha"
        domain_part = f" - {domain}" if domain else ""
        lines.append(f"- '{title}'{domain_part}, {stamp} (GDELT).")
        sources.append({"type": "live_news", "id": url,
                        "title": f"{company.ticker}: {title}", "url": url})
    return ChatResponse(
        answer="\n\n".join(lines),
        sources=sources,
        model="deterministic",
        prompt_version="brain-live-v1",
        confidence=0.9,
        llm_trace={"path": "live_news", "provider_calls": 0, "generated": False},
    )


async def answer_live_question(
    db: Session, question: str, page_company: Company | None = None
) -> ChatResponse | None:
    """Respuesta con datos pedidos al proveedor ahora, o None si no procede.

    ``None`` significa «esta herramienta no se hace cargo»: la pregunta no
    pide dato en vivo, no nombra empresa del catálogo, o el proveedor falló;
    la ruta normal (datos guardados, siempre fechados) responde después.
    """
    text = (question or "").strip()
    if not text or not _live_calls_allowed():
        return None
    price_ask = bool(_PRICE_ASK_RE.search(text)) and not _PRICE_EXCLUDE_RE.search(text)
    news_ask = bool(_NEWS_ASK_RE.search(text)) and not _NEWS_EXCLUDE_RE.search(text)
    if not (price_ask or news_ask):
        return None
    companies = _companies_in_question(db, text, page_company)
    if not companies:
        return None
    parts: list[str] = []
    sources: list[dict] = []
    paths: list[str] = []
    if price_ask:
        quote = await _live_quote_answer(companies)
        if quote is not None:
            parts.append(quote.answer)
            sources.extend(quote.sources)
            paths.append("live_quote")
    if news_ask and len(companies) == 1:
        news = await _live_news_answer(companies[0])
        if news is not None:
            parts.append(news.answer)
            sources.extend(news.sources)
            paths.append("live_news")
    # Una respuesta mixta no debe silenciar la mitad fallida: toda la
    # pregunta sigue a la ruta guardada si falta alguna parte solicitada.
    if (price_ask and "live_quote" not in paths) or (news_ask and "live_news" not in paths):
        return None
    if not parts:
        return None
    return ChatResponse(
        answer="\n\n".join(parts),
        sources=sources,
        model="deterministic",
        prompt_version="brain-live-v1",
        confidence=0.9,
        llm_trace={"path": "+".join(paths), "provider_calls": 0, "generated": False},
    )
