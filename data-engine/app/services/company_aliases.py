"""Alias y relaciones por empresa para vincular noticias que no citan el ticker.

``detect_ticker`` solo vincula con el ticker en el texto (cashtag, «(NASDAQ:
X)», sigla con nombre o contexto). Una noticia que habla de «AST SpaceMobile»,
de los satélites «BlueBird» o de «Abel Avellan» sin escribir «ASTS» se quedaba
sin empresa. Este módulo añade dos capas, solo cuando la detección por ticker
no encontró evidencia alguna (así nada de lo que ya se vinculaba cambia):

1. Alias («sobre»): nombre comercial, marcas, productos, filiales y personas
   de la empresa, de ``app/data/company_aliases.json`` y de
   ``ticker_news_lane.VERIFIED_ALIASES``, más el nombre de la empresa sin
   sufijos legales cuando tiene 2+ palabras y es único en el catálogo
   (mayúsculas como en el nombre). Un nombre de una sola palabra («Apple»,
   «Target») o repetido entre empresas no se adivina: queda en
   ``generated_name_report`` para revisarlo a mano.
2. Relaciones («relacionada»): socios, clientes, competidores, reguladores y
   términos del sector, siempre con un término de contexto obligatorio
   («AT&T» solo cuenta si la noticia habla de satélite directo al móvil).

Coste: se arma una vez por catálogo (como ``_ticker_candidates``) un índice
primera-palabra → reglas; cada noticia se parte en palabras plegadas y solo
se evalúan las reglas cuya primera palabra aparece.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import Company
from app.services.company_catalog import all_companies

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "company_aliases.json"

LINK_ABOUT = "sobre"
LINK_RELATED = "relacionada"

# Sufijos legales y de clase que no identifican a la empresa; solo se quitan
# del FINAL del nombre (y «The» del principio): «Bank of America Corp» →
# «Bank of America».
_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "plc",
        "sa",
        "s.a",
        "nv",
        "n.v",
        "ag",
        "se",
        "spa",
        "s.p.a",
        "group",
        "holdings",
        "holding",
        "limited",
        "sme",
        "llc",
        "lp",
        "l.p",
        "ord",
        "adr",
        "ads",
        "class",
        "cl",
        "the",
    }
)
_CLASS_LETTERS = frozenset({"a", "b", "c"})
_CONNECTORS = frozenset({"of", "de", "del", "and", "&", "the", "y", "la", "el", "le", "du", "des"})
_TOKEN = re.compile(r"\w+")


def _fold(text: str) -> str:
    # Mismo plegado que el prefiltro de detect_ticker (casefold + «ı»→i).
    return (text or "").casefold().replace("\u0131", "i")


def _term_regex(term: str, *, case_sensitive: bool) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in term.split())
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(rf"(?<![\w&]){body}(?![\w&])", flags)


def _any_regex(terms: list[str] | None) -> re.Pattern[str] | None:
    terms = [t for t in (terms or []) if t and t.strip()]
    if not terms:
        return None
    body = "|".join(
        r"\s+".join(re.escape(p) for p in t.split()) for t in sorted(terms, key=len, reverse=True)
    )
    return re.compile(rf"(?<![\w&])(?:{body})(?![\w&])", re.IGNORECASE)


def _first_key(term: str) -> str | None:
    match = _TOKEN.search(_fold(term))
    return match.group(0) if match else None


@dataclass(frozen=True)
class CompanyLink:
    """Vínculo noticia → empresa y por qué («via»)."""

    company: Company
    link_type: str  # LINK_ABOUT | LINK_RELATED
    via: str  # «alias:BlueBird», «nombre:AST SpaceMobile», «socio:AT&T»...
    position: int = 0

    @property
    def ticker(self) -> str:
        return self.company.ticker

    def as_metadata(self) -> dict[str, str]:
        return {"ticker": self.company.ticker, "tipo": self.link_type, "via": self.via}


@dataclass(frozen=True)
class _Rule:
    ticker: str
    via: str
    link_type: str
    pattern: re.Pattern[str]
    requires: re.Pattern[str] | None
    excludes: re.Pattern[str] | None


@lru_cache(maxsize=4)
def _load_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("empresas"), dict):
        raise ValueError(f"{path}: falta el objeto «empresas»")
    return data


def load_alias_file(path: Path | None = None) -> dict[str, Any]:
    """Contenido del fichero de alias (cacheado por proceso)."""
    return _load_file(str(path or DATA_PATH))


def _name_phrase(name: str | None) -> str | None:
    """Nombre sin sufijos legales si quedan 2+ palabras distintivas; si no, None."""
    words = [w.strip(",") for w in (name or "").split()]
    words = [w for w in words if w]
    while words:
        last = words[-1].casefold().rstrip(".")
        if last in _LEGAL_SUFFIXES or (
            last in _CLASS_LETTERS and len(words) >= 2 and words[-2].casefold().rstrip(".") in {"class", "cl"}
        ):
            words.pop()
        else:
            break
    if words and words[0].casefold() == "the":
        words.pop(0)
    distinctive = [w for w in words if w.casefold() not in _CONNECTORS]
    if len(distinctive) < 2:
        return None
    return " ".join(words)


def generated_names(companies: list[Company]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(ticker → nombre usable, nombre ambiguo → tickers que lo comparten).

    Usable = 2+ palabras distintivas y único en el catálogo. Los nombres de una
    palabra no entran en ninguno de los dos: ``generated_name_report`` los lista.
    """
    by_phrase: dict[str, list[str]] = {}
    for company in companies:
        phrase = _name_phrase(company.name)
        if phrase and company.ticker:
            by_phrase.setdefault(phrase.casefold(), []).append(company.ticker)
    usable: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    for company in companies:
        phrase = _name_phrase(company.name)
        if not phrase or not company.ticker:
            continue
        owners = by_phrase[phrase.casefold()]
        if len(owners) == 1:
            usable[company.ticker] = phrase
        else:
            ambiguous[phrase] = sorted(set(owners))
    return usable, ambiguous


def generated_name_report(db: Session) -> dict[str, Any]:
    """Para revisar a mano: nombres usados, ambiguos y de una sola palabra."""
    companies = all_companies(db)
    usable, ambiguous = generated_names(companies)
    single = sorted(
        c.ticker
        for c in companies
        if c.ticker and c.ticker not in usable and not any(c.ticker in v for v in ambiguous.values())
    )
    return {"usados": usable, "ambiguos": ambiguous, "una_palabra_o_vacio": single}


def _curated_aliases(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    from app.services.ticker_news_lane import VERIFIED_ALIASES

    merged: dict[str, list[dict[str, Any]]] = {}
    for ticker, terms in VERIFIED_ALIASES.items():
        # Marcas propias verificadas a mano en el carril por ticker; en texto
        # libre se exige la mayúscula de marca («Azure», no «azure»).
        merged.setdefault(ticker, []).extend({"termino": t, "mayusculas": True} for t in terms)
    for ticker, entry in data["empresas"].items():
        file_terms = {a["termino"] for a in entry.get("aliases", [])}
        # El fichero manda: sus reglas (contexto, exclusiones) sustituyen a la
        # entrada homónima de VERIFIED_ALIASES.
        merged[ticker] = [a for a in merged.get(ticker, []) if a["termino"] not in file_terms]
        merged[ticker].extend(entry.get("aliases", []))
    return merged


class _Matcher:
    def __init__(self, companies: list[Company], data: dict[str, Any], *, relations: bool) -> None:
        self.by_ticker = {c.ticker: c for c in companies if c.ticker}
        self.index: dict[str, list[_Rule]] = {}
        about_terms: dict[str, set[str]] = {}
        for ticker, aliases in _curated_aliases(data).items():
            if ticker not in self.by_ticker:
                continue
            for alias in aliases:
                term = alias["termino"]
                kind = alias.get("tipo", "alias")
                self._add(
                    term,
                    _Rule(
                        ticker=ticker,
                        via=f"{kind}:{term}",
                        link_type=LINK_ABOUT,
                        pattern=_term_regex(term, case_sensitive=bool(alias.get("mayusculas"))),
                        requires=_any_regex(alias.get("requiere")),
                        excludes=_any_regex(alias.get("excluye")),
                    ),
                )
                about_terms.setdefault(term.casefold(), set()).add(ticker)
        usable, _ambiguous = generated_names(companies)
        for ticker, phrase in usable.items():
            owners = about_terms.get(phrase.casefold(), set())
            if owners - {ticker}:
                continue  # el nombre es alias curado de OTRA empresa: ambiguo
            self._add(
                phrase,
                _Rule(
                    ticker=ticker,
                    via=f"nombre:{phrase}",
                    link_type=LINK_ABOUT,
                    pattern=_term_regex(phrase, case_sensitive=True),
                    requires=None,
                    excludes=None,
                ),
            )
        if relations:
            for ticker, entry in data["empresas"].items():
                if ticker not in self.by_ticker:
                    continue
                for rel in entry.get("relaciones", []):
                    requires = _any_regex(rel.get("requiere"))
                    excludes = _any_regex(rel.get("excluye"))
                    for term in rel.get("terminos", []):
                        self._add(
                            term,
                            _Rule(
                                ticker=ticker,
                                via=f"{rel['tipo']}:{term}",
                                link_type=LINK_RELATED,
                                pattern=_term_regex(term, case_sensitive=bool(rel.get("mayusculas"))),
                                requires=requires,
                                excludes=excludes,
                            ),
                        )

    def _add(self, term: str, rule: _Rule) -> None:
        key = _first_key(term)
        if key:
            self.index.setdefault(key, []).append(rule)

    def matches(self, text: str) -> list[CompanyLink]:
        if not text or not self.index:
            return []
        keys = set(_TOKEN.findall(_fold(text)))
        found: list[CompanyLink] = []
        for key in keys & self.index.keys():
            for rule in self.index[key]:
                match = rule.pattern.search(text)
                if match is None:
                    continue
                if rule.requires is not None and rule.requires.search(text) is None:
                    continue
                if rule.excludes is not None and rule.excludes.search(text) is not None:
                    continue
                found.append(
                    CompanyLink(
                        company=self.by_ticker[rule.ticker],
                        link_type=rule.link_type,
                        via=rule.via,
                        position=match.start(),
                    )
                )
        found.sort(key=lambda link: (link.position, link.ticker, link.via))
        return found


_MATCHER_KEY = "_company_alias_matcher"


def _matcher(db: Session, *, relations: bool) -> _Matcher:
    companies = all_companies(db)
    data = load_alias_file()
    cache_key = (_MATCHER_KEY, relations)
    cached = db.info.get(cache_key)
    if cached is not None and cached[0] is companies and cached[1] is data:
        return cached[2]
    matcher = _Matcher(companies, data, relations=relations)
    db.info[cache_key] = (companies, data, matcher)
    return matcher


def _pick(links: list[CompanyLink]) -> CompanyLink | None:
    """La empresa citada antes en el texto (el titular va delante); si dos
    empresas distintas empiezan en la misma posición («Google» → GOOG y
    GOOGL), es ambiguo y no se vincula."""
    if not links:
        return None
    first = links[0]
    rivals = {link.ticker for link in links if link.position == first.position}
    return first if len(rivals) == 1 else None


def find_alias_link(db: Session, text: str) -> CompanyLink | None:
    """Capa 1: empresa de la que trata el texto por alias o nombre, o None."""
    return _pick(_matcher(db, relations=False).matches(text))


def find_links(
    db: Session, text: str, about: CompanyLink | None
) -> tuple[CompanyLink | None, list[CompanyLink]]:
    """Capa 2: (vínculo principal, empresas relacionadas).

    ``about`` es el vínculo «sobre» ya decidido (ticker o alias) o None.
    Relacionadas = reglas de relación (socio, competidor, regulador, sector)
    que se cumplen, una por empresa y sin la empresa «sobre». Si no hay
    empresa «sobre» y solo UNA empresa queda relacionada, esa pasa a ser el
    vínculo principal con tipo «relacionada» (la noticia aparece en su ficha
    marcada como relacionada); con varias, ninguna se elige (el esquema
    actual guarda una sola empresa por noticia: ver HANDOFF/propuesta).
    """
    seen: dict[str, CompanyLink] = {}
    for link in _matcher(db, relations=True).matches(text):
        if link.link_type != LINK_RELATED:
            continue
        if about is not None and link.ticker == about.ticker:
            continue
        seen.setdefault(link.ticker, link)
    related = list(seen.values())
    if about is not None:
        return about, related
    if len(related) == 1:
        return related[0], []
    return None, related
