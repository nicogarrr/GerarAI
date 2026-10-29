"""Agrupación de la misma historia entre medios (portada de /api/news).

Una misma noticia llega por varios agregadores (Yahoo, Moomoo,
MarketScreener...) con titulares reescritos y a veces en distinto idioma. La
deduplicación literal (mismo titular normalizado) no los detecta y la portada
repetía la misma historia dos o tres veces.

Criterio determinista, sin LLM: solo se agrupan eventos de la MISMA empresa
(o ambos del carril macro) publicados dentro de una ventana de 48 h cuya
firma de tokens del titular coincide con suficiente evidencia:

- Jaccard >= 0.50 sobre tokens de contenido, o
- contención >= 0.65 (intersección / firma menor), o
- >= 2 tokens distintivos compartidos (alfa, >= 7 caracteres, fuera del
  vocabulario financiero genérico y de los tokens de la empresa).

Para comparar en el mismo idioma se usa la traducción española cacheada del
titular cuando existe (misma procedencia: metadata del evento); si no hay,
el titular original. Cross-idioma sin traducción cacheada puede no agrupar:
se prefiere no juntar a juntar mal.

Solo lectura: las filas absorbidas no se borran ni se modifican; la fila
representante (la más reciente) declara la cobertura absorbida en
``coverage``/``coverage_count`` para que la UI pueda mostrar "N fuentes".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models import Company, NewsEvent
from app.services.news_headline_translation import display_translation, original_headline

WINDOW = timedelta(hours=48)
JACCARD_MIN = 0.50
CONTAINMENT_MIN = 0.65
MIN_SIGNATURE_TOKENS = 3
MIN_SHARED_DISTINCTIVE = 2

_STOPWORDS = {
    # inglés
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "as", "at", "by",
    "from", "over", "after", "amid", "says", "said", "say", "report", "reports", "reported",
    "its", "it", "is", "are", "was", "were", "be", "been", "has", "have", "had", "will",
    "would", "could", "can", "may", "might", "new", "now", "this", "that", "these", "those",
    "his", "her", "their", "our", "your", "per", "via", "into", "than", "then", "when",
    "while", "what", "which", "who", "how", "why", "not", "no", "up", "out", "off", "about",
    "against", "between", "under", "again", "here", "there", "all", "any", "both", "each",
    "more", "most", "other", "others", "some", "such", "only", "own", "same", "so", "too",
    "very", "just", "but", "if", "because", "until", "also", "us", "we", "you", "they",
    "them", "he", "she", "do", "does", "did", "don",
    # español
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y", "o",
    "en", "con", "por", "para", "que", "se", "su", "sus", "es", "son", "fue", "han", "ha",
    "como", "tras", "ante", "segun", "mas", "ya", "si", "este", "esta", "estos", "estas",
    "ese", "esa", "lo", "le", "les", "mi", "tu", "nos", "me", "te", "ser", "estar", "hace", "desde", "hasta", "donde", "cuando", "quien", "cual", "cuales", "esto", "eso",
}

# Vocabulario financiero genérico: no distingue una historia de otra.
_GENERIC_FINANCE = {
    "earnings", "revenue", "shares", "stock", "stocks", "price", "target", "rating",
    "ratings", "upgrade", "upgrades", "downgrade", "downgrades", "analyst", "analysts",
    "market", "markets", "investor", "investors", "guidance", "profit", "profits",
    "quarter", "quarterly", "results", "growth", "outlook", "forecast", "dividend",
    "buyback", "stake", "position", "holdings", "bolsa", "acciones", "mercado",
    "mercados", "resultados", "beneficio", "beneficios", "dividendo", "compra",
    "venta", "recomendacion", "analistas", "precio", "objetivo", "titulos", "valores",
    "inversores", "inversion", "crecimiento", "prevision", "trimestre", "trimestral",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    return stripped


def _company_tokens(ticker: str | None, company: Company | None) -> set[str]:
    tokens: set[str] = set()
    if ticker:
        tokens.add(_normalize(ticker))
    name = company.name if company else None
    if name:
        for token in _TOKEN_RE.findall(_normalize(name)):
            tokens.add(token)
    return tokens


def best_text(event: NewsEvent) -> str:
    """Texto de comparación: traducción española cacheada si existe; si no, titular original."""
    cached = display_translation(event)
    if cached and isinstance(cached.get("text"), str) and cached["text"].strip():
        return cached["text"]
    return original_headline(event)


def signature(text: str, company_tokens: set[str]) -> set[str]:
    """Tokens de contenido del titular: sin stopwords ni tokens de la empresa."""
    return {
        token
        for token in _TOKEN_RE.findall(_normalize(text))
        if token not in _STOPWORDS and token not in company_tokens and len(token) > 1
    }


def distinctive(tokens: set[str]) -> set[str]:
    """Tokens raros (largos, alfabéticos, fuera del vocabulario financiero genérico)."""
    return {
        token
        for token in tokens
        if token.isalpha() and len(token) >= 7 and token not in _GENERIC_FINANCE
    }


def same_story(
    sig_a: set[str], sig_b: set[str], date_a: datetime, date_b: datetime,
) -> bool:
    """Regla de agrupación: ventana de 48 h y evidencia de solape suficiente."""
    if abs(date_a - date_b) > WINDOW:
        return False
    if len(sig_a) < MIN_SIGNATURE_TOKENS or len(sig_b) < MIN_SIGNATURE_TOKENS:
        return False
    shared = sig_a & sig_b
    if not shared:
        return False
    jaccard = len(shared) / len(sig_a | sig_b)
    if jaccard >= JACCARD_MIN:
        return True
    containment = len(shared) / min(len(sig_a), len(sig_b))
    if containment >= CONTAINMENT_MIN:
        return True
    return len(distinctive(sig_a) & distinctive(sig_b)) >= MIN_SHARED_DISTINCTIVE


def exact_key(text: str) -> str:
    """Titular normalizado (minúsculas sin tildes, espacios colapsados).

    Dos filas con el mismo titular literal son la misma noticia re-publicada
    aunque la firma tenga menos de MIN_SIGNATURE_TOKENS tokens (titulares de
    una o dos palabras, donde la regla de solape no aplica).
    """
    return " ".join(_TOKEN_RE.findall(_normalize(text)))


@dataclass
class StoryGroup:
    """Una historia en portada: evento representante + cobertura absorbida."""

    event: NewsEvent
    company: Company | None
    signature: set[str]
    text_key: str
    coverage: list[dict] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        lane = (self.event.metadata_ or {}).get("news_lane")
        return (self.company.id if self.company else None, "macro" if lane == "macro" else "empresa")


def absorb(group: StoryGroup, event: NewsEvent) -> None:
    """Añade un evento absorbido a la cobertura del grupo (fuente + URL visibles)."""
    group.coverage.append({"source": event.source, "url": event.url, "title": original_headline(event)})


def find_group(groups: list[StoryGroup], event: NewsEvent, company: Company | None, sig: set[str]) -> StoryGroup | None:
    """Grupo del mismo emisor (o mismo carril) cuya firma declara la misma historia."""
    lane = (event.metadata_ or {}).get("news_lane")
    key = (company.id if company else None, "macro" if lane == "macro" else "empresa")
    text_key = exact_key(original_headline(event))
    for group in groups:
        if group.key != key:
            continue
        if text_key and group.text_key == text_key:
            return group
        if same_story(group.signature, sig, group.event.date, event.date):
            return group
    return None


def event_signature(event: NewsEvent, company: Company | None) -> set[str]:
    """Firma de comparación: tokens del titular original Y de su traducción
    española cacheada cuando existe. Medido en prod (19-oct-2026): dos copias
    de la misma nota de prensa no se agrupaban porque una ya tenía traducción
    cacheada y la otra no — firmas en idiomas disjuntos. Unir ambos idiomas
    mantiene el criterio (el solape EN↔EN o ES↔ES sigue siendo de la misma
    historia) y no junta historias distintas: dos titulares sin parentesco no
    ganan tokens compartidos por tener traducción."""
    company_tokens = _company_tokens(company.ticker if company else None, company)
    sig = signature(original_headline(event), company_tokens)
    cached = display_translation(event)
    if cached and isinstance(cached.get("text"), str) and cached["text"].strip():
        sig |= signature(cached["text"], company_tokens)
    return sig
