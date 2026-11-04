"""Alias de empresa sacados de datos, para todas las empresas y todos los tenants.

Petición de Nico (4-nov-2026): nada de arreglos para un caso concreto
(«SPCX → SpaceX, Starlink» escrito a mano en #4492); las marcas, productos,
filiales y personas de CADA empresa salen de datos, con su procedencia:

- Wikidata, con el QID de la empresa y el de cada alias: marcas (P1716),
  productos (P1056), filiales (P355), lo que es propiedad de la empresa o
  lo opera o fabrica (P127/P749/P137/P176 a la inversa), consejero delegado
  (P169), presidente (P488) y fundadores (P112), y la etiqueta y los
  alias del propio elemento («SpaceX» para «Space Exploration
  Technologies»). Etiqueta «verificado»: el dato existe en la fuente.
- El texto de negocio de la empresa (apartado de negocio del 10-K/20-F o
  del informe anual ESEF ya ingerido, o el perfil): nombres con marca
  registrada (®/™) o con mayúsculas internas repetidos («BlueBird»,
  «SpaceMobile»). Etiqueta «inferido» y siempre con contexto obligatorio.

Guardas comunes a todas las empresas (nada por ticker):
- longitud mínima (``MIN_LEN``), fuera palabras corrientes
  (``COMMON_WORDS``), siglas cortas y términos que son el nombre o el
  ticker de OTRA empresa del catálogo;
- un término que en Wikidata también nombra a otra cosa con peso propio
  (otro elemento con la misma etiqueta y ``AMBIGUITY_SITELINKS`` o más
  enlaces) o que es una sola palabra sin rasgos de marca exige contexto
  («BlueBird solo si habla de satélites», generalizado): el nombre de la
  empresa, sus alias no ambiguos y los términos de su sector y de sus
  productos genéricos («artificial satellite» → «satellite»);
- las personas siempre exigen contexto;
- como mucho ``MAX_LINK_ALIASES`` alias por empresa y ``MAX_SEARCH_TERMS``
  términos en el feed de búsqueda por marca, que además solo pide lo de
  los últimos 7 días (``SEARCH_WINDOW``) y nunca usa lo inferido.

Caché: ``tenants.metadata["company_aliases"]`` (columna JSON existente, sin
migración), una entrada por ticker con fecha; caduca a los
``CACHE_TTL_DAYS`` días (un fallo de la fuente se reintenta al día). La
propuesta de columna propia (``companies.metadata``) está en el HANDOFF.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

CACHE_KEY = "company_aliases"
CACHE_VERSION = 1
CACHE_TTL_DAYS = 30
ERROR_RETRY_DAYS = 1
MIN_LEN = 4
MAX_LINK_ALIASES = 12
MAX_SEARCH_TERMS = 3
MAX_PEOPLE = 2
SEARCH_MIN_WEIGHT = 10
SEARCH_WINDOW = "when:7d"
AMBIGUITY_SITELINKS = 5
MAX_CONTEXT_TERMS = 24

VERIFIED = "verificado"
INFERRED = "inferido"

# Palabras corrientes (inglés y español) y genéricas de producto/empresa que
# nunca valen como alias, se escriban como se escriban.
COMMON_WORDS = frozenset(
    {
        "about", "access", "account", "active", "block", "booster", "model", "plant", "series", "ship",
        "unit", "version", "advanced", "air", "alpha", "america", "american", "app", "apps", "apple",
        "bank", "banco", "beta", "black", "blue", "board", "book", "box", "brand", "cable", "capital",
        "card", "care", "cash", "cell", "center", "central", "city", "class", "cloud", "club", "code",
        "coin", "core", "corporate", "credit", "data", "delta", "digital", "direct", "drive", "east",
        "edge", "electric", "energy", "energia", "energía", "engine", "express", "farm", "fiber",
        "first", "flex", "fly", "fresh", "fund", "future", "gas", "general", "global", "gold", "good",
        "green", "group", "grupo", "health", "high", "home", "house", "hub", "image", "india",
        "industrial", "insurance", "international", "jordan", "light", "line", "link", "live", "local",
        "mail", "market", "media", "mobile", "money", "music", "nation", "national", "network",
        "networks", "new", "news", "next", "north", "nova", "office", "one", "online", "open",
        "orange", "pay", "people", "plus", "point", "power", "premium", "prime", "pro", "project",
        "quantum", "real", "red", "renewables", "renovables", "research", "retail", "river", "road",
        "rock", "safe", "sales", "science", "security", "service", "services", "shop", "signal",
        "smart", "social", "solar", "solutions", "space", "sport", "star", "state", "stock", "store",
        "studio", "sun", "systems", "target", "team", "tech", "technology", "telecom", "terra", "the",
        "time", "today", "total", "trade", "travel", "trust", "united", "universal", "value", "vision",
        "water", "wave", "west", "wind", "wireless", "work", "world",
    }
)
_LEGAL_SUFFIX_RE = re.compile(
    r"(?:,?\s+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|llc|l\.l\.c|plc|"
    r"s\.?a\.?u?|s\.?l\.?|n\.?v\.?|ag|se|gmbh|ab|asa|oyj|spa|s\.p\.a|holdings?|group))+\.?$",
    re.IGNORECASE,
)
_NAME_NOISE = frozenset(
    {"inc", "corp", "corporation", "co", "company", "ltd", "plc", "sa", "nv", "ag", "se",
     "the", "group", "holdings", "holding", "limited", "llc", "sme", "and", "de", "of"}
)
_QID_RE = re.compile(r"^Q\d+$")
# Rasgos de marca en un término de una palabra: mayúscula interna (iPhone,
# WhatsApp, BlueBird), dígito (A350) o signo propio (C3.ai, AT&T).
_BRANDLIKE_RE = re.compile(r"[a-z][A-Z]|\d|[.&+]")

# Tipos de alias en orden de prioridad para el tope por empresa.
KIND_ORDER = ("nombre", "marca", "producto", "filial", "persona")
_PROPS = {
    "P1716": "marca",
    "P1056": "producto",
    "P355": "filial",
    "P169": "persona",
    "P488": "persona",
    "P112": "persona",
    "P452": "sector",
}
# Relaciones inversas: elementos que son propiedad de la empresa o que
# fabrica (Instagram/WhatsApp → Meta, iPhone → Apple). Lo que solo «opera»
# (P137: centrales, presas, misiones) no entra. Los elementos numerados
# cuentan como SERIE: el nombre común de 3+ («Starlink 1130»… → «Starlink»,
# «BlueBird 6»… → «BlueBird»).
_INVERSE_PROPS = {"P127": "filial", "P749": "filial", "P176": "producto"}
_SERIES_RE = re.compile(r"^(?P<base>.+?)[\s-]*(?:\d+[A-Za-z]?|[IVX]+)$")
_DOMAIN_RE = re.compile(r"\.(?:com|net|org|io|es|co\.uk)$", re.IGNORECASE)
SERIES_MIN = 3

HttpGet = Callable[[str, dict[str, Any]], Any]


@dataclass(frozen=True)
class AliasTerm:
    termino: str
    tipo: str
    fuente: str
    etiqueta: str = VERIFIED
    qid: str | None = None
    peso: int = 0
    requiere: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requiere"] = list(self.requiere)
        return {k: v for k, v in data.items() if v not in (None, [], 0) or k in ("termino", "tipo")}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AliasTerm:
        return cls(
            termino=str(data["termino"]),
            tipo=str(data.get("tipo") or "marca"),
            fuente=str(data.get("fuente") or "wikidata"),
            etiqueta=str(data.get("etiqueta") or VERIFIED),
            qid=data.get("qid"),
            peso=int(data.get("peso") or 0),
            requiere=tuple(data.get("requiere") or ()),
        )

    @property
    def ambiguous(self) -> bool:
        return bool(self.requiere)


@dataclass
class AliasRecord:
    ticker: str
    qid: str | None = None
    fetched_at: str | None = None
    aliases: list[AliasTerm] = field(default_factory=list)
    contexto: list[str] = field(default_factory=list)
    fuentes: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "v": CACHE_VERSION,
            "qid": self.qid,
            "fetched_at": self.fetched_at,
            "aliases": [a.as_dict() for a in self.aliases],
            "contexto": list(self.contexto),
            "fuentes": list(self.fuentes),
            **({"error": self.error} if self.error else {}),
        }

    @classmethod
    def from_dict(cls, ticker: str, data: dict[str, Any]) -> AliasRecord:
        return cls(
            ticker=ticker,
            qid=data.get("qid"),
            fetched_at=data.get("fetched_at"),
            aliases=[AliasTerm.from_dict(a) for a in data.get("aliases") or [] if a.get("termino")],
            contexto=[str(t) for t in data.get("contexto") or []],
            fuentes=[str(s) for s in data.get("fuentes") or []],
            error=data.get("error"),
        )

    def is_fresh(self, now: datetime | None = None) -> bool:
        if not self.fetched_at:
            return False
        try:
            at = datetime.fromisoformat(self.fetched_at)
        except ValueError:
            return False
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        ttl = timedelta(days=ERROR_RETRY_DAYS if self.error else CACHE_TTL_DAYS)
        return (now or datetime.now(UTC)) - at < ttl


# --------------------------------------------------------------------------
# Normalización y guardas
# --------------------------------------------------------------------------


def clean_term(term: str | None) -> str:
    """Sin sufijo legal ni puntuación final: «Instagram, LLC» → «Instagram»."""
    text = re.sub(r"\s+", " ", (term or "").strip())
    text = re.sub(r"\s*\([^)]*\)$", "", text)  # «Facebook (Israel)»
    original = text
    previous = None
    while previous != text:
        previous = text
        text = _LEGAL_SUFFIX_RE.sub("", text).strip().rstrip(",")
    text = text.strip(" ,;:")
    # «The Boring Company» no se queda en «The Boring».
    if re.fullmatch(r"(?i)the\s+\S+", text):
        return original
    return text


def name_phrase(name: str | None) -> str:
    return clean_term(name)


def _core_name_words(name: str | None) -> list[str]:
    return [
        w for w in re.split(r"[^\w&.]+", clean_term(name))
        if len(w) >= MIN_LEN and w.casefold() not in _NAME_NOISE and w.casefold() not in COMMON_WORDS
    ]


def _head_noun(label: str) -> str | None:
    words = [w for w in re.split(r"\s+", label.strip()) if w]
    if len(words) < 2:
        return None
    head = words[-1]
    return head if len(head) >= 5 and head.casefold() not in _NAME_NOISE else None


def is_generic_label(label: str) -> bool:
    """Una clase genérica de Wikidata va en minúscula («smartphone»,
    «artificial satellite»); una marca o un nombre propio, no."""
    return bool(label) and label[0].islower() and not _BRANDLIKE_RE.search(label)


def reject_reason(
    term: str,
    *,
    company_ticker: str,
    company_name: str | None,
    catalog_terms: dict[str, set[str]] | None = None,
) -> str | None:
    """Motivo por el que el término no vale como alias, o None si vale."""
    text = term.strip()
    folded = text.casefold()
    if len(text) < MIN_LEN:
        return "corto"
    if folded in COMMON_WORDS:
        return "palabra_corriente"
    if _QID_RE.match(text):
        return "sin_etiqueta"
    if re.fullmatch(r"[A-Z]{1,5}", text):
        return "sigla"
    if _DOMAIN_RE.search(text):
        return "dominio"
    if folded == company_ticker.casefold() or folded == name_phrase(company_name).casefold():
        return "es_el_nombre"
    owners = (catalog_terms or {}).get(folded, set()) - {company_ticker.upper()}
    if owners:
        return "otra_empresa:" + ",".join(sorted(owners))
    return None


def needs_context(term: str, *, kind: str, homonyms: int | None = None) -> bool:
    """Exige contexto: personas y homónimos con peso propio en Wikidata
    («Threads», «Messenger», «BlueBird»). Sin esa comprobación (fuente
    caída o término inferido), toda palabra suelta sin rasgos de marca."""
    if kind == "persona":
        return True
    if homonyms is not None:
        return homonyms > 0
    words = term.split()
    return len(words) == 1 and not _BRANDLIKE_RE.search(term)


def context_terms(
    company_name: str | None, aliases: Iterable[AliasTerm], generic_labels: Iterable[str]
) -> list[str]:
    """Contexto que vale para los alias ambiguos de la empresa: su nombre, sus
    alias que no son ambiguos y sus clases genéricas (sector, productos)."""
    seen: dict[str, str] = {}

    def add(term: str | None) -> None:
        term = (term or "").strip()
        if len(term) >= MIN_LEN and term.casefold() not in seen and term.casefold() not in COMMON_WORDS:
            seen[term.casefold()] = term

    phrase = name_phrase(company_name)
    if len(phrase.split()) >= 2:
        add(phrase)
    for word in _core_name_words(company_name):
        add(word)
    for alias in aliases:
        if not alias.requiere and alias.tipo != "persona":
            add(alias.termino)
    for label in generic_labels:
        add(label)
        add(_head_noun(label))
    return list(seen.values())[:MAX_CONTEXT_TERMS]


def finalize(
    ticker: str,
    company_name: str | None,
    candidates: Iterable[AliasTerm],
    generic_labels: Iterable[str],
    *,
    catalog_terms: dict[str, set[str]] | None = None,
    homonyms: dict[str, int] | None = None,
) -> tuple[list[AliasTerm], list[str]]:
    """``homonyms``: término → homónimos con peso propio (solo los que se
    comprobaron; el resto se trata con la regla de la palabra suelta)."""
    """Aplica las guardas, el contexto y el tope a los candidatos de una empresa."""
    kept: dict[str, AliasTerm] = {}
    for cand in collapse_series(candidates):
        term = clean_term(cand.termino)
        if cand.tipo == "persona" and len(term.split()) < 2:
            continue
        if reject_reason(term, company_ticker=ticker, company_name=company_name, catalog_terms=catalog_terms):
            continue
        key = term.casefold()
        previous = kept.get(key)
        if previous is not None:
            # El mismo término por dos vías: el tipo más fuerte, el mayor peso.
            best = min((previous, cand), key=lambda a: (a.etiqueta != VERIFIED, KIND_ORDER.index(a.tipo) if a.tipo in KIND_ORDER else 9))
            kept[key] = AliasTerm(term, best.tipo, best.fuente, best.etiqueta, best.qid or previous.qid, max(previous.peso, cand.peso))
            continue
        kept[key] = AliasTerm(term, cand.tipo, cand.fuente, cand.etiqueta, cand.qid, cand.peso)
    # Verificados antes que inferidos; dentro, por peso (enlaces de Wikipedia
    # del elemento: lo que la prensa cita de verdad) y luego por tipo.
    ranked = sorted(
        kept.values(),
        key=lambda a: (a.etiqueta != VERIFIED, a.tipo == "persona", -a.peso,
                       KIND_ORDER.index(a.tipo) if a.tipo in KIND_ORDER else 9, a.termino),
    )
    people = [a for a in ranked if a.tipo == "persona"][:MAX_PEOPLE]
    others = [a for a in ranked if a.tipo != "persona"][: MAX_LINK_ALIASES - len(people)]
    ordered = others + people
    flags = {
        a.termino.casefold(): a.etiqueta == INFERRED
        or needs_context(a.termino, kind=a.tipo, homonyms=(homonyms or {}).get(a.termino.casefold()))
        for a in ordered
    }
    provisional = [AliasTerm(a.termino, a.tipo, a.fuente, a.etiqueta, a.qid, a.peso, ("*",) if flags[a.termino.casefold()] else ()) for a in ordered]
    context = context_terms(company_name, provisional, generic_labels)
    final: list[AliasTerm] = []
    for a in provisional:
        required = tuple(t for t in context if t.casefold() != a.termino.casefold()) if a.requiere else ()
        if a.requiere and not required:
            continue  # exige contexto y no hay ninguno con el que comprobarlo: fuera
        final.append(AliasTerm(a.termino, a.tipo, a.fuente, a.etiqueta, a.qid, a.peso, required))
    return final, context


def collapse_series(candidates: Iterable[AliasTerm]) -> list[AliasTerm]:
    """Elementos numerados de una misma serie («BlueBird 6», «Starlink 1130»)
    se sustituyen por el nombre de la serie si tiene ``SERIES_MIN`` o más;
    sueltos, no valen (demasiado concretos). Las «serie» que no forman
    serie se descartan."""
    series: dict[str, list[AliasTerm]] = {}
    rest: list[AliasTerm] = []
    for cand in candidates:
        match = _SERIES_RE.match(cand.termino.strip()) if cand.tipo != "persona" else None
        if match and len(match.group("base").strip()) >= MIN_LEN:
            series.setdefault(match.group("base").strip(), []).append(cand)
        elif cand.tipo != "serie":
            rest.append(cand)
    out = list(rest)
    for base, members in series.items():
        count = len({m.termino for m in members})
        if count >= SERIES_MIN:
            sample = members[0]
            # Peso de la serie: 10 por elemento (tope 500), comparable a los
            # enlaces de Wikipedia de un elemento suelto.
            out.append(AliasTerm(base, "marca", sample.fuente, sample.etiqueta, None, min(10 * count, 500)))
        else:
            out.extend(m for m in members if m.tipo != "serie")
    return out


def search_terms(
    record: AliasRecord | None, *, company_name: str | None = None, limit: int = MAX_SEARCH_TERMS
) -> list[str]:
    """Términos del feed de búsqueda por marca: verificados, no ambiguos,
    marca/producto/filial/nombre, con peso propio (``SEARCH_MIN_WEIGHT``),
    que no repitan el nombre que ya busca el feed por nombre; los de más
    peso primero."""
    if record is None:
        return []
    phrase = name_phrase(company_name).casefold()
    picked = [
        a for a in record.aliases
        if a.etiqueta == VERIFIED and not a.requiere and a.tipo in ("nombre", "marca", "producto", "filial")
        and a.peso >= SEARCH_MIN_WEIGHT
        and not (phrase and phrase in a.termino.casefold())
    ]
    # Lo que contiene un término ya elegido («SpaceX CRS» con «SpaceX») sobra.
    picked.sort(key=lambda a: (-a.peso, KIND_ORDER.index(a.tipo), a.termino))
    chosen: list[AliasTerm] = []
    for alias in picked:
        if any(re.search(rf"(?<![\w]){re.escape(c.termino)}(?![\w])", alias.termino, re.IGNORECASE) for c in chosen):
            continue
        chosen.append(alias)
    picked = chosen
    picked.sort(key=lambda a: (-a.peso, KIND_ORDER.index(a.tipo), a.termino))
    return [a.termino for a in picked[:limit]]


# --------------------------------------------------------------------------
# Fuente: Wikidata
# --------------------------------------------------------------------------


# Wikimedia exige un agente con forma de contacto: con el genérico de la app
# la consulta queda limitada a 1 petición por minuto.
USER_AGENT = "GerarAI-news-aliases/1.0 (https://gerarai.duckdns.org)"


def _wikidata_only(url: str) -> bool:
    return urlsplit(url).hostname in {"query.wikidata.org", "www.wikidata.org"}


def _default_get(url: str, params: dict[str, Any]) -> Any:
    from app.services.public_fetch import fetch_public_url

    raw, _mime, _final = fetch_public_url(
        f"{url}?{urlencode(params)}", max_bytes=8 * 1024 * 1024, timeout=55.0,
        allowed_url=_wikidata_only, user_agent=USER_AGENT,
    )
    return json.loads(raw)


def _sparql(get: HttpGet, query: str) -> list[dict[str, Any]]:
    data = get(WIKIDATA_SPARQL, {"query": query, "format": "json"})
    return list(((data or {}).get("results") or {}).get("bindings") or [])


def _value(binding: dict[str, Any], key: str) -> str | None:
    cell = binding.get(key)
    return cell.get("value") if isinstance(cell, dict) else None


def _qid(uri: str | None) -> str | None:
    if not uri:
        return None
    tail = uri.rsplit("/", 1)[-1]
    return tail if _QID_RE.match(tail) else None


def _tokens(text: str | None) -> set[str]:
    return {w for w in re.split(r"\W+", clean_term(text).casefold()) if len(w) >= 2 and w not in _NAME_NOISE}


def _exchange_tokens(exchange: str | None) -> set[str]:
    text = (exchange or "").casefold()
    tokens = set(re.split(r"\W+", text))
    if "nasdaq" in text:
        tokens.add("nasdaq")
    if "nyse" in text or "new york" in text:
        tokens |= {"new", "york"}
    if text in {"bme", "mce", "mc", "bmad"} or "madrid" in text or "bme" in tokens:
        tokens.add("madrid")
    if text in {"lse", "l"} or "london" in text:
        tokens.add("london")
    if "euronext" in text or text in {"as", "ams", "pa", "par"}:
        tokens.add("euronext")
    return {t for t in tokens if t}


def resolve_qid(company: Any, get: HttpGet) -> str | None:
    """QID de la empresa: por ISIN, por ticker cotizado (con el nombre y la
    bolsa para desempatar) o por su nombre exacto. Sin coincidencia, None."""
    isin = (getattr(company, "isin", None) or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin):
        rows = _sparql(get, f'SELECT ?item WHERE {{ ?item wdt:P946 "{isin}" . }} LIMIT 3')
        qids = {_qid(_value(r, "item")) for r in rows} - {None}
        if len(qids) == 1:
            return qids.pop()
    ticker = (getattr(company, "ticker", "") or "").upper().split(".")[0]
    name_tokens = _tokens(getattr(company, "name", None))
    if re.fullmatch(r"[A-Z0-9\-]{1,10}", ticker):
        rows = _sparql(
            get,
            f'SELECT ?item ?itemLabel ?exLabel WHERE {{ ?item p:P414 ?st . ?st pq:P249 "{ticker}" . '
            "OPTIONAL { ?st ps:P414 ?ex } "
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,es,mul". } } LIMIT 20',
        )
        exchange = _exchange_tokens(getattr(company, "exchange", None))
        scored: dict[str, int] = {}
        for row in rows:
            qid = _qid(_value(row, "item"))
            if not qid:
                continue
            overlap = len(name_tokens & _tokens(_value(row, "itemLabel")))
            bonus = 1 if exchange & _exchange_tokens(_value(row, "exLabel")) else 0
            scored[qid] = max(scored.get(qid, -1), overlap * 2 + bonus)
        if scored:
            best = max(scored.values())
            winners = [q for q, s in scored.items() if s == best]
            if len(winners) == 1 and (best >= 2 or len(scored) == 1):
                return winners[0]
    phrase = name_phrase(getattr(company, "name", None))
    if phrase:
        data = get(
            WIKIDATA_API,
            {"action": "wbsearchentities", "search": phrase, "language": "en", "type": "item",
             "limit": 5, "format": "json"},
        )
        for hit in (data or {}).get("search") or []:
            texts = {clean_term(hit.get("label")).casefold(), clean_term((hit.get("match") or {}).get("text")).casefold()}
            if phrase.casefold() in texts and _QID_RE.match(str(hit.get("id") or "")):
                return str(hit["id"])
    return None


def _candidate_rows(qid: str, get: HttpGet) -> list[dict[str, Any]]:
    """Filas (prop, val, etiqueta, enlaces, dir) en dos consultas: las
    directas siempre completas; las inversas (lo fabricado, que en grandes
    grupos son miles) con tope propio."""
    direct = " ".join(f"p:{p}" for p in _PROPS)
    inverse = " ".join(f"wdt:{p}" for p in _INVERSE_PROPS)
    labels = """  OPTIONAL {{ ?val wikibase:sitelinks ?sl }}
  OPTIONAL {{ ?val rdfs:label ?enl FILTER(LANG(?enl) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,es,mul". }}"""
    rows = _sparql(
        get,
        f"""SELECT ?prop ?val ?valLabel ?enl ?sl ?dir WHERE {{
  VALUES ?prop {{ {direct} }}
  wd:{qid} ?prop ?st . ?pp wikibase:claim ?prop ; wikibase:statementProperty ?ps . ?st ?ps ?val .
  FILTER NOT EXISTS {{ ?st pq:P582 ?end }}
  FILTER NOT EXISTS {{ ?st wikibase:rank wikibase:DeprecatedRank }}
  BIND("d" AS ?dir)
{labels.format()}
}} LIMIT 400""",
    )
    rows += _sparql(
        get,
        f"""SELECT ?prop ?val ?valLabel ?enl ?sl ?dir WHERE {{
  VALUES ?prop {{ {inverse} }}
  ?val ?prop wd:{qid} . FILTER NOT EXISTS {{ ?val wdt:P576 ?gone }}
  # Bienes con coordenadas (centrales, presas, edificios) no son marcas.
  FILTER NOT EXISTS {{ ?val wdt:P625 ?where }}
  BIND("i" AS ?dir)
{labels.format()}
}} LIMIT 1500""",
    )
    return rows


def _own_labels(qid: str, get: HttpGet) -> list[tuple[str, bool]]:
    """(etiqueta, es_principal) del propio elemento: la principal («SpaceX»)
    y los alias («Facebook», «AST & Science»)."""
    rows = _sparql(
        get,
        f'SELECT ?l ?k WHERE {{ {{ wd:{qid} rdfs:label ?l BIND("p" AS ?k) }} UNION '
        f'{{ wd:{qid} skos:altLabel ?l BIND("a" AS ?k) }} FILTER(LANG(?l) IN ("en","es","mul")) }}',
    )
    labels: dict[str, bool] = {}
    for row in rows:
        label = _value(row, "l") or ""
        if label:
            labels[label] = labels.get(label, False) or _value(row, "k") == "p"
    return sorted(labels.items())


def _claims_point_to(entity: dict[str, Any], qids: set[str]) -> bool:
    for statements in ((entity or {}).get("claims") or {}).values():
        for statement in statements or []:
            value = (((statement or {}).get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(value, dict) and value.get("id") in qids:
                return True
    return False


def homonym_weight(
    term: str,
    own_qids: set[str],
    get: HttpGet,
    own_names: Iterable[str] = (),
    own_weight: int = 0,
    company_qid: str | None = None,
) -> int:
    """Cuántos OTROS elementos de Wikidata con peso propio (≥
    ``AMBIGUITY_SITELINKS`` enlaces) se llaman exactamente así. Uno cuya
    descripción nombra a la empresa («smartphone by Apple») es de la misma
    familia, no un homónimo."""
    names = [n for n in own_names if n]
    data = get(
        WIKIDATA_API,
        {"action": "wbsearchentities", "search": term, "language": "en", "type": "item", "limit": 10, "format": "json"},
    )
    others = []
    family = set(own_qids) | ({company_qid} if company_qid else set())
    for hit in (data or {}).get("search") or []:
        qid = str(hit.get("id") or "")
        texts = {str(hit.get("label") or "").casefold(), str((hit.get("match") or {}).get("text") or "").casefold()}
        description = str(hit.get("description") or "")
        same_family = any(re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", description, re.IGNORECASE) for n in names)
        if qid and same_family:
            family.add(qid)
        if qid and qid not in own_qids and term.casefold() in texts and not same_family:
            others.append(qid)
    if not others:
        return 0
    entities = get(
        WIKIDATA_API,
        {"action": "wbgetentities", "ids": "|".join(others[:10]), "props": "sitelinks|claims", "format": "json"},
    )
    # Homónimo con peso propio: al menos AMBIGUITY_SITELINKS enlaces y al
    # menos la cuarta parte de los del alias (Instagram, con 167, no se
    # vuelve ambiguo por una canción homónima con 6).
    floor = max(AMBIGUITY_SITELINKS, own_weight // 4)
    heavy = 0
    for entity in ((entities or {}).get("entities") or {}).values():
        # Un elemento que apunta a la empresa (la constelación Starlink,
        # operada por SpaceX) es de la familia, no un homónimo.
        if _claims_point_to(entity, family):
            continue
        if len((entity or {}).get("sitelinks") or {}) >= floor:
            heavy += 1
    return heavy


def fetch_wikidata(
    company: Any,
    get: HttpGet | None = None,
    *,
    catalog_terms: dict[str, set[str]] | None = None,
    check_homonyms: bool = True,
) -> AliasRecord:
    """Alias verificados de la empresa en Wikidata (red: ``get``)."""
    get = get or _default_get
    ticker = (getattr(company, "ticker", "") or "").upper()
    name = getattr(company, "name", None)
    qid = resolve_qid(company, get)
    record = AliasRecord(ticker=ticker, qid=qid, fuentes=["wikidata"])
    if qid is None:
        record.error = "sin_qid"
        return record
    candidates: list[AliasTerm] = []
    generic: list[str] = []
    own_qids = {qid}
    own_names: set[str] = set(_core_name_words(name))
    for label, main in _own_labels(qid, get):
        candidates.append(AliasTerm(label, "nombre", "wikidata", VERIFIED, qid, 1_000 if main else 0))
        if main:
            own_names |= {w for w in _core_name_words(label)} | {clean_term(label)}
    for row in _candidate_rows(qid, get):
        prop = (_value(row, "prop") or "").rsplit("/", 1)[-1]
        direction = _value(row, "dir")
        kind = (_PROPS if direction == "d" else _INVERSE_PROPS).get(prop)
        value_qid = _qid(_value(row, "val"))
        label = (_value(row, "enl") or _value(row, "valLabel") or "").strip()
        if not kind or not value_qid or not label or label == value_qid:
            continue
        if kind == "sector" or is_generic_label(label):
            generic.append(label)
            continue
        own_qids.add(value_qid)
        candidates.append(AliasTerm(label, kind, "wikidata", VERIFIED, value_qid, int(_value(row, "sl") or 0)))
    homonyms: dict[str, int] = {}
    if check_homonyms:
        provisional, _ = finalize(ticker, name, candidates, generic, catalog_terms=catalog_terms)
        for alias in provisional:
            if alias.tipo == "persona":
                continue
            try:
                homonyms[alias.termino.casefold()] = homonym_weight(
                    alias.termino, own_qids, get, own_names, own_weight=alias.peso, company_qid=qid
                )
            except Exception:  # noqa: BLE001 - sin comprobación: se trata como ambiguo si es una palabra
                continue
    record.aliases, record.contexto = finalize(
        ticker, name, candidates, generic, catalog_terms=catalog_terms, homonyms=homonyms
    )
    return record


# --------------------------------------------------------------------------
# Fuente: texto de negocio de la empresa («inferido»)
# --------------------------------------------------------------------------

_MARKED_RE = re.compile(r"\b([A-Z][\w.&-]*(?:\s+[A-Z][\w.&-]*){0,2})\s?(?:®|™|\(R\)|\(TM\))")
_CAMEL_RE = re.compile(r"\b((?:[A-Z][a-z]+){2,}|[a-z]+[A-Z]\w+)\b")


def infer_from_text(text: str | None, *, fuente: str, company_name: str | None = None, min_count: int = 2) -> list[AliasTerm]:
    """Nombres propios de la empresa en su texto de negocio: con ®/™, o con
    mayúsculas internas y repetidos. Siempre «inferido» (exigen contexto)."""
    body = text or ""
    found: dict[str, int] = {}
    for match in _MARKED_RE.finditer(body):
        term = match.group(1).strip()
        found[term] = found.get(term, 0) + min_count
    for match in _CAMEL_RE.finditer(body):
        term = match.group(1)
        found[term] = found.get(term, 0) + 1
    own = {w.casefold() for w in _core_name_words(company_name)}
    return [
        AliasTerm(term, "marca", fuente, INFERRED, None, count)
        for term, count in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= min_count and term.casefold() not in own
    ]


def business_text(db: Session, company_id: int, *, limit_chars: int = 60_000) -> tuple[str | None, str | None]:
    """Texto de negocio ya ingerido: el informe anual más reciente (10-K,
    20-F, 40-F o ESEF) por sus primeros fragmentos. (texto, fuente) o (None, None)."""
    from app.models.entities import Document, DocumentChunk

    doc = db.scalar(
        select(Document)
        .where(
            Document.company_id == company_id,
            Document.retention_tombstoned_at.is_(None),
            Document.source_type.in_(("sec_10k", "sec_20f", "sec_40f", "10-K", "20-F", "40-F", "annual_report", "esef")),
        )
        .order_by(Document.published_at.desc().nullslast(), Document.id.desc())
        .limit(1)
    )
    if doc is None:
        return None, None
    chunks = db.scalars(
        select(DocumentChunk.text).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index).limit(40)
    ).all()
    text = "\n".join(chunks)[:limit_chars]
    return (text or None), (doc.source_type or "informe anual")


# --------------------------------------------------------------------------
# Caché en tenants.metadata
# --------------------------------------------------------------------------


def _tenant(db: Session, *, for_update: bool = False):
    from app.models.entities import Tenant

    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        return None
    statement = select(Tenant).where(Tenant.id == tenant_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def load_cached(db: Session) -> dict[str, AliasRecord]:
    """Alias en caché del tenant de la sesión, por ticker (vacío sin tenant)."""
    cache_key = ("_company_alias_records", db.info.get("tenant_id"))
    cached = db.info.get(cache_key)
    if cached is not None:
        return cached
    tenant = _tenant(db)
    raw = ((tenant.metadata_ or {}).get(CACHE_KEY) or {}) if tenant is not None else {}
    records = {
        ticker: AliasRecord.from_dict(ticker, data)
        for ticker, data in (raw.get("empresas") or {}).items()
        if isinstance(data, dict) and data.get("v") == CACHE_VERSION
    }
    db.info[cache_key] = records
    return records


def store(db: Session, records: Iterable[AliasRecord]) -> None:
    """Guarda en ``tenants.metadata`` solo la clave de alias, con la fila
    bloqueada (no pisa otras claves escritas a la vez)."""
    tenant = _tenant(db, for_update=True)
    if tenant is None:
        return
    metadata = dict(tenant.metadata_ or {})
    block = dict(metadata.get(CACHE_KEY) or {})
    empresas = dict(block.get("empresas") or {})
    for record in records:
        empresas[record.ticker] = record.as_dict()
    metadata[CACHE_KEY] = {"v": CACHE_VERSION, "empresas": empresas}
    tenant.metadata_ = metadata  # reasignar: el JSON no detecta mutaciones in situ
    db.commit()
    db.info.pop(("_company_alias_records", db.info.get("tenant_id")), None)


def catalog_terms(companies: Iterable[Any]) -> dict[str, set[str]]:
    """Nombre limpio y ticker de cada empresa del catálogo → sus tickers."""
    terms: dict[str, set[str]] = {}
    for company in companies:
        ticker = (getattr(company, "ticker", "") or "").upper()
        if not ticker:
            continue
        for term in (ticker, name_phrase(getattr(company, "name", None))):
            if term:
                terms.setdefault(term.casefold(), set()).add(ticker)
    return terms


def build_record(
    company: Any,
    *,
    get: HttpGet | None = None,
    text: str | None = None,
    text_source: str | None = None,
    catalog: dict[str, set[str]] | None = None,
    now: datetime | None = None,
    check_homonyms: bool = True,
) -> AliasRecord:
    """Wikidata + texto de negocio («inferido»), con guardas y fecha."""
    try:
        record = fetch_wikidata(company, get, catalog_terms=catalog, check_homonyms=check_homonyms)
    except Exception as exc:  # noqa: BLE001 - la fuente cae: se reintenta al día
        from app.core.errors import redact_secrets

        record = AliasRecord(
            ticker=(getattr(company, "ticker", "") or "").upper(), fuentes=["wikidata"],
            error=redact_secrets(f"{type(exc).__name__}: {exc}")[:200],
        )
    if text:
        inferred = infer_from_text(text, fuente=text_source or "informe anual", company_name=getattr(company, "name", None))
        if inferred:
            have = {a.termino.casefold() for a in record.aliases}
            merged = [*record.aliases, *(a for a in inferred if a.termino.casefold() not in have)]
            generic = [t for t in record.contexto if t[:1].islower()]
            record.aliases, record.contexto = finalize(
                record.ticker, getattr(company, "name", None), merged, generic, catalog_terms=catalog,
                homonyms={a.termino.casefold(): 1 for a in record.aliases if a.requiere},
            )
            record.fuentes.append(text_source or "informe anual")
    record.fetched_at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return record


def ensure_aliases(
    db: Session,
    companies: Iterable[Any],
    *,
    max_fetch: int = 5,
    get: HttpGet | None = None,
    now: datetime | None = None,
    catalog: dict[str, set[str]] | None = None,
) -> dict[str, AliasRecord]:
    """Alias en caché de cada empresa; refresca como mucho ``max_fetch``
    que falten o hayan caducado (las demás, en el siguiente barrido)."""
    if db.info.get("tenant_id") is None:
        return {}
    records = dict(load_cached(db))
    stale = [c for c in companies if not (records.get((c.ticker or "").upper()) and records[(c.ticker or "").upper()].is_fresh(now))]
    if not stale or max_fetch <= 0:
        return records
    if catalog is None:
        from app.services.company_catalog import all_companies

        catalog = catalog_terms(all_companies(db))
    fresh: list[AliasRecord] = []
    for company in stale[:max_fetch]:
        text, source = (None, None)
        if getattr(company, "id", None) is not None:
            try:
                text, source = business_text(db, company.id)
            except Exception:  # noqa: BLE001 - sin texto: solo Wikidata
                db.rollback()
        fresh.append(build_record(company, get=get, text=text, text_source=source, catalog=catalog, now=now))
    store(db, fresh)
    records.update({r.ticker: r for r in fresh})
    return records


# --------------------------------------------------------------------------
# Comprobación en texto libre
# --------------------------------------------------------------------------


def _term_pattern(term: str) -> re.Pattern[str]:
    # Una palabra sola se exige con su grafía («Threads», no «threads»);
    # varias palabras, sin distinguir mayúsculas.
    flags = 0 if len(term.split()) == 1 else re.IGNORECASE
    return re.compile(rf"(?<![\w$]){re.escape(term)}(?![\w])", flags)


def alias_hit(text: str, aliases: Iterable[AliasTerm]) -> AliasTerm | None:
    """Primer alias que aparece en el texto con su contexto obligatorio."""
    if not text:
        return None
    for alias in aliases:
        if not _term_pattern(alias.termino).search(text):
            continue
        if alias.requiere and not any(
            re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", text, re.IGNORECASE) for t in alias.requiere
        ):
            continue
        return alias
    return None
