"""Estimaciones de analistas recopiladas solas de la prensa gratuita, por firma y año.

Caso real (8-nov-2026): Nico pide que GerarAI reúna las estimaciones de los
analistas por sí mismo. La nota de Clear Street sobre ASTS no está en ninguna
fuente de datos gratuita, pero la prensa la cita con cifras: Advanced
Television (13-ago-2026) publica «Total estimated revenues of $165 million, and
2027 of $557 million, 2028 of $1.9 billion…», y TheFly/StreetInsider/Yahoo
recogen precios objetivo («reiterated a Buy rating and $115 price target»).

Qué hace (determinista, sin LLM y nada por ticker):

1. **Descubre artículos** de la empresa que citan a analistas: las noticias que
   GerarAI ya guarda (``news_events``) y el RSS público de Bing News con dos
   consultas generales («"<nombre>" analyst estimates», «"<nombre>" price
   target»). El RSS de Bing trae la URL del medio en el enlace, sin redirección.
   Google News queda fuera para esto: su robots.txt prohíbe ``/rss/articles`` y
   sus enlaces no llevan la URL del medio.
2. **Lee cada artículo** respetando su robots.txt (si lo prohíbe, se salta y se
   dice), con User-Agent propio, tope de tamaño y ritmo de 1 petición/s.
3. **Extrae por frase**: una cifra es una estimación si la frase (o la anterior)
   nombra a una firma de análisis y la cifra va con un año («2027 of $557
   million», «$1.9 billion in 2028», «2028E revenue of $X», «this year»). La
   magnitud sale de la palabra más cercana (revenue/sales, adjusted EBITDA,
   EBITDA, EPS). Precio objetivo: «$115 price target», «price target of $115»,
   «target to $54». Frases de consenso («analysts expect», «consensus») se
   guardan como firma «Consenso (prensa)», nunca como una firma concreta.
4. **Guarda** cada estimación en ``declared_input_values`` (method='analyst',
   clave ``analyst.<métrica>.fy<año>.<firma>``, firma, fecha del artículo, URL y
   frase literal) y la nota en ``analyst_notes`` (con ``estimates`` por año),
   que son lo que ya leen los expertos y el histórico de revisiones. Una cifra
   más antigua nunca pisa a una más reciente de la misma firma.
"""

from __future__ import annotations

import asyncio
import re
import time
import urllib.robotparser
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

USER_AGENT = "GerarAI research bot (+https://github.com/nicogarrr/GerarAI; tab@tab.bot)"
BING_NEWS_RSS = "https://www.bing.com/news/search?q={query}&format=rss"
DISCOVERY_QUERIES = ('"{name}" analyst estimates revenue', '"{name}" price target analyst')
MAX_ARTICLES = 25
MAX_FIRM_QUERIES = 6
MAX_ARTICLE_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_S = 20
MIN_INTERVAL_S = 1.0
LOOKBACK_DAYS = 400
EXTRACTOR_VERSION = "analyst_press v1"
CONSENSUS_FIRM = "Consenso (prensa)"

# Casas de análisis frecuentes (lista general, no por empresa) + sufijos típicos.
KNOWN_FIRMS = (
    "Clear Street", "Piper Sandler", "B. Riley", "B.Riley", "Roth Capital", "Roth MKM", "Roth", "Deutsche Bank",
    "Barclays", "Scotiabank", "Cantor Fitzgerald", "Jefferies", "Goldman Sachs", "Morgan Stanley", "UBS",
    "BofA Securities", "Bank of America", "Citigroup", "Citi", "JPMorgan", "J.P. Morgan", "Wells Fargo", "Wedbush",
    "Needham", "Benchmark", "Oppenheimer", "Raymond James", "RBC Capital", "TD Cowen", "Cowen", "Evercore ISI",
    "Bernstein", "Mizuho", "KeyBanc", "Truist", "Stifel", "William Blair", "Baird", "Canaccord Genuity",
    "Craig-Hallum", "Northland", "Rosenblatt", "HC Wainwright", "H.C. Wainwright", "Lake Street", "Ladenburg",
    "Macquarie", "BMO Capital", "National Bank Financial", "Desjardins", "CIBC", "Berenberg", "Redburn",
    "Kepler Cheuvreux", "Exane", "BNP Paribas", "Société Générale", "Santander", "Jefferies", "Morningstar",
    "Seaport", "Moffett", "Loop Capital", "Telsey", "Guggenheim", "Susquehanna", "Melius", "Bernstein",
    "Tigress", "Maxim", "Alliance Global", "Freedom Capital", "Zacks", "Argus", "CFRA",
)
_FIRM_SUFFIX = re.compile(
    r"\b((?:[A-Z][\w.&'-]+\s){0,3}(?:Securities|Capital Markets|Capital|Partners|Research|Advisors|& Co\.?))\b")
_CONSENSUS = re.compile(r"\b(consensus|analysts (?:expect|polled|estimate|forecast)|wall street expects|"
                        r"according to (?:lseg|factset|visible alpha|zacks|s&p global))\b", re.I)

_SCALE = {"million": Decimal(10) ** 6, "mn": Decimal(10) ** 6, "m": Decimal(10) ** 6, "mm": Decimal(10) ** 6,
          "billion": Decimal(10) ** 9, "bn": Decimal(10) ** 9, "b": Decimal(10) ** 9,
          "thousand": Decimal(10) ** 3, "k": Decimal(10) ** 3}
_AMOUNT = r"\$\s?(?P<num{n}>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<scale{n}>million|billion|thousand|mn|bn|mm|[mbk])\b"
_YEAR = r"(?:fy\s?|fiscal\s(?:year\s)?)?(?P<year{n}>20[2-4]\d)e?"
_PAIR_PATTERNS = (
    re.compile(_YEAR.format(n=1) + r"(?:\s(?:of|at|to|revenue of|revenues of|sales of))\s" + _AMOUNT.format(n=1), re.I),
    re.compile(_AMOUNT.format(n=1) + r"\s(?:in|for|by)\s(?:fiscal\s|fy\s?)?" + _YEAR.format(n=1), re.I),
    re.compile(r"\(" + _YEAR.format(n=1) + r"\)\s(?:of\s)?" + _AMOUNT.format(n=1), re.I),
)
_RELATIVE = re.compile(r"(?P<rel>this year|next year|current year|the year)\b[^.$]{0,160}?" + _AMOUNT.format(n=1)
                       + r"|" + _AMOUNT.format(n=2) + r"[^.$]{0,40}?\b(?P<rel2>this year|next year)\b", re.I)
_METRICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("adjusted_ebitda", re.compile(r"adjusted ebitda|ebitda \(adj", re.I)),
    ("ebitda", re.compile(r"\bebitda\b", re.I)),
    ("free_cash_flow", re.compile(r"free cash flow|\bfcf\b", re.I)),
    ("revenue", re.compile(r"\brevenues?\b|\bsales\b|\btop line\b", re.I)),
)
_PRICE_TARGET = re.compile(
    r"\$\s?(?P<a>\d{1,5}(?:\.\d{1,2})?)\s(?:share\s)?price target|price target (?:of|to|at|is)\s\$\s?(?P<b>\d{1,5}(?:\.\d{1,2})?)"
    r"|target (?:to|of)\s\$\s?(?P<c>\d{1,5}(?:\.\d{1,2})?)", re.I)
_ACTIONS = (("upgrade", re.compile(r"\bupgrad", re.I)), ("downgrade", re.compile(r"\bdowngrad", re.I)),
            ("initiate", re.compile(r"\binitiat", re.I)), ("reiterate", re.compile(r"\breiterat", re.I)),
            ("maintain", re.compile(r"\bmaintain", re.I)))
_SENTENCE = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[A-Z“\"(])")


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    published: date
    text: str


@dataclass
class Estimate:
    firm: str
    metric: str
    year: int
    amount: Decimal  # dólares (o por acción en price_target)
    quote: str
    url: str
    published: date
    paragraph: int


@dataclass
class ArticleReading:
    estimates: list[Estimate] = field(default_factory=list)
    targets: list[Estimate] = field(default_factory=list)
    actions: dict[str, str] = field(default_factory=dict)


def _norm_firm(raw: str) -> str:
    from app.services.analyst_history_service import normalize_firm

    name = re.sub(r"[’']s$", "", re.sub(r"[\s-]+", " ", raw.strip())).strip()
    name = re.sub(r"\b([A-Z])\.(?=[A-Z][a-z])", r"\1. ", name)  # «B.Riley» -> «B. Riley»
    name = {"B.Riley": "B. Riley", "Roth MKM": "Roth Capital", "Roth": "Roth Capital", "Citi": "Citigroup",
            "J.P. Morgan": "JPMorgan", "H.C. Wainwright": "HC Wainwright", "Bank of America": "BofA Securities",
            "Cowen": "TD Cowen"}.get(name, name)
    return normalize_firm(name) or name


def firms_in(text: str, extra: Sequence[str] = ()) -> list[str]:
    """Firmas de análisis citadas en un texto, en orden de aparición (sin repetir)."""
    hits: list[tuple[int, str]] = []
    for firm in (*extra, *KNOWN_FIRMS):
        pattern = re.escape(firm).replace(r"\ ", r"[\s-]")
        for m in re.finditer(r"(?<![\w.])" + pattern + r"(?![\w])", text):
            hits.append((m.start(), firm))
    for m in _FIRM_SUFFIX.finditer(text):
        hits.append((m.start(), m.group(1)))
    out: list[str] = []
    covered: list[tuple[int, int]] = []
    for start, firm in sorted(hits, key=lambda h: (h[0], -len(h[1]))):
        if any(s <= start < e for s, e in covered):
            continue
        covered.append((start, start + len(firm)))
        name = _norm_firm(firm)
        if name not in out:
            out.append(name)
    return out


def _amount(num: str, scale: str) -> Decimal:
    return Decimal(num.replace(",", "")) * _SCALE[scale.lower()]


def _metric_before(sentence: str, pos: int) -> str | None:
    best: tuple[int, str] | None = None
    for metric, rx in _METRICS:
        for m in rx.finditer(sentence):
            if m.start() <= pos and (best is None or m.start() > best[0]):
                best = (m.start(), metric)
    if best is not None:
        return best[1]
    # «… and 2027 of $557 million» sin palabra antes: la métrica de la frase.
    found = [metric for metric, rx in _METRICS if rx.search(sentence)]
    return found[0] if len(found) == 1 else None


_NOT_ENTITIES = {
    "Wall", "Street", "Buy", "Sell", "Hold", "Neutral", "Overweight", "Underweight", "Outperform", "Underperform",
    "Perform", "Sector", "Market", "Equal", "Weight", "Strong", "Total", "Revenue", "Revenues", "Adjusted",
    "EBITDA", "EPS", "CEO", "CFO", "Investing", "Nasdaq", "NASDAQ", "NYSE", "The", "This", "That", "These",
    "Analysts", "Analyst", "Meanwhile", "However", "While", "According", "Its", "Their", "His", "Her", "In",
    "On", "At", "By", "For", "From", "And", "But", "With", "After", "Before", "Shares", "Stock", "Q1", "Q2", "Q3",
    "Q4", "FY", "U.S.", "US", "USD", "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
}


def company_terms(company: Any) -> list[str]:
    """Cómo cita la prensa a la empresa: ticker y palabras propias del nombre."""
    name = re.sub(r",?\s+(inc|corp|corporation|co|ltd|plc|holdings?|limited|group|s\.a\.)\.?$", "",
                  getattr(company, "name", "") or "", flags=re.I)
    terms = [w for w in re.findall(r"[A-Za-z][\w&'-]+", name) if len(w) >= 3 and w.lower() not in {"the", "and"}]
    ticker = (getattr(company, "ticker", "") or "").split(".")[0]
    return [*terms, ticker] if ticker else terms


def _about_company(sentence: str, terms: Sequence[str], firms: Sequence[str]) -> bool:
    """La frase cita a la empresa, o no nombra a ninguna otra entidad (conservador)."""
    if not terms or any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", sentence) for t in terms):
        return True
    firm_words = {w for f in (*firms, *KNOWN_FIRMS) for w in re.findall(r"[\w.&'-]+", f)}
    words = re.findall(r"(?<![\w.])([A-Z][\w&'-]+)", sentence)
    others = [w for i, w in enumerate(words) if i > 0 and w not in _NOT_ENTITIES and w not in firm_words]
    return not others


def read_article(article: Article, *, extra_firms: Sequence[str] = (), company: Any = None) -> ArticleReading:
    reading = ArticleReading()
    terms = company_terms(company) if company is not None else []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", article.text) if p.strip()]
    article_firms = firms_in(article.text, extra_firms)
    for p_index, paragraph in enumerate(paragraphs):
        sentences = _SENTENCE.split(paragraph)
        for s_index, sentence in enumerate(sentences):
            own = firms_in(sentence, extra_firms)
            consensus = bool(_CONSENSUS.search(sentence)) and not own
            if own:
                firm = own[0] if len(own) == 1 else None
            elif consensus:
                firm = CONSENSUS_FIRM
            else:
                prev = firms_in(" ".join(sentences[max(0, s_index - 2):s_index]), extra_firms)
                firm = prev[-1] if prev else (article_firms[0] if len(article_firms) == 1 else None)
            if firm is None or not _about_company(sentence, terms, own):
                continue
            for action, rx in _ACTIONS:
                if rx.search(sentence) and firm != CONSENSUS_FIRM:
                    reading.actions.setdefault(firm, action)
                    break
            seen: set[tuple[str, int]] = set()
            for rx in _PAIR_PATTERNS:
                for m in rx.finditer(sentence):
                    metric = _metric_before(sentence, m.start())
                    year = int(m.group("year1"))
                    if metric is None or (metric, year) in seen:
                        continue
                    seen.add((metric, year))
                    reading.estimates.append(Estimate(firm, metric, year, _amount(m.group("num1"), m.group("scale1")),
                                                      sentence.strip()[:600], article.url, article.published, p_index))
            for m in _RELATIVE.finditer(sentence):
                rel = (m.group("rel") or m.group("rel2") or "").lower()
                num, scale = (m.group("num1"), m.group("scale1")) if m.group("num1") else (m.group("num2"), m.group("scale2"))
                year = article.published.year + (1 if rel == "next year" else 0)
                metric = _metric_before(sentence, m.end())
                if metric is None or (metric, year) in seen or rel == "the year":
                    continue
                seen.add((metric, year))
                reading.estimates.append(Estimate(firm, metric, year, _amount(num, scale), sentence.strip()[:600],
                                                  article.url, article.published, p_index))
            if firm != CONSENSUS_FIRM:
                for m in _PRICE_TARGET.finditer(sentence):
                    value = Decimal(m.group("a") or m.group("b") or m.group("c"))
                    reading.targets.append(Estimate(firm, "price_target", article.published.year, value,
                                                    sentence.strip()[:600], article.url, article.published, p_index))
                    break
    return reading


# -- descubrimiento y lectura ------------------------------------------------


def bing_items(rss: str) -> list[tuple[str, str, date | None]]:
    """(url del medio, título, fecha) de un RSS de Bing News."""
    out: list[tuple[str, str, date | None]] = []
    for item in re.findall(r"<item>(.*?)</item>", rss or "", re.S):
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if not link:
            continue
        raw = unescape(link.group(1).strip())
        target = parse_qs(urlparse(raw).query).get("url", [raw])[0]
        if urlparse(target).scheme != "https":
            continue
        day = None
        if pub:
            try:
                day = parsedate_to_datetime(pub.group(1).strip()).date()
            except (TypeError, ValueError):
                day = None
        out.append((target, unescape(title.group(1).strip()) if title else "", day))
    return out


def article_text(html: str) -> str:
    """Texto de un artículo en párrafos (``<p>``), sin menús ni scripts."""
    import lxml.html

    try:
        doc = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return ""
    for bad in doc.xpath("//script|//style|//nav|//footer|//header|//aside|//form"):
        bad.drop_tree()
    root = (doc.xpath("//article") or doc.xpath("//*[contains(@class,'entry-content')]") or [doc])[0]
    paragraphs = [re.sub(r"\s+", " ", p.text_content()).strip() for p in root.xpath(".//p|.//li")]
    return "\n\n".join(p for p in paragraphs if len(p) > 40)


def _published_from_html(html: str) -> date | None:
    m = re.search(r'(?:article:published_time|datePublished)["\']?\s*(?:content=|:)\s*["\'](\d{4}-\d{2}-\d{2})', html)
    return date.fromisoformat(m.group(1)) if m else None


class _Robots:
    def __init__(self) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def allowed(self, url: str, fetch) -> bool:
        host = urlparse(url).netloc
        if host not in self._cache:
            parser = urllib.robotparser.RobotFileParser()
            try:
                content, _, _ = await fetch(f"https://{host}/robots.txt")
                parser.parse(content.decode("utf-8", errors="replace").splitlines())
                self._cache[host] = parser
            except Exception:  # noqa: BLE001 - sin robots.txt legible: se permite (RFC 9309 §2.3.1.3)
                self._cache[host] = None
        parser = self._cache[host]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)


@dataclass
class CollectReport:
    articles_seen: int = 0
    articles_read: int = 0
    skipped_robots: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    readings: list[tuple[Article, ArticleReading]] = field(default_factory=list)


async def _default_fetch(url: str):
    from app.services.public_fetch import fetch_public_url_async

    return await fetch_public_url_async(url, timeout=FETCH_TIMEOUT_S, max_bytes=MAX_ARTICLE_BYTES,
                                        headers={"User-Agent": USER_AGENT})


async def collect(company: Any, *, known_urls: Iterable[tuple[str, str, date | None]] = (),
                  extra_firms: Sequence[str] = (), max_articles: int = MAX_ARTICLES, fetch=None,
                  today: date | None = None) -> CollectReport:
    """Busca y lee artículos con estimaciones de analistas de una empresa."""
    if fetch is None:
        fetch = _default_fetch
    today = today or datetime.now(UTC).date()
    name = re.sub(r",?\s+(inc|corp|corporation|co|ltd|plc|holdings?|limited|s\.a\.)\.?$", "", company.name or "",
                  flags=re.I).strip() or company.ticker
    report = CollectReport()
    # (url, título, fecha, viene de una búsqueda de analistas)
    candidates: list[tuple[str, str, date | None, bool]] = [(u, t, d, False) for u, t, d in known_urls]
    last = 0.0
    # Consultas generales y una por cada firma que ya cubre la empresa (las del
    # esqueleto de Yahoo en analyst_notes): sus notas salen en prensa con su nombre.
    queries = [q.format(name=name) for q in DISCOVERY_QUERIES]
    queries += [f'"{name}" "{firm}"' for firm in list(dict.fromkeys(extra_firms))[:MAX_FIRM_QUERIES]]
    for query in queries:
        wait = MIN_INTERVAL_S - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        url = BING_NEWS_RSS.format(query=quote_plus(query))
        try:
            content, _, _ = await fetch(url)
            candidates += [(u, t, d, True) for u, t, d in bing_items(content.decode("utf-8", errors="replace"))]
        except Exception as exc:  # noqa: BLE001
            report.failed.append(f"bing: {type(exc).__name__}")
        last = time.monotonic()
    seen: set[str] = set()
    robots = _Robots()
    cue = re.compile(r"analyst|price target|estimate|forecast|rating|upgrade|downgrade|reiterat|initiat|"
                     + "|".join(re.escape(f) for f in (*extra_firms, *KNOWN_FIRMS)), re.I)
    for url, title, day, from_search in candidates:
        key = url.split("#")[0]
        if key in seen or len(report.readings) + len(report.failed) >= max_articles:
            continue
        seen.add(key)
        if day is not None and day < today - timedelta(days=LOOKBACK_DAYS):
            continue
        if title and not from_search and not cue.search(title):
            continue
        report.articles_seen += 1
        if not await robots.allowed(url, fetch):
            report.skipped_robots.append(urlparse(url).netloc)
            continue
        wait = MIN_INTERVAL_S - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            content, _, final_url = await fetch(url)
        except Exception as exc:  # noqa: BLE001 - un medio caído no para la recogida
            report.failed.append(f"{urlparse(url).netloc}: {type(exc).__name__}")
            continue
        finally:
            last = time.monotonic()
        html = content.decode("utf-8", errors="replace")
        text = article_text(html)
        if not text:
            continue
        published = _published_from_html(html) or day or today
        article = Article(url=final_url or url, title=title, published=published, text=text)
        report.articles_read += 1
        reading = read_article(article, extra_firms=extra_firms, company=company)
        if reading.estimates or reading.targets:
            report.readings.append((article, reading))
    return report


# -- guardado ----------------------------------------------------------------


def _slug(firm: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", firm.lower()).strip("_") or "firma"


def estimate_key(metric: str, year: int, firm: str) -> str:
    return f"analyst.{metric}.fy{year}.{_slug(firm)}"


def store_readings(db: Any, company: Any, tenant_id: int, readings: Sequence[tuple[Article, ArticleReading]]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue
    from app.services.analyst_note_service import AnalystNoteError, AnalystNoteInput, analyst_note_service
    from app.services.declared_input_service import DeclaredInput, DeclaredInputService

    service = DeclaredInputService()
    stored: list[dict[str, Any]] = []
    skipped: list[str] = []
    for article, reading in sorted(readings, key=lambda r: r[0].published):
        by_firm: dict[str, list[Estimate]] = {}
        for est in (*reading.estimates, *reading.targets):
            by_firm.setdefault(est.firm, []).append(est)
        for firm, items in by_firm.items():
            estimates: dict[str, dict[str, float]] = {}
            for est in items:
                if est.metric == "price_target":
                    continue
                key = estimate_key(est.metric, est.year, firm)
                current = db.scalars(select(DeclaredInputValue).where(
                    DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
                    DeclaredInputValue.input_key == key, DeclaredInputValue.superseded_at.is_(None))).first()
                if current is not None and current.as_of and current.as_of > est.published:
                    skipped.append(f"{key}: hay una cifra más reciente ({current.as_of})")
                    continue
                item = DeclaredInput(
                    input_key=key, base=est.amount, unit="USD", method="analyst", analyst_firm=firm,
                    source_url=est.url, source_quote=est.quote, as_of=est.published,
                    metadata={"kind": "analyst_press", "metric": est.metric, "year": est.year, "firm": firm,
                              "paragraph": est.paragraph, "extractor": EXTRACTOR_VERSION,
                              "consensus": firm == CONSENSUS_FIRM},
                )
                problems = service.validate(item)
                if problems:
                    skipped.append(f"{key}: {'; '.join(problems)}")
                    continue
                result = service.upsert(db, company=company, tenant_id=tenant_id, item=item)
                stored.append({"key": key, "firm": firm, "base": str(est.amount), "date": est.published.isoformat(),
                               "url": est.url, "action": result.reason})
                estimates.setdefault(est.metric, {})[str(est.year)] = float(est.amount / Decimal(10) ** 6)
            if firm == CONSENSUS_FIRM:
                continue
            target = next((e for e in items if e.metric == "price_target"), None)
            quote = (target or items[0]).quote
            try:
                analyst_note_service.upsert(db, tenant_id, AnalystNoteInput(
                    ticker=company.ticker, firm=firm, note_date=article.published,
                    action=reading.actions.get(firm, "other"), source_type="news", company_id=company.id,
                    pt_new=target.amount if target else None, currency="USD" if target else None,
                    quote=quote, source_url=article.url, estimates={k: v for k, v in estimates.items()},
                    extras={"kind": "analyst_press", "extractor": EXTRACTOR_VERSION, "estimates_unit": "millones",
                            "collected_on": datetime.now(UTC).date().isoformat()},
                ))
            except AnalystNoteError as exc:
                skipped.append(f"nota {firm}: {exc}")
    db.flush()
    return {"stored": stored, "skipped": skipped}


def refresh_press_estimates(db: Any, company: Any, tenant_id: int, *, max_articles: int = MAX_ARTICLES,
                            fetch=None, today: date | None = None, timeout: float = 240.0) -> dict[str, Any]:
    """Recoge y guarda las estimaciones de prensa de una empresa. No hace commit."""
    from sqlalchemy import select

    from app.models import AnalystNote
    from app.models.entities import NewsEvent
    from app.services.async_bridge import run_from_any_context

    today = today or datetime.now(UTC).date()
    since = datetime.combine(today - timedelta(days=LOOKBACK_DAYS), datetime.min.time(), tzinfo=UTC)
    # Las firmas que ya cubren la empresa (esqueleto Yahoo y notas previas): consultas y nombres.
    firms = [f for f in db.scalars(select(AnalystNote.firm).where(
        AnalystNote.tenant_id == tenant_id, AnalystNote.ticker == company.ticker)
        .order_by(AnalystNote.note_date.desc()).limit(200)).all() if f]
    known: list[tuple[str, str, date | None]] = []
    for row in db.scalars(select(NewsEvent).where(
            NewsEvent.tenant_id == tenant_id, NewsEvent.company_id == company.id, NewsEvent.date >= since)
            .order_by(NewsEvent.date.desc()).limit(300)).all():
        url = (row.url or "").strip()
        host = urlparse(url).netloc
        # Los enlaces de Google News no llevan la URL del medio (y su robots.txt los prohíbe).
        if url.startswith("https://") and host and not host.endswith("news.google.com"):
            known.append((url, f"{row.title} {row.summary or ''}"[:500], row.date.date() if row.date else None))
    report = run_from_any_context(
        collect(company, known_urls=known, extra_firms=list(dict.fromkeys(firms)), max_articles=max_articles,
                fetch=fetch, today=today),
        timeout=timeout,
    )
    saved = store_readings(db, company, tenant_id, report.readings)
    return {"articles_seen": report.articles_seen, "articles_read": report.articles_read,
            "with_estimates": len(report.readings), "skipped_robots": sorted(set(report.skipped_robots)),
            "failed": report.failed[:20], **saved}


STALE_DAYS = 3


def press_estimates_stale(db: Any, company: Any, tenant_id: int, *, today: date | None = None) -> bool:
    """Sin una recogida de prensa en ``STALE_DAYS`` días (marca en las notas de analista)."""
    from sqlalchemy import select

    from app.models import AnalystNote

    today = today or datetime.now(UTC).date()
    rows = db.scalars(select(AnalystNote.extras).where(
        AnalystNote.tenant_id == tenant_id, AnalystNote.ticker == company.ticker,
        AnalystNote.note_date >= today - timedelta(days=60))).all()
    marks = [r.get("collected_on") for r in rows if isinstance(r, dict) and r.get("kind") == "analyst_press"]
    latest = max((date.fromisoformat(m) for m in marks if m), default=None)
    return latest is None or latest < today - timedelta(days=STALE_DAYS)
