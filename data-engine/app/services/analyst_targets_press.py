"""Complemento de prensa para el panel de precios objetivo por analista.

Yahoo (yfinance) ingiere las notas con latencia: una reiteración de hoy no
aparece en el panel hasta dentro de días (caso real: Cantor Fitzgerald
reiteró 90 $ sobre ASTS el 2026-11-09 y Yahoo seguía mostrando la nota de
agosto). La prensa financiera publica la nota el mismo día.

Este módulo descubre artículos con el RSS público de Bing News (el patrón ya
establecido en ``analyst_press_estimates``), lee el artículo respetando
robots.txt (agente declarado, ritmo de 1 req/s, tope de bytes) y, si el medio
bloquea la lectura automatizada (Cloudflare, muro de pago), usa el fragmento
literal que el propio medio publica en su titular y descripción del RSS. La
extracción es determinista (expresiones regulares, sin LLM): una fila solo
nace de una frase que cita a la firma y al objetivo; sin firma, sin fecha o
con divisa no verificable no hay fila, nunca se infiere. Cada fila lleva el
medio y el enlace al artículo, y su fecha es la de publicación del artículo.

El consenso agregado NUNCA se recalcula con prensa: sigue siendo el de Yahoo.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse

from app.services.analyst_history_service import normalize_firm
from app.services.analyst_press_estimates import (
    DOLLAR_MARKS,
    USER_AGENT,
    Robots,
    article_text,
    firms_in,
    marked_currency,
    press_actions,
    published_from_html,
    resolve_currency,
    sentence_split,
)

BING_NEWS_RSS = "https://www.bing.com/news/search?q={query}&format=rss&count=30"
MAX_CANDIDATES = 30
MAX_ARTICLES_READ = 4
MAX_FIRM_QUERIES = 4
MAX_ARTICLE_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_S = 6.0
MIN_INTERVAL_S = 1.0
LOOKBACK_DAYS = 180
# Mínimo de texto legible para considerar que el artículo se pudo leer; por
# debajo es un muro (Cloudflare, paywall) y se usa el fragmento del RSS.
MIN_ARTICLE_CHARS = 200

# Marcas de divisa que la frase puede escribir junto al objetivo y su código.
# Un «$» a secas lo resuelve resolve_currency (USD salvo dólares ambiguos).

# Medios frecuentes en notas de analistas: nombre corto para la atribución.
_OUTLET_NAMES = {
    "streetinsider.com": "StreetInsider",
    "investing.com": "Investing.com",
    "benzinga.com": "Benzinga",
    "thefly.com": "TheFly",
    "barrons.com": "Barron's",
    "marketwatch.com": "MarketWatch",
    "fool.com": "Motley Fool",
    "seekingalpha.com": "Seeking Alpha",
    "tipranks.com": "TipRanks",
    "zacks.com": "Zacks",
    "marketbeat.com": "MarketBeat",
    "stocktitan.net": "StockTitan",
    "globenewswire.com": "GlobeNewswire",
    "businesswire.com": "Business Wire",
    "reuters.com": "Reuters",
    "finance.yahoo.com": "Yahoo Finance",
    "msn.com": "MSN",
    "morningstar.com": "Morningstar",
}

# Lista cerrada de medios fiables para esta fuente (criterio del auditor):
# prensa financiera con redacción identificable y notas de analistas
# verificables; agregadores de contenido de usuarios (Stocktwits) o blogs no
# entran aunque su robots.txt lo permita. Cualquier ítem fuera de la lista se
# descarta antes de leerlo.
_TRUSTED_DOMAINS = frozenset(_OUTLET_NAMES)


def _trusted(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in _TRUSTED_DOMAINS)

# Como el patrón de analyst_press_estimates, pero admite además la forma
# «price target on AST Spacemobile to $54» (habitual en prensa: el objetivo
# tras «on <empresa>»). El patrón del colector de estimaciones no se toca:
# alimenta inputs declarados de valoración y su cobertura es deliberada.
_PRICE_TARGET_PANEL = re.compile(
    r"\$\s?(?P<a>\d{1,5}(?:\.\d{1,2})?)\s(?:share\s)?price target"
    r"|price target\b[^.]{0,60}?\b(?:of|to|at|is)\s(?:[A-Z]{1,3})?\$\s?(?P<b>\d{1,5}(?:\.\d{1,2})?)"
    r"|target (?:to|of)\s(?:[A-Z]{1,3})?\$\s?(?P<c>\d{1,5}(?:\.\d{1,2})?)", re.I)
_PRIOR_TARGET = re.compile(
    r"\bfrom\s(?:[A-Z]{1,3})?\$\s?(?P<prior>\d{1,5}(?:\.\d{1,2})?)", re.I)

# Alias LOCALES del panel (no se toca FIRM_ALIASES de analyst_history_service:
# es compartido con thesis_service y analyst_blend). La prensa cita a la casa
# como «Roth» a secas; es la misma firma que Yahoo llama «Roth Capital».
_PRESS_FIRM_ALIASES = {"roth": "Roth Capital"}

# Marca de divisa no reconocida junto al «$» («XYZ$90»): marked_currency la
# deja en None y un «$» a secas resolvería a USD; con marca desconocida la
# fila se descarta (auditor: la divisa no puede ser fail-open).
_ANY_MARK = re.compile(r"\b([A-Za-z]{1,3})\$")
# Códigos de divisa mencionados en la frase («(CAD)»); cada uno debe resolver
# a la divisa declarada por Yahoo o la fila se descarta al fusionar.
_CURRENCY_MENTION = re.compile(
    r"\b(USD|CAD|AUD|HKD|NZD|SGD|TWD|MXN|EUR|GBP|CHF|JPY|BRL|ZAR|SEK|NOK|DKK|GBX|GBp)\b")

# Fechas de la nota respaldadas por el texto (auditor: la fecha de publicación
# solo vale si el texto no dice otra). «on November 3» fija el día; «on
# Monday» fija el día de esa semana. Fecha futura = fila descartada.
_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
             "saturday": 5, "sunday": 6}
_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
           "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
_ON_WEEKDAY = re.compile(r"\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
_ON_MONTH_DAY = re.compile(
    r"\bon (january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)


def note_date(sentence: str, *, published: date, today: date) -> date | None:
    """Fecha de la nota: la que respalda el texto o, sin ancla, la de publicación.

    None cuando no hay fecha verificable (publicación en el futuro o ancla que
    cae en el futuro): sin fecha verificable no hay fila.
    """
    if published > today:
        return None
    match = _ON_MONTH_DAY.search(sentence)
    if match:
        try:
            day = date(published.year, _MONTHS[match.group(1).lower()], int(match.group(2)))
        except ValueError:
            return None
        if day > published:
            # Solo retrospectiva clara de año anterior («on December 15»
            # publicado en enero). Un ancla unos días por delante de la
            # publicación («on November 13» publicado el 9) es un plan futuro
            # o un error: fecha no verificable, sin fila.
            if (day - published).days <= 300:
                return None
            day = date(published.year - 1, day.month, day.day)
        return None if day > today else day
    match = _ON_WEEKDAY.search(sentence)
    if match:
        delta = (published.weekday() - _WEEKDAYS[match.group(1).lower()]) % 7
        day = published - timedelta(days=delta)
        return None if day > today else day
    return published


# Tokens en mayúsculas que no son tickers de otra empresa: siglas de mercado,
# métricas y rangos habituales en notas de analistas.
_STOP_TICKER_TOKENS = {
    "PT", "EPS", "EBITDA", "CEO", "CFO", "USD", "US", "USA", "NASDAQ", "NYSE", "AI", "EV",
    "IPO", "ETF", "ADR", "ADS", "FCF", "PE", "PS", "PB", "Q1", "Q2", "Q3", "Q4", "FY",
    "TM", "AM", "PM", "ET", "CT", "EST", "CET", "SEC", "FDA", "FAA", "FCC",
    # Códigos de divisa: no son tickers ajenos (la divisa se verifica aparte).
    "CAD", "AUD", "EUR", "GBP", "CHF", "JPY", "MXN", "BRL", "ZAR", "HKD", "NZD", "SGD",
    "TWD", "SEK", "NOK", "DKK", "GBX",
}
_TICKER_TOKEN = re.compile(r"(?<![\w$.])([A-Z][A-Z0-9]{1,4})(?![\w])")


def _foreign_ticker(sentence: str, symbol: str, firm: str) -> bool:
    """True si la frase cita OTRO ticker además del símbolo pedido.

    Guardia contra la contaminación cruzada: «…price target on AAPL» en un
    artículo que menciona ASTS no puede producir una fila para ASTS. Los
    tokens del nombre de la firma (UBS, RBC, TD, BMO…) no cuentan.
    """
    firm_tokens = {t.upper() for t in re.findall(r"[A-Za-z0-9.]+", firm)}
    for token in _TICKER_TOKEN.findall(sentence):
        if token in _STOP_TICKER_TOKENS or token in firm_tokens:
            continue
        # El nombre propio de la empresa puede contener un token en mayúsculas
        # emparentado con el ticker (AST en «AST Spacemobile», ticker ASTS).
        if token in symbol or symbol in token:
            continue
        return True
    return False
_RATINGS = (
    "Speculative Buy", "Market Outperform", "Market Perform", "Sector Perform", "Equal Weight",
    "Equal-Weight", "Overweight", "Underweight", "Outperform", "Underperform", "Neutral",
    "Buy", "Sell", "Hold", "Positive", "Negative",
)
_RATING = re.compile(r"\b(" + "|".join(re.escape(r) for r in _RATINGS) + r")\s+rating\b", re.I)
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class PressItem:
    url: str
    title: str
    description: str
    published: date | None


@dataclass(frozen=True)
class PressTarget:
    firm: str
    date: date
    price_target: float
    prior_target: float | None
    rating: str | None
    action: str | None
    outlet: str
    url: str
    # Marca de divisa escrita en la frase (US$, C$…; None = «$» a secas). El
    # filtro contra la divisa declarada por Yahoo se aplica al fusionar.
    currency_mark: str | None
    # Códigos de divisa mencionados en la frase («(CAD)»); al fusionar, todos
    # deben resolver a la divisa declarada por Yahoo o la fila se descarta.
    currency_mentions: tuple[str, ...] = ()
    # True si la fila se extrajo del cuerpo del artículo; False si sale del
    # fragmento (titular+descripción) del RSS.
    full_text: bool = False


def outlet_name(url: str) -> str:
    """Nombre corto del medio para la atribución de la fila."""
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label]
    registrable = ".".join(labels[-2:]) if len(labels) >= 2 else host
    if host in _OUTLET_NAMES:
        return _OUTLET_NAMES[host]
    if registrable in _OUTLET_NAMES:
        return _OUTLET_NAMES[registrable]
    return (labels[-2] if len(labels) >= 2 else host).capitalize() or urlparse(url).netloc


def rss_items(xml: str) -> list[PressItem]:
    """Ítems de un RSS de Bing News con enlace real, titular, fragmento y fecha."""
    items: list[PressItem] = []
    for chunk in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        link = re.search(r"<link>(.*?)</link>", chunk, re.S)
        if not link:
            continue
        raw = unescape(link.group(1).strip())
        target = parse_qs(urlparse(raw).query).get("url", [raw])[0]
        if urlparse(target).scheme != "https":
            continue
        title = re.search(r"<title>(.*?)</title>", chunk, re.S)
        description = re.search(r"<description>(.*?)</description>", chunk, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", chunk, re.S)
        day = None
        if pub:
            try:
                day = parsedate_to_datetime(unescape(pub.group(1).strip())).date()
            except (TypeError, ValueError):
                day = None
        items.append(PressItem(
            url=target,
            title=unescape(title.group(1).strip()) if title else "",
            description=unescape(re.sub(r"\s+", " ", _TAG.sub(" ", description.group(1)))).strip() if description else "",
            published=day,
        ))
    return items


def _mentions_symbol(text: str, symbol: str) -> bool:
    """El ticker aparece como palabra (guardia contra colisiones de ticker)."""
    return bool(re.search(r"(?<![\w.])" + re.escape(symbol) + r"(?!\w)", text))


def extract_targets(text: str, *, symbol: str, published: date, url: str, full_text: bool,
                    today: date | None = None) -> list[PressTarget]:
    """Objetivos por firma citados literalmente en un texto de prensa.

    Solo frases con firma y objetivo; sin firma única atribuible no hay fila.
    La divisa queda como marca declarada en la frase para que quien fusiona la
    verifique contra la divisa declarada del listado. La fecha de la fila es
    la que respalda el texto («on November 3», «on Monday») o, sin ancla, la
    de publicación; una fecha futura descarta la fila.
    """
    today = today or published
    if not _mentions_symbol(text, symbol):
        return []
    outlet = outlet_name(url)
    article_firms = firms_in(text)
    found: list[PressTarget] = []
    for sentence in sentence_split(text):
        match = _PRICE_TARGET_PANEL.search(sentence)
        if match is None:
            continue
        # Firma, cifra y empresa/ticker en la MISMA frase: un artículo que
        # menciona ASTS de pasada no convierte el objetivo de OTRA empresa en
        # una fila de ASTS.
        if not _mentions_symbol(sentence, symbol):
            continue
        own = firms_in(sentence)
        firm = own[0] if len(own) == 1 else (article_firms[0] if not own and len(article_firms) == 1 else None)
        if firm is None:
            continue
        canonical_firm = _PRESS_FIRM_ALIASES.get(firm.lower()) or normalize_firm(firm) or firm
        if _foreign_ticker(sentence, symbol, firm):
            continue
        # Marca de divisa no reconocida («XYZ$90»): la fila no es verificable.
        if any(m.group(1).upper() not in DOLLAR_MARKS for m in _ANY_MARK.finditer(sentence)):
            continue
        day = note_date(sentence, published=published, today=today)
        if day is None:
            continue
        value = match.group("a") or match.group("b") or match.group("c")
        try:
            target = float(value)
        except (TypeError, ValueError):
            continue
        if target <= 0:
            continue
        num_start = match.start("a") if match.group("a") else (match.start("b") if match.group("b") else match.start("c"))
        prior = None
        prior_match = _PRIOR_TARGET.search(sentence)
        if prior_match:
            prior_value = float(prior_match.group("prior"))
            # «raised to 54 from 98»: el anterior no puede ser el mismo número.
            if 0 < prior_value != target:
                prior = prior_value
        rating_match = _RATING.search(sentence)
        action = next((name for name, rx in press_actions() if rx.search(sentence)), None)
        found.append(PressTarget(
            firm=canonical_firm,
            date=day,
            price_target=target,
            prior_target=prior,
            rating=rating_match.group(1) if rating_match else None,
            action=action,
            outlet=outlet,
            url=url,
            currency_mark=marked_currency(sentence, num_start - 4),
            currency_mentions=tuple(m.group(1) for m in _CURRENCY_MENTION.finditer(sentence)),
            full_text=full_text,
        ))
    return found


async def _default_fetch(url: str):
    from app.services.public_fetch import fetch_public_url_async

    return await fetch_public_url_async(
        url, timeout=FETCH_TIMEOUT_S, max_bytes=MAX_ARTICLE_BYTES, headers={"User-Agent": USER_AGENT})


def base_queries(symbol: str) -> list[str]:
    """Consulta general de descubrimiento para un símbolo."""
    return [f'"{symbol}" price target analyst']


def firm_queries(symbol: str, firms: list[str]) -> list[str]:
    """Una consulta por firma: Bing posiciona mejor «"ASTS" "Cantor Fitzgerald"»
    que la consulta general para notas de ESA casa (comprobado en vivo: la nota
    de Cantor del 10 ago 2026 salía con la consulta por firma y no con la
    general). Se usa con las firmas cuya fila de Yahoo va envejecida."""
    return [f'"{symbol}" "{firm}"' for firm in firms[:MAX_FIRM_QUERIES]]


async def fetch_press_targets(symbol: str, *, today: date, queries: list[str] | None = None,
                              fetch=None) -> list[PressTarget]:
    """Objetivos de analistas publicados en prensa reciente para ``symbol``.

    Mejor esfuerzo: cualquier fallo de red o de un medio deja esa fuente fuera
    sin afectar a las demás. Ritmo de 1 petición/s y robots.txt respetado en
    cada lectura de artículo. ``queries`` permite una segunda pasada con
    consultas por firma; por defecto se usa la consulta general.
    """
    if fetch is None:
        fetch = _default_fetch
    symbol = symbol.strip().upper()
    if not symbol:
        return []
    earliest = today - timedelta(days=LOOKBACK_DAYS)
    last = 0.0

    async def paced(url: str):
        nonlocal last
        wait = MIN_INTERVAL_S - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        last = time.monotonic()
        return await fetch(url)

    items: list[PressItem] = []
    for query in (queries if queries is not None else base_queries(symbol)):
        try:
            content, _, _ = await paced(BING_NEWS_RSS.format(query=quote_plus(query)))
        except Exception:  # noqa: BLE001 - sin esa búsqueda no pasa nada
            continue
        items.extend(rss_items(content.decode("utf-8", errors="replace")))
    items = sorted(
        (item for item in items
         if item.published is not None and earliest <= item.published <= today),
        key=lambda item: item.published or date.min, reverse=True)[:MAX_CANDIDATES]
    robots = Robots()
    targets: list[PressTarget] = []
    articles_read = 0
    seen: set[str] = set()
    for item in items:
        key = item.url.split("#")[0]
        if key in seen or not _trusted(item.url):
            continue
        seen.add(key)
        rows: list[PressTarget] = []
        if articles_read < MAX_ARTICLES_READ and await robots.allowed(item.url, fetch):
            articles_read += 1
            try:
                content, _, _ = await paced(item.url)
            except Exception:  # noqa: BLE001 - medio caído o bloqueado: fragmento
                content = b""
            text = article_text(content.decode("utf-8", errors="replace")) if content else ""
            # Fecha del artículo en su HTML o, sin ella, la del RSS (ambas reales).
            day = (published_from_html(content.decode("utf-8", errors="replace")) if content else None) or item.published
            if len(text) >= MIN_ARTICLE_CHARS and day <= today:
                rows = extract_targets(text, symbol=symbol, published=day, url=item.url,
                                       full_text=True, today=today)
        if not rows:
            snippet = f"{item.title}. {item.description}".strip(". ")
            rows = extract_targets(snippet, symbol=symbol, published=item.published, url=item.url,
                                   full_text=False, today=today)
        targets.extend(rows)
    # Una fila por firma: la más reciente; a igual fecha, la de artículo leído.
    latest: dict[str, PressTarget] = {}
    for row in targets:
        key = row.firm.casefold()
        current = latest.get(key)
        if current is None or (row.date, row.full_text) > (current.date, current.full_text):
            latest[key] = row
    return sorted(latest.values(), key=lambda row: (row.date, row.firm), reverse=True)


def currency_matches(mark: str | None, declared: str | None,
                     mentions: tuple[str, ...] = ()) -> bool:
    """True solo si la frase es verificable en la divisa declarada por Yahoo.

    Fail-closed (auditor): sin divisa declarada no se acepta nada; una marca
    «$» a secas solo resuelve cuando la declarada no es ambigua; cualquier
    código mencionado en la frase («(CAD)») que no sea la declarada descarta.
    """
    if not declared:
        return False
    wanted = declared.strip().upper()
    for mention in mentions:
        # «GBp» (peniques) y «GBX» son la misma subunidad; «GBP» es la libra.
        normalized = {"GBp": "GBX"}.get(mention, mention).upper()
        if normalized != wanted:
            return False
    if mentions and mark is None:
        # La propia frase declara la divisa («(CAD)») y cuadra con la declarada.
        return True
    resolved = resolve_currency(mark, declared)
    return resolved is not None and resolved.upper() == wanted
