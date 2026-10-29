"""Carril de noticias por ticker independiente de GDELT.

GDELT (tier gratuito, ~1 req / 5 s por IP) devuelve 429 en la mayoria de las
consultas y dejaba a empresas como ASTS o SPCX sin titulares durante dias. Este
carril usa dos fuentes gratuitas sin clave, por ticker, con pacing propio:

- Yahoo Finance RSS por simbolo (solo cotizadas en EEUU: el simbolo de otras
  bolsas necesita sufijo de mercado que aqui no se conoce, asi que no se
  adivina).
- Google News RSS por nombre de empresa y ticker. Solo se guardan titulares
  cuya pista de texto cita a la empresa (misma regla de evidencia que
  NewsService), porque la busqueda es amplia.

Fuente y fecha son las reales del feed; el dedupe por URL lo hace
NewsService. Nada se inventa: sin fecha, el item conserva published_at None.
"""

from __future__ import annotations

import dataclasses
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus

from app.core.errors import redact_secrets
from app.services.connectors.base import ConnectorItem, ConnectorResult

US_EXCHANGE_RE = re.compile(r"NASDAQ|NYSE|AMEX|ARCA|BATS|CBOE", re.IGNORECASE)
# Empresas seguidas de cerca: siempre entran en el carril rapido.
PRIORITY_TICKERS = frozenset({"ASTS", "SPCX"})
# Alias verificados a mano por empresa: las noticias reales citan la marca y no
# el ticker ("SpaceX compra espectro..."). Solo marcas propias de esa empresa;
# nada de terminos de sector ("satelite", "espacio") ni de competidores.
VERIFIED_ALIASES: dict[str, tuple[str, ...]] = {
    "SPCX": ("SpaceX", "Space Exploration Technologies", "Starlink"),
    "ASTS": ("AST SpaceMobile", "SpaceMobile", "BlueBird"),
    # Marcas propias que la prensa cita en vez del nombre legal (Alphabet, Meta
    # Platforms, Amazon.com...). Solo marcas oficiales de cada grupo.
    "GOOGL": ("Google", "YouTube", "Waymo", "DeepMind"),
    "GOOG": ("Google", "YouTube", "Waymo", "DeepMind"),
    "META": ("Facebook", "Instagram", "WhatsApp"),
    "AMZN": ("AWS", "Amazon Web Services", "Whole Foods"),
    "MSFT": ("Azure", "LinkedIn", "GitHub", "Xbox"),
    "AAPL": ("iPhone", "iPad", "App Store"),
    "ADBE": ("Photoshop", "Acrobat"),
}
# Siglas que coinciden con una palabra o lugar corriente (AENA en titulares de
# Rio de Janeiro, Adani o aguas fecales de Ibiza): el ticker o «Aena» sueltos no
# vinculan; hace falta el nombre completo, una forma verificada o el cashtag.
STRICT_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    # CPT = Curricular Practical Training (visado de estudiantes) en titulares
    # de educación; el REIT es Camden Property Trust. «Camden» a secas no vale:
    # es un lugar corriente.
    "CPT": (
        r"Camden\s+Property(?:\s+Trust)?",
        r"\$CPT\b",
        r"\bNYSE\s*:\s*CPT\b",
    ),
    "AENA": (
        r"Aena\s+S\.?\s?M\.?\s?E\.?",
        r"Aena\s+Aeropuertos",
        r"Aeropuertos\s+Espa(?:ñ|n)oles\s+y\s+Navegaci(?:ó|o)n\s+A(?:é|e)rea",
        r"aeropuertos\s+de\s+Aena",
        r"\$AENA\b",
        r"\b(?:BME|BME\s*Growth|MCE)\s*:\s*AENA\b",
    ),
}


# «Aena» suelto vale si el texto trae ademas una palabra del sector o de su
# entorno en Espana; sin ella, es una colision de palabra.
_STRICT_CONTEXT = {
    # «shares»/«stocks» sueltos NO valen como contexto: «She shares her CPT
    # experience for F-1 students» (visado) vinculaba con Camden por «shares»
    # (objeción del auditor, 19-oct-2026). Contexto del sector REIT o
    # financiero, no verbos corrientes.
    "CPT": re.compile(
        r"\breit\b|residencial|apartamentos?|apartments?|multifamily|vivienda|alquiler|"
        r"beneficio|resultados|dividendo|ingresos|\bNYSE\b|\bearnings\b",
        flags=re.IGNORECASE,
    ),
    "AENA": re.compile(
        r"aeropuert|aeroportuari|pasajeros|tarifas|barajas|el\s+prat|enaire|ferrovial|"
        r"\bBME\b|\bIBEX\b|\bCNMC\b|aerol(?:í|i)neas|\bvuelos\b|"
        r"beneficio|resultados|dividendo|facturaci(?:ó|o)n|ingresos",
        flags=re.IGNORECASE,
    ),
}


def fails_strict_name(company, text: str) -> bool:
    """True si la sigla es una palabra corriente y el texto no vincula a la empresa.

    Vale: una forma completa verificada, o «Aena» suelto (fuera del ticker pegado
    delante) junto a una palabra de contexto del sector.
    """
    ticker = (getattr(company, "ticker", None) or str(company)).upper()
    patterns = STRICT_NAME_PATTERNS.get(ticker)
    if not patterns:
        return False
    text = text or ""
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
        return False
    # La etiqueta de ingesta es el ticker en mayusculas; «Aena sube...» natural no es etiqueta.
    first = re.sub(rf"^\s*{re.escape(ticker)}\s+", "", text.strip(), count=1)
    bare_name = re.search(rf"(?<![\w$]){re.escape(ticker)}(?![\w])", first, flags=re.IGNORECASE)
    context = _STRICT_CONTEXT.get(ticker)
    return not (bare_name and context and context.search(first))


# Competidores que el feed de Yahoo etiqueta con nuestro ticker aunque el
# titular trate de ellos (ASTS recibia titulares de Rocket Lab). Solo se descarta
# si el texto nombra al competidor Y no cita a la empresa; nada de terminos de
# sector. Lista verificada a mano, ampliable por caso.
COMPETITOR_ONLY_TERMS: dict[str, tuple[str, ...]] = {
    "ASTS": ("Rocket Lab", "RKLB"),
}
_NAME_NOISE = frozenset({
    "inc", "corp", "corporation", "co", "company", "ltd", "plc", "sa", "nv", "ag",
    "the", "group", "holdings", "holding", "limited", "sme", "s.a.",
})
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
# Paginas de datos que Google News/Yahoo mezclan con la prensa: fichas de
# precio, cotizaciones de opciones, tokens cripto, perfiles. No son noticias.
# Reglas conservadoras: mejor perder un titular dudoso que ensuciar el feed.
_DATA_PAGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # Solo FORMATO de ficha de datos, nunca tema: una noticia sobre acciones
        # tokenizadas, previsiones o cripto es prensa y debe conservarse.
        r"\b(?:19|20)\d{2}\s+\d[\d.,]*\s+(?:call|put)\b",  # "Oct 2026 136.000 call"
        r"\b[A-Z]{1,6}\d{6}[CP]\d{8}\b",  # simbolo OCC: SPCX261030C00136000
        r"\(\s*[A-Z0-9]{3,10}\s*-\s*(?:USD|EUR|USDT|GBP)\s*\)",  # par: (ASTSX-USD)
        r"\(\d?x\s+(?:long|short)\)\s*\([A-Z0-9]{4,}\)",  # ETP apalancado + codigo
        r"^(?:[A-Z]{1,5}\s+)?(?:precio de acciones|stock price|share price)[, ].*\b(?:historial|history)\b",
        r"\bprecio de acciones, noticias, cotizaci[oó]n e historial\b",
        r"^(?:[A-Z]{1,5}\s+)?(?:gr[aá]fico de acciones interactivo|datos y precios hist[oó]ricos)\b",
        r"^(?:[A-Z]{1,5}\s+)?(?:predicci[oó]n|previsi[oó]n) de precio de\b",
        r"^(?:[A-Z]{1,5}\s+)?precio,? gr[aá]ficos,? capitalizaci[oó]n de mercado\b",
        r"\bperfil y datos de (?:criptomonedas|cripto)\b",
        r"\bvalor de precio de\b",
        r"\binformaci[oó]n de precios,? capitalizaci[oó]n de mercado\b",
        r"\bprevisi[oó]n de [A-Z]{2,5}:\s*precio objetivo\s+(?:19|20)\d{2}\b",
    )
)


def is_data_page_headline(title: str | None) -> bool:
    text = (title or "").strip()
    return any(pattern.search(text) for pattern in _DATA_PAGE_PATTERNS)


# Comunicados de despachos de abogados captando demandantes. No son hechos de la
# empresa (no aportan cifras ni eventos) pero el motor los puntuaba como criticos
# por palabras como "fraud" o "investigation". Solo se descarta la captacion
# (nombre de despacho, plazo de demandante principal, "en nombre de inversores");
# la noticia periodistica de una demanda colectiva no encaja aqui.
_LAW_FIRM_SOLICITATION = re.compile(
    "|".join(
        (
            r"\b(?:rosen law firm|pomerantz|levi\s*&\s*korsinsky|bragar eagel|faruqi|"
            r"kessler topaz|gross law firm|schall law|hagens berman|bernstein liebhard|"
            r"glancy prongay|robbins geller|johnson fistel|block & leviton|"
            r"the schall|kirby mcinerney|law offices of|bronstein, gewirtz|"
            r"portnoy law|howard g\. smith|rigrodsky|holzer & holzer|"
            r"frank r\. cruz|the law offices)\b",
            r"\blead plaintiff deadline\b",
            r"\bdeadline in \d+ days\b[^.]{0,180}\bclass action\b",
            r"\b(?:investors?|shareholders?|stockholders?)\s+(?:who|that)\s+(?:lost|suffered|incurred)\b",
            r"\b(?:investigat\w+|announces?|reminds?|encourages?|urges?)\b[^.]{0,80}\bon behalf of\b[^.]{0,40}\b(?:investors?|shareholders?|stockholders?)\b",
            r"\b(?:securities )?class action (?:lawsuit )?(?:deadline|reminder)\b",
            r"\bshareholder (?:alert|rights alert)\b",
            # Captacion de demandantes sin nombre de despacho conocido:
            # "Investors Have Opportunity to Lead ... Securities Fraud Lawsuit with SBS Law".
            r"\bopportunity to lead\b.{0,120}\b(?:lawsuit|class action)\b",
            r"\b(?:lawsuit|class action)\b[^.]{0,40}\bwith [A-Z][\w&.,' -]{1,40}\b(?:law|llp|pllc|p\.c\.)\b",
            r"\b(?:law (?:firm|offices?|group)|llp|pllc)\b[^.]{0,60}\b(?:investors?|shareholders?)\b[^.]{0,60}\b(?:lawsuit|class action|claims?)\b",
            # Captacion sin despacho de la lista, vista en prod (2026-10-29):
            # «SueWallSt Alerts ... Stockholders of Securities Class Action» y
            # «UPCOMING DEADLINE: ... Class Action». Verbo «alerts» + destinatario
            # accionista + demanda: ningun patron anterior cubria esa forma.
            r"\bsuewallst\b",
            r"\bupcoming deadline\b[^.]{0,180}\b(?:class action|stockholders?|shareholders?)\b",
            r"\balerts?\b[^.]{0,120}\b(?:stockholders?|shareholders?|investors?)\b[^.]{0,80}\b(?:class action|securities (?:fraud|lawsuit))\b",
        )
    ),
    re.IGNORECASE,
)


def is_law_firm_solicitation(title: str | None, summary: str | None = None) -> bool:
    return bool(_LAW_FIRM_SOLICITATION.search(f"{title or ''} {summary or ''}"))


# Etiquetas de «medio» de Google News que en realidad son granjas de
# contenido u organizaciones, verificadas en prod (ampliar solo con evidencia).
JUNK_PUBLISHER_LABELS = {"bitcoin foundation"}

_PUBLISHER_RE = re.compile(r"^(?P<title>.+?)\s+-\s+(?P<publisher>[^-]{2,60})$")


def is_us_listed(company) -> bool:
    ticker = (getattr(company, "ticker", "") or "").upper()
    exchange = getattr(company, "exchange", "") or ""
    return bool(_TICKER_RE.match(ticker)) and bool(US_EXCHANGE_RE.search(exchange))


def yahoo_feed_url(ticker: str) -> str:
    return (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={quote_plus(ticker.upper())}&region=US&lang=en-US"
    )


def google_feed_url(company, *, lang: str = "en") -> str:
    name = re.sub(r"\s+(inc|corp|corporation|co|ltd|plc|holdings?)\.?$", "", company.name or "", flags=re.I)
    query = f'"{name.strip()}" OR {company.ticker.upper()}' if name.strip() else company.ticker.upper()
    hl, gl, ceid = ("es", "ES", "ES:es") if lang == "es" else ("en-US", "US", "US:en")
    return (
        f"https://news.google.com/rss/search?q={quote_plus(query)}"
        f"&hl={hl}&gl={gl}&ceid={ceid}"
    )


def is_competitor_only(company, text: str, evidence_level) -> bool:
    terms = COMPETITOR_ONLY_TERMS.get((getattr(company, "ticker", "") or "").upper(), ())
    if not terms or not any(
        re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", text, flags=re.IGNORECASE) for term in terms
    ):
        return False
    return not company_mentioned(company, text, evidence_level)


def _only_ticker_prefix_mention(company, title: str, summary: str) -> bool:
    """El titular solo nombra a la empresa por un ticker pegado delante.

    El feed de Yahoo de NVDA trajo "NVDA Data Centers, Aerospace...: ... Fastenal's
    results ...": el ticker es una etiqueta anadida y el articulo trata de otra
    empresa. Se descarta SOLO si el titular empieza por "TICKER " y, quitada esa
    etiqueta, ni el titular ni el resumen citan el ticker, el nombre (palabras
    distintivas de 4+ letras) ni un alias verificado. Un articulo sobre la empresa
    siempre se nombra en su texto, asi que no se pierde prensa legitima.
    """
    ticker = (getattr(company, "ticker", "") or "").upper()
    if not ticker or not re.match(rf"^{re.escape(ticker)}\s+\S", (title or "").strip()):
        return False
    prefix = re.compile(rf"^\s*{re.escape(ticker)}\s+")
    rest = f"{prefix.sub('', title or '', count=1)} {prefix.sub('', summary or '', count=1)}"
    terms = [ticker, *VERIFIED_ALIASES.get(ticker, ())]
    terms += [
        w for w in re.split(r"\W+", getattr(company, "name", "") or "")
        if len(w) >= 4 and w.lower() not in _NAME_NOISE
    ]
    return not any(
        re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", rest, flags=re.IGNORECASE) for term in terms
    )


def _company_terms(company) -> list[str]:
    """Terminos que identifican a la empresa en texto libre: ticker, alias
    verificados y palabras distintivas (4+ letras) del nombre."""
    ticker = (getattr(company, "ticker", "") or "").upper()
    terms = [ticker, *VERIFIED_ALIASES.get(ticker, ())] if ticker else []
    terms += [
        w for w in re.split(r"\W+", getattr(company, "name", "") or "")
        if len(w) >= 4 and w.lower() not in _NAME_NOISE
    ]
    return terms


def _cites_company_in_title(company, title: str) -> bool:
    """True si el TITULAR cita a la empresa (ticker, alias o palabra del nombre).

    Una mencion solo en el cuerpo no basta para el carril por ticker: el feed
    de Yahoo por ticker inserta articulos «relacionados» sobre OTRAS empresas
    que la mencionan de pasada (19 oct 2026: «The Bet Behind Tieto's Rally»
    atribuido a MSFT por «AI partnership with Microsoft» en el cuerpo, con
    materialidad 10). Fail-closed: sin cita en el titular, no entra al carril.
    """
    # El ticker como primera palabra SI vale como cita («MSFT raises dividend»);
    # el caso de etiqueta pegada falsa lo filtra _only_ticker_prefix_mention.
    text = (title or "").strip()
    if fails_strict_name(company, text):
        return False
    return any(
        re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", text, flags=re.IGNORECASE)
        for term in _company_terms(company)
    )


def _cites_company(company, title: str, summary: str) -> bool:
    """True si titular o resumen citan a la empresa (sin contar el ticker pegado delante).

    Terminos: el ticker, los alias verificados y las palabras distintivas (4+
    letras) del nombre, en palabra completa. El feed de Yahoo por ticker trae
    articulos «relacionados» que no tratan de la empresa (Novo Nordisk y Ken
    Griffin bajo NVDA, Verizon bajo GOOGL); como la ingesta liga la noticia al
    ticker del feed, sin esta comprobacion quedaban atribuidas a ella.
    """
    ticker = (getattr(company, "ticker", "") or "").upper()
    if not ticker:
        return True
    if fails_strict_name(company, f"{title or ''} {summary or ''}"):
        return False
    prefix = re.compile(rf"^\s*{re.escape(ticker)}\s+")
    rest = f"{prefix.sub('', title or '', count=1)} {prefix.sub('', summary or '', count=1)}"
    return any(
        re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", rest, flags=re.IGNORECASE)
        for term in _company_terms(company)
    )


def label_yahoo(result: ConnectorResult, company=None, evidence_level=None) -> ConnectorResult:
    """Fuente legible y estable: el titulo del feed es 'Yahoo! Finance: X News'."""
    result.items = [
        dataclasses.replace(item, source="Yahoo Finance")
        for item in result.items
        if not is_data_page_headline(item.title)
        and not is_law_firm_solicitation(item.title, item.summary)
        and (company is None or _cites_company_in_title(company, item.title))
        and not (company is not None and _only_ticker_prefix_mention(company, item.title, item.summary or ""))
        and not (
            company is not None
            and evidence_level is not None
            and is_competitor_only(company, f"{item.title} {item.summary}", evidence_level)
        )
    ]
    return result


def _name_phrase(name: str | None) -> str | None:
    words = [w for w in re.split(r"\s+", (name or "").strip()) if w]
    kept = [w for w in words if w.lower().strip(".,") not in _NAME_NOISE]
    # Una sola palabra generica ("Apple", "Target") es ambigua: solo vale el
    # nombre completo de dos o mas palabras, o los alias verificados.
    return " ".join(kept) if len(kept) >= 2 else None


def company_mentioned(company, text: str, evidence_level) -> bool:
    """True si el texto cita a la empresa: ticker con evidencia, alias verificado
    o nombre completo (>= 2 palabras distintivas). Sin inferir nada mas."""
    if fails_strict_name(company, text):
        return False
    if evidence_level(company.ticker, company.name, text) > 0:
        return True
    terms = list(VERIFIED_ALIASES.get(company.ticker.upper(), ()))
    phrase = _name_phrase(getattr(company, "name", None))
    if phrase:
        terms.append(phrase)
    return any(
        re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", text, flags=re.IGNORECASE)
        for term in terms
    )


def label_google(result: ConnectorResult, company, evidence_level) -> ConnectorResult:
    """Fuente = medio real (sufijo ' - Medio' del titular) y filtro de evidencia."""
    kept: list[ConnectorItem] = []
    for item in result.items:
        # Solo el titular decide la atribucion (ver _cites_company_in_title):
        # el cuerpo puede mencionar a la empresa de pasada en un articulo
        # que trata de otra (Tieto -> MSFT, 19 oct 2026).
        if is_data_page_headline(item.title) or is_law_firm_solicitation(item.title, item.summary):
            continue
        if not company_mentioned(company, item.title, evidence_level):
            continue
        match = _PUBLISHER_RE.match(item.title)
        if match:
            publisher = match.group("publisher").strip()
            # Granjas de contenido que republican noticias ajenas bajo un
            # nombre de organización: la etiqueta no es un medio y confunde
            # («Bitcoin Foundation» para una noticia de JPM, prod 19 oct
            # 2026). Se muestra el agregador, no la etiqueta.
            if publisher.casefold() in JUNK_PUBLISHER_LABELS:
                publisher = "Google News"
            item = dataclasses.replace(
                item, title=match.group("title").strip(), source=publisher
            )
        else:
            item = dataclasses.replace(item, source="Google News")
        kept.append(item)
    result.items = kept
    return result


class Deadline:
    """Presupuesto de tiempo de un barrido, con reloj inyectable para tests.

    El actor lo consulta antes de cada unidad (empresa o feed) y el resultado
    nunca debe marcarse "ok" si el barrido se corto: el coalescer solo conserva
    la marca de frescura con status "ok" y un barrido truncado debe reintentarse
    en el siguiente tick.
    """

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds
        self.truncated = False

    def remaining(self) -> float:
        return self._end - self._clock()

    def expired(self) -> bool:
        if self._clock() > self._end:
            self.truncated = True
        return self.truncated


def finalize_status(base_status: str, truncated: bool) -> str:
    """Un barrido cortado por tiempo es "partial", salvo que ya fuese "error"."""
    if truncated and base_status == "ok":
        return "partial"
    return base_status


ITEM_CHUNK = 5


def ingest_in_chunks(ingest: Callable[[ConnectorResult], dict], result: ConnectorResult, deadline: Deadline) -> int:
    """Ingiere por tandas de ITEM_CHUNK y comprueba el presupuesto entre tandas.

    NewsService analiza cada item (llamadas externas): una sola llamada con 30
    items no admite corte. Con tandas, el limite se respeta a nivel item y los
    items no tratados se descartan del barrido (el siguiente tick los recoge,
    el dedupe por URL evita duplicados). Devuelve las noticias creadas.
    """
    created = 0
    for start in range(0, len(result.items), ITEM_CHUNK):
        if deadline.expired():
            break
        part = dataclasses.replace(result, items=result.items[start : start + ITEM_CHUNK])
        created += int(ingest(part).get("created", 0))
    return created


def sweep(
    companies,
    lanes_for: Callable[[Any], list[tuple[str, str]]],
    fetch: Callable[[Any, str, str], ConnectorResult],
    ingest: Callable[[Any, ConnectorResult], dict],
    deadline: Deadline,
    *,
    pause: Callable[[], None] = lambda: None,
    on_error: Callable[[], None] = lambda: None,
) -> dict:
    """Barrido por empresa y feed con presupuesto de tiempo en cada unidad.

    El presupuesto se comprueba antes de cada empresa, antes y DESPUES de cada
    feed (una ultima unidad que pasa el limite marca truncated) y entre tandas
    de items. Un barrido truncado nunca se reporta como completo.
    """
    processed = ingested = 0
    errors: list[dict] = []
    for company in companies:
        if deadline.expired():
            break
        for lane, url in lanes_for(company):
            if deadline.expired():
                break
            try:
                result = fetch(company, lane, url)
                errors.extend(
                    {"ticker": company.ticker, "source": lane, "message": message}
                    for message in result.errors
                )
                ingested += ingest_in_chunks(lambda part: ingest(company, part), result, deadline)
                if result.status != "error":
                    processed += 1
            except Exception as exc:  # noqa: BLE001 - un feed roto no tumba el barrido
                on_error()
                errors.append(
                    {"ticker": company.ticker, "source": lane,
                     "type": type(exc).__name__, "message": redact_secrets(str(exc))}
                )
            pause()
            if deadline.expired():  # post-unidad: el ultimo feed tambien cuenta
                break
    return {"processed": processed, "ingested": ingested, "errors": errors}
