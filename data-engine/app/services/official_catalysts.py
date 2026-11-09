"""Catalizadores oficiales: contratos, empresas conjuntas (JV) y subvenciones publicados por la empresa o su contraparte.

Regla pre-registrada ``catalizadores-oficiales-v1`` (sin modelo; nada por emisor):

- **Fuente oficial** (:func:`official_kind`): un documento de la SEC de la propia empresa (8-K/6-K y sus EX-99), o una
  nota de prensa en un servicio de notas de prensa, en la web de inversores de la empresa (host de ``ir_url``) o en una
  web corporativa (ruta de sala de prensa en un host que no es de un medio y cuya editora se nombra en la página). Un
  artículo de un medio nunca es fuente oficial.
- **Catalizador** (:func:`extract`): frase de un documento que nombra a la empresa y contiene un término de contrato,
  empresa conjunta o subvención (inglés, español y japonés). Tipo por prioridad: jv → contrato → subvención.
- Cada fila lleva fecha, URL, editora, tipo, **resumen literal** (las frases tal cual, sin traducir; recortadas con «…»),
  los importes citados tal cual y el **importe para la empresa**: solo si en la MISMA frase la empresa, por su propio
  nombre (no como parte de otro nombre propio: «Rakuten AST» no es AST), es la receptora o la parte con un patrón
  explícito; si no, ``N/D (no publicado)``.
- Solo un importe atribuible entra en los escenarios (:mod:`app.services.pre_revenue_valuation`, ancla de cartera
  contratada). Sin importe atribuible, la valoración no cambia.

La lectura (:func:`catalysts_for`) es pura sobre documentos ya guardados; la red solo está en :func:`collect`.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

RULES_VERSION = "catalizadores-oficiales-v1"
WINDOW_DAYS = 365
MAX_ROWS = 12
MAX_AMOUNTS = 6
MAX_SUMMARY = 360  # por frase
ND_AMOUNT = "N/D (no publicado)"

#: Servicios de distribución de notas de prensa: el texto es el del emisor.
PRESS_WIRES = ("businesswire.com", "prnewswire.com", "globenewswire.com", "accesswire.com", "accessnewswire.com",
               "newsfilecorp.com", "webwire.com", "feeds.issuerdirect.com", "newswire.ca")
#: Medios y agregadores (nunca oficiales aunque la ruta lo parezca).
MEDIA_HOSTS = ("yahoo.", "msn.com", "nikkei.com", "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "ft.com",
               "marketwatch.com", "barrons.com", "fool.com", "seekingalpha.com", "benzinga.com", "investing.com",
               "247wallst.com", "zacks.com", "tipranks.com", "lightreading.com", "satnews.com", "spacenews.com",
               "theglobeandmail.com", "forbes.com", "businessinsider.com", "impress.co.jp", "itmedia.co.jp",
               "livedoor.com", "note.com", "kanaloco.jp", "aol.com", "financialcontent.com", "google.", "bing.com")
_NEWSROOM_PATH = re.compile(r"/(?:news/press|press[-_]?releases?|pressreleases?|press|newsroom|news[-_]releases?|"
                            r"media/(?:news|press)|ir/news|investors?/news)(?:/|$|\.)", re.I)
_SEC_FORMS = ("8-K", "6-K")

# Términos de catalizador por tipo (prioridad: jv → contrato → subvención).
TERMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("jv", re.compile(r"\bjoint[- ]venture\b|\bJV\b|\bempresa conjunta\b|合弁|新会社|共同出資", re.I)),
    ("contrato", re.compile(r"\b(?:definitive |commercial |master |supply |purchase |services? )?agreements?\b|"
                            r"\bcontracts?\b|\bpurchase orders?\b|\bcontratos?\b|\bacuerdos?\b|契約|合意", re.I)),
    ("subvencion", re.compile(r"\bgrants?\b|\bawards?\b|\bawarded\b|\bsubsid(?:y|ies)\b|\bfunding\b|"
                              r"\bsubvenci[oó]n(?:es)?\b|\badjudicaci[oó]n\b|交付|補助|助成|採択", re.I)),
)
TYPE_LABELS = {"jv": "empresa conjunta (JV)", "contrato": "contrato o acuerdo", "subvencion": "subvención o adjudicación"}

# Importes citados (tal cual): «$1.2 billion», «US$500 million», «€30m», «1,480億円», «最大1,480億円», «JPY 148 billion».
_AMOUNT = re.compile(
    r"(?:最大|約|up to |approximately |about |hasta )?"
    r"(?:(?:US\$|C\$|A\$|\$|€|£|¥|JPY|USD|EUR|GBP)\s?\d[\d,.]*(?:\s?(?:billion|million|thousand|bn|mn|m|b|mil millones|millones))?"
    r"|\d[\d,.]*\s?(?:兆|億|万)\s?円|\d[\d,.]*\s?(?:billion|million|bn|mil millones|millones)\s?(?:yen|euros?|dollars|dólares|USD|EUR|JPY)"
    r"|\d[\d,.]*\s?円)", re.I)
_SPLIT = re.compile(r"(?<=[。！？])|(?<=[.!?;])\s+(?=[A-Z“\"(¿¡•\u3040-\u30ff\u4e00-\u9fff])")
_DATE_JA = re.compile(r"(20\d\d)年\s?(\d{1,2})月\s?(\d{1,2})日")
_DATE_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_DATE_EN = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
                      r"\s+(\d{1,2}),\s+(20\d\d)\b")
_MONTHS = {m: i + 1 for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August",
                                           "September", "October", "November", "December"))}
_URL_DATE = re.compile(r"/(20\d\d)/(\d\d)(\d\d)(?:[_-]|\.|/)")
_RECEIVE_EN = re.compile(r"^\s*(?:,[^,]{0,80},\s*)?(?:has been |was |is |will be )?(?:awarded|will receive|received|receives|"
                         r"secured|has secured|won|signed|has signed|entered into|has entered into|will be paid)\b", re.I)
_TO_COMPANY_EN = re.compile(r"\b(?:to|for|with)\s+$", re.I)
_STAKE = re.compile(r"\d{1,3}(?:[.,]\d+)?\s?[%％]")
_RECEIVE_JA = re.compile(r"^\s*(?:は|が)")
_RECEIVE_JA_TAIL = re.compile(r"受注|を受け|契約")


@dataclass(frozen=True)
class Catalyst:
    date: str | None
    kind: str
    url: str
    publisher: str
    source_kind: str
    summary: str
    amounts: tuple[str, ...] = ()
    amount_for_company: str | None = None
    amount_for_company_value: float | None = None
    amount_currency: str | None = None
    amount_reason: str = ND_AMOUNT
    document_id: int | None = None
    title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["amounts"] = list(self.amounts)
        out["kind_label"] = TYPE_LABELS.get(self.kind, self.kind)
        return out


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def registrable_label(host: str) -> str | None:
    """«corp.rakuten.co.jp» → «rakuten»; «investors.ast-science.com» → «ast-science». Puro."""
    parts = [p for p in host.lower().split(".") if p]
    if len(parts) < 2:
        return None
    second_level = {"co", "com", "ne", "or", "ac", "go", "org", "net", "gov", "edu"}
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in second_level:
        return parts[-3]
    return parts[-2]


def official_kind(url: str, *, text: str = "", ir_hosts: Iterable[str] = ()) -> str | None:
    """«sec» | «wire» | «ir» | «corporativa» | None (medio o desconocido). Puro."""
    host = _host(url)
    if not host or not url.lower().startswith("https://"):
        return None
    if host in ("www.sec.gov", "sec.gov"):
        return "sec"
    if any(host == w or host.endswith("." + w) for w in PRESS_WIRES):
        return "wire"
    if any(m in host for m in MEDIA_HOSTS):
        return None
    irs = {h.lower() for h in ir_hosts if h}
    if host in irs or any(registrable_label(host) == registrable_label(h) for h in irs):
        return "ir"
    path = urlsplit(url).path
    label = registrable_label(host)
    if _NEWSROOM_PATH.search(path) and label and len(label) >= 3 and re.search(
            re.escape(label).replace(r"\-", "[- ]?"), text or "", re.I):
        return "corporativa"
    return None


def company_terms(company: Any) -> list[str]:
    """Nombre sin sufijo societario, cada palabra propia de ≥3 letras y el ticker (sin bolsa)."""
    name = re.sub(r",?\s+(inc|corp|corporation|co|ltd|plc|holdings?|limited|group|s\.a\.|n\.v\.|ag|se)\.?$", "",
                  str(getattr(company, "name", "") or "").strip(), flags=re.I).strip(" ,")
    words = [w for w in re.findall(r"[A-Za-z][\w&'-]+", name) if len(w) >= 3 and w.lower() not in {"the", "and"}]
    ticker = str(getattr(company, "ticker", "") or "").split(".")[0]
    out = [name] if name else []
    out += [w for w in words if w not in out]
    if ticker and ticker not in out:
        out.append(ticker)
    return out


def _standalone(text: str, start: int, end: int) -> bool:
    """La mención no es parte de otro nombre propio («Rakuten AST», «ASTX», «AST株式会社»)."""
    before = text[max(0, start - 12):start]
    after = text[end:end + 4]
    if re.search(r"[A-Za-z0-9][\w&.'-]*\s?$", before) and not re.search(r"(?:\b(?:to|with|for|and|by|of|that|"
                                                                         r"y|con|para|a)\s|[,(]\s?)$", before, re.I):
        return False
    if re.match(r"[A-Za-z0-9]|株式会社|社\b", after):
        return False
    return True


def _mentions(text: str, terms: Sequence[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for term in terms:
        if not term:
            continue
        pat = re.escape(term) if not term.isascii() else r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        spans += [(m.start(), m.end()) for m in re.finditer(pat, text)]
    return sorted(set(spans))


def sentences(text: str) -> list[str]:
    flat = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    out: list[str] = []
    for block in re.split(r"\n+", flat):
        for part in _SPLIT.split(block):
            p = part.strip()
            if 12 <= len(p) <= 1500:
                out.append(p)
    return out


def _currency(amount: str) -> str | None:
    a = amount.upper()
    if "円" in amount or "¥" in amount or "JPY" in a or "YEN" in a:
        return "JPY"
    if "€" in amount or "EUR" in a:
        return "EUR"
    if "£" in amount or "GBP" in a:
        return "GBP"
    if "C$" in amount:
        return "CAD"
    if "A$" in amount:
        return "AUD"
    if "$" in amount or "USD" in a or "DOLLAR" in a or "DÓLAR" in a:
        return "USD"
    return None


def amount_value(amount: str) -> float | None:
    """Importe en unidades de su divisa («1,480億円» → 1,48e11; «$1.2 billion» → 1,2e9). Puro."""
    m = re.search(r"\d[\d,.]*", amount)
    if not m:
        return None
    raw = m.group(0).rstrip(".,")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        raw = raw.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", raw):
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".") if raw.count(",") == 1 and "." not in raw else raw.replace(",", "")
    try:
        v = float(raw)
    except ValueError:
        return None
    low = amount.lower()
    for word, mult in (("兆", 1e12), ("億", 1e8), ("万", 1e4), ("mil millones", 1e9), ("billion", 1e9), ("bn", 1e9),
                       ("millones", 1e6), ("million", 1e6), ("mn", 1e6), ("thousand", 1e3)):
        if word in low:
            return v * mult
    if re.search(r"\d\s?m\b", low):
        return v * 1e6
    if re.search(r"\d\s?b\b", low):
        return v * 1e9
    return v


def attributable(sentence: str, amount_span: tuple[int, int], terms: Sequence[str]) -> bool:
    """La empresa, por su propio nombre, es la receptora o la parte del importe en la misma frase. Puro."""
    for start, end in _mentions(sentence, terms):
        if not _standalone(sentence, start, end):
            continue
        tail = sentence[end:]
        if end <= amount_span[0] and _RECEIVE_EN.match(tail):
            return True
        if end <= amount_span[0] and _RECEIVE_JA.match(tail) and _RECEIVE_JA_TAIL.search(sentence[amount_span[1]:]):
            return True
        if start >= amount_span[1] and _TO_COMPANY_EN.search(sentence[amount_span[1]:start][-12:]):
            return True
    return False


def kind_of(sentence: str) -> str | None:
    for kind, pat in TERMS:
        if pat.search(sentence):
            return kind
    return None


def _clip(text: str) -> str:
    return text if len(text) <= MAX_SUMMARY else text[:MAX_SUMMARY].rstrip() + "…"


def extract(text: str, *, terms: Sequence[str], published: date | None, url: str, publisher: str,
            source_kind: str, document_id: int | None = None, title: str | None = None) -> list[Catalyst]:
    """Catalizadores de un documento oficial (uno por tipo; frases literales). Puro."""
    if not text or not _mentions(text, terms):
        return []
    by_kind: dict[str, list[str]] = {}
    amounts: dict[str, list[str]] = {}
    attributed: dict[str, tuple[str, float | None, str | None]] = {}
    for s in sentences(text):
        kind = kind_of(s)
        if kind is None:
            continue
        own = source_kind in ("sec", "ir")
        if not own and not _mentions(s, terms):
            continue
        by_kind.setdefault(kind, []).append(s)
        for m in _AMOUNT.finditer(s):
            lit = m.group(0).strip()
            if not re.search(r"\d", lit):
                continue
            amounts.setdefault(kind, []).append(lit)
            if kind not in attributed and attributable(s, (m.start(), m.end()), terms):
                attributed[kind] = (lit, amount_value(lit), _currency(lit))
    out: list[Catalyst] = []
    for kind, sents in by_kind.items():
        lit = attributed.get(kind)
        # La primera frase y, si existe, la que da el reparto o la participación (51 %/49 %), tal cual.
        stake = next((x for x in sents[1:] if _STAKE.search(x)), None)
        picked = [sents[0], stake or (sents[1] if len(sents) > 1 else None)]
        out.append(Catalyst(
            date=published.isoformat() if published else None, kind=kind, url=url, publisher=publisher,
            source_kind=source_kind, summary=" … ".join(_clip(x) for x in picked if x), amounts=tuple(dict.fromkeys(amounts.get(kind, [])))[:MAX_AMOUNTS],
            amount_for_company=lit[0] if lit else None, amount_for_company_value=lit[1] if lit else None,
            amount_currency=lit[2] if lit else None,
            amount_reason="atribuido a la empresa en la misma frase" if lit else ND_AMOUNT,
            document_id=document_id, title=title))
    return out


# --------------------------------------------------------------------------------------------- lectura (sin red)

def _published(doc: Any) -> date | None:
    v = getattr(doc, "published_at", None)
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _ir_hosts(company: Any) -> list[str]:
    host = _host(str(getattr(company, "ir_url", "") or ""))
    return [host] if host else []


def catalysts_for(db: Any, company: Any, *, today: date | None = None) -> list[dict[str, Any]]:
    """Catalizadores de los documentos oficiales ya guardados de la empresa (más reciente primero). Nunca lanza."""
    from sqlalchemy import select

    from app.models.entities import Document, DocumentChunk

    today = today or date.today()
    since = datetime.combine(today - timedelta(days=WINDOW_DAYS), datetime.min.time(), tzinfo=UTC)
    try:
        docs = db.scalars(
            select(Document).where(Document.company_id == company.id, Document.retention_tombstoned_at.is_(None),
                                   Document.published_at.is_not(None), Document.published_at >= since,
                                   Document.source_url.is_not(None))
            .order_by(Document.published_at.desc(), Document.id.desc()).limit(200)).all()
    except Exception as exc:  # noqa: BLE001 - sin documentos, sin catalizadores
        logger.info("catalizadores %s: %s", getattr(company, "ticker", "?"), type(exc).__name__)
        db.rollback()
        return []
    terms, irs = company_terms(company), _ir_hosts(company)
    rows: list[Catalyst] = []
    seen: set[str] = set()
    for doc in docs:
        url = str(doc.source_url or "")
        meta = doc.metadata_ or {}
        chunks = db.scalars(select(DocumentChunk.text).where(DocumentChunk.document_id == doc.id)
                            .order_by(DocumentChunk.chunk_index)).all()
        text = " ".join(c or "" for c in chunks)
        if not text:
            continue
        kind = official_kind(url, text=text, ir_hosts=irs)
        if kind == "sec" and not (str(meta.get("form") or "") in _SEC_FORMS
                                  or re.search(r"(?<![\w-])[86]-K\b", str(doc.title or ""))):
            continue  # 10-K/10-Q/20-F: informes periódicos, no anuncios de catalizadores
        if kind is None:
            continue
        for cat in extract(text, terms=terms, published=_published(doc), url=url, publisher=_host(url),
                           source_kind=kind, document_id=doc.id, title=doc.title):
            key = hashlib.sha1(f"{cat.url}|{cat.kind}|{cat.summary[:120]}".encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                rows.append(cat)
    rows.sort(key=lambda c: (c.date or "", c.document_id or 0), reverse=True)
    return [c.as_dict() for c in rows[:MAX_ROWS]]


# --------------------------------------------------------------------------------------------- recogida (red)

def page_text(html: bytes) -> tuple[str, str | None, str]:
    """(texto en párrafos, titular h1, texto plano completo) de una nota de prensa, sin menús ni scripts."""
    import lxml.html

    try:
        doc = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return "", None, ""
    for bad in doc.xpath("//script|//style|//nav|//footer|//header|//aside|//form|//noscript"):
        bad.drop_tree()
    h1 = next((re.sub(r"\s+", " ", h.text_content()).strip() for h in doc.xpath("//h1")), None)
    paragraphs = [re.sub(r"\s+", " ", p.text_content()).strip() for p in doc.xpath("//h1|//p|//li")]
    body = doc.xpath("//body")
    flat = re.sub(r"\s+", " ", (body[0] if body else doc).text_content())
    return "\n".join(p for p in paragraphs if p), h1, flat


def page_date(flat: str, h1: str | None, url: str, html: bytes = b"") -> date | None:
    """Fecha de la nota: la fecha más cercana al titular (h1) en la página, hasta 200 caracteres antes o 300 después
    (las salas de prensa la ponen encima o debajo del titular); si no, los metadatos de publicación; si no, la fecha de
    la ruta (``/2026/1109_01``)."""
    start = flat.find(h1) if h1 else -1
    hits: list[tuple[int, date]] = []
    if start >= 0:
        end = start + len(h1 or "")
        lo = max(0, start - 200)
        window = flat[lo:end + 300]
        found = [(m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3)))
                 for pat in (_DATE_JA, _DATE_ISO) for m in pat.finditer(window)]
        found += [(m.start(), int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))) for m in _DATE_EN.finditer(window)]
        for pos, y, mo, d in found:
            at = lo + pos
            if start <= at < end:
                continue  # una fecha dentro del propio titular no es la de publicación
            try:
                hits.append((start - at if at < start else at - end, date(y, mo, d)))
            except ValueError:
                continue
    if hits:
        return sorted(hits, key=lambda h: h[0])[0][1]
    meta = re.search(rb'(?:article:published_time|datePublished)["\']?\s*(?:content=|:)\s*["\'](20\d\d-\d\d-\d\d)', html)
    if meta:
        return date.fromisoformat(meta.group(1).decode())
    mu = _URL_DATE.search(urlsplit(url).path)
    if mu:
        try:
            return date(int(mu.group(1)), int(mu.group(2)), int(mu.group(3)))
        except ValueError:
            return None
    return None


DISCOVERY_QUERIES = ('"{name}" joint venture', '"{name}" agreement', '"{name}" contract', '"{name}" grant OR award')
BING_NEWS_RSS = "https://www.bing.com/news/search?q={query}&format=rss"


def discover(company: Any, fetch: Callable[[str], bytes]) -> list[tuple[str, str, date | None]]:
    """Candidatos de Bing News RSS (gratis) por el nombre de la empresa y términos de catalizador."""
    from app.services.analyst_press_estimates import bing_items

    name = company_terms(company)[0] if company_terms(company) else str(getattr(company, "ticker", ""))
    out: list[tuple[str, str, date | None]] = []
    for q in DISCOVERY_QUERIES:
        try:
            rss = fetch(BING_NEWS_RSS.format(query=quote(q.format(name=name))))
            out += bing_items(rss.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001 - una consulta caída no para las demás
            logger.info("catalizadores bing: %s", type(exc).__name__)
    return out


def _default_fetch(url: str) -> bytes:
    from app.services.public_fetch import fetch_public_url

    content, _ctype, _final = fetch_public_url(url)
    return content


def _robots_allows(url: str, fetch: Callable[[str], bytes]) -> bool:
    from urllib.robotparser import RobotFileParser

    host = _host(url)
    try:
        raw = fetch(f"https://{host}/robots.txt").decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - sin robots.txt legible se permite (RFC 9309 §2.3.1.3)
        return True
    rp = RobotFileParser()
    rp.parse(raw.splitlines())
    return rp.can_fetch("GerarAI", url)


def collect(db: Any, company: Any, tenant_id: int, *, urls: Iterable[str] = (), fetch: Callable[[str], bytes] | None = None,
            discover_news: bool = True, max_pages: int = 12) -> dict[str, Any]:
    """Busca notas de prensa oficiales (propias o de la contraparte) y las guarda como documentos con su texto.

    Solo entra lo que pasa :func:`official_kind`. No hace commit."""
    from sqlalchemy import select

    from app.models.entities import Document, DocumentChunk, NewsEvent

    fetch = fetch or _default_fetch
    candidates: list[tuple[str, date | None]] = [(u, None) for u in urls]
    if discover_news:
        candidates += [(u, d) for u, _t, d in discover(company, fetch)]
        try:
            candidates += [(str(n.url), n.date.date() if n.date else None) for n in db.scalars(
                select(NewsEvent).where(NewsEvent.company_id == company.id, NewsEvent.url.is_not(None))
                .order_by(NewsEvent.date.desc()).limit(200)).all()]
        except Exception:  # noqa: BLE001
            db.rollback()
    irs, terms = _ir_hosts(company), company_terms(company)
    have = {str(u) for u in db.scalars(select(Document.source_url).where(Document.company_id == company.id)).all()}
    report: dict[str, Any] = {"rules": RULES_VERSION, "candidates": 0, "stored": [], "skipped": {}}
    seen: set[str] = set()
    for url, hint in candidates:
        if url in seen or url in have:
            continue
        seen.add(url)
        # Filtro previo sin texto: un medio o un host desconocido sin ruta de sala de prensa ni se descarga.
        host = _host(url)
        if official_kind(url, text=registrable_label(host) or "", ir_hosts=irs) is None:
            continue
        report["candidates"] += 1
        if len(report["stored"]) >= max_pages:
            break
        if not _robots_allows(url, fetch):
            report["skipped"][url] = "robots.txt"
            continue
        try:
            html = fetch(url)
        except Exception as exc:  # noqa: BLE001
            report["skipped"][url] = type(exc).__name__
            continue
        text, h1, flat = page_text(html)
        kind = official_kind(url, text=flat, ir_hosts=irs)
        if kind is None or not _mentions(text, terms):
            report["skipped"][url] = "no oficial o no nombra a la empresa"
            continue
        published = page_date(flat, h1, url, html) or hint
        doc = Document(company_id=company.id, tenant_id=tenant_id, title=(h1 or url)[:400], source_type="press_release",
                       source_url=url, checksum=hashlib.sha256(html).hexdigest(),
                       published_at=datetime.combine(published, datetime.min.time(), tzinfo=UTC) if published else None,
                       metadata_={"official": kind, "publisher": host, "collector": RULES_VERSION,
                                  "published_from": "página" if published and published != hint else "buscador"})
        db.add(doc)
        db.flush()
        for i in range(0, len(text), 1500):
            db.add(DocumentChunk(document_id=doc.id, tenant_id=tenant_id, chunk_index=i // 1500, text=text[i:i + 1500],
                                 token_count=0, metadata_={"collector": RULES_VERSION}))
        report["stored"].append({"url": url, "kind": kind, "date": published.isoformat() if published else None})
    return report


__all__ = ["Catalyst", "RULES_VERSION", "attributable", "catalysts_for", "collect", "company_terms", "extract",
           "official_kind", "page_date", "page_text", "registrable_label"]
