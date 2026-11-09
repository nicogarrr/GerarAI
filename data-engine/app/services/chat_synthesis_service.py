"""LLM synthesis layered on top of the deterministic chat context contract."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import current_language
from app.llm import LLMRequest, Message, ResponseFormat, parse_json_response
from app.llm.base import LLMProvider
from app.llm.chat_provider import fallback_notice
from app.llm.interactive_deadline import complete_with_deadline
from app.llm.reasoning_sections import chat_reasoning_effort
from app.schemas import ChatResponse, SynthesisSection
from app.services.budget import BudgetController, BudgetExceededError
from app.services.langfuse_client import LangfuseTracer
from app.services.llm_output_guard import _english_hits, _spanish_hits, inspect_response_text
from app.services.prompt_registry import get_prompt

logger = logging.getLogger(__name__)
PROMPT_VERSION = get_prompt("chat_source_synthesis", allow_remote=False).version
GENERAL_PROMPT_VERSION = get_prompt("chat_general", allow_remote=False).version
SECTION_ORDER = (
    "facts",
    "calculations",
    "user_hypotheses",
    "unverified_claims",
    "inferences",
    "contradictions",
    "insufficient_data",
    "conclusion",
)
SECTION_LABELS = {
    "facts": "HECHO",
    "calculations": "CALCULO",
    "user_hypotheses": "HIPOTESIS / MEMORIA DEL USUARIO",
    "unverified_claims": "AFIRMACION SIN VERIFICAR",
    "inferences": "INFERENCIA",
    "contradictions": "CONTRADICCIONES",
    "insufficient_data": "DATOS INSUFICIENTES",
    "conclusion": "CONCLUSION",
}
# Confidence ceiling when the answer is not backed by sourced facts.
MAX_CONFIDENCE_WITHOUT_FACTS = 0.35
# Phrases a model uses to say "I found nothing", in the languages the prompt
# asks for. Matched against the FACT section only, which is the section that is
# supposed to carry the numbers.
_NO_DATA_PHRASES = (
    "no se han encontrado",
    "no se ha encontrado",
    "no encontramos",
    "no hay datos",
    "no existen datos",
    "insufficient data",
    "no data available",
    "not enough data",
    "no financial data",
    "sin datos",
    "no consta",
    "no hay informacion",
    "no hay información",
)
_FACT_BULLET = re.compile(r"(?m)^\s*(?:[-*\u2022]|\d+[.)])\s+\S")


def _section_is_empty(section: SynthesisSection | None) -> bool:
    if section is None:
        return True
    return not (section.body or "").strip()


def _section_states_no_data(section: SynthesisSection | None) -> bool:
    """True when the FACT section says, in effect, "I found nothing".

    A section that contains the phrase AND still lists items is reporting
    partial data, not none, so it does not count.
    """
    if section is None:
        return True
    body = (section.body or "").strip().lower()
    if not body:
        return True
    if not any(phrase in body for phrase in _NO_DATA_PHRASES):
        return False
    return not _FACT_BULLET.search(body)


# Sections that must rest on retrieved evidence. The five-way classification
# only holds if a FACT cannot be a user hypothesis and a CONCLUSION cannot be
# a memory item.
GROUNDED_SECTIONS = frozenset({"facts", "calculations", "inferences", "conclusion"})
# Source types each grounded section may legitimately rest on.
SECTION_SOURCE_TYPES: dict[str, set[str]] = {
    # position / risk_event: la cartera y los avisos abiertos del propio
    # usuario (filas de su tenant), hechos suyos citables (chat-posicion-1).
    "facts": {"financial_fact", "document_chunk", "claim_evidence", "market_price", "position", "risk_event"},
    "calculations": {"financial_fact", "document_chunk", "claim_evidence", "market_price", "position"},
    "inferences": {
        "financial_fact",
        "document_chunk",
        "claim_evidence",
        "thesis_version",
        "rag_chunk",
        "knowledge_chunk",
        "memory_item",
        "memory_writeback",
    },
    "conclusion": {
        "financial_fact",
        "document_chunk",
        "claim_evidence",
        "claim",
        "news_event",
        "thesis_version",
        "memory_item",
        "memory_writeback",
        "position",
        "risk_event",
    },
}
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 8,
                        "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string", "enum": list(SECTION_ORDER)},
                    "body": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "body", "citations"],
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "insufficient_data": {"type": "boolean"},
        # Respuesta visible: prosa natural en castellano, sin etiquetas de
        # seccion ni IDs de cita. Las secciones quedan para el panel plegado.
        "answer": {"type": "string"},
    },
    "required": ["sections", "confidence", "insufficient_data", "answer"],
}


_CITATION_ID_RE = re.compile(
    r"\b(?:financial_fact|news_event|document_chunk|claim_evidence|claim|"
    r"thesis_version|thesis_section|rag_chunk|knowledge_chunk|memory_item|"
    r"memory_writeback|market_price|research_session|evidence_suggestion):"
)
_SECTION_LABEL_DUMP_RE = re.compile(
    r"(?m)^\s*(?:HECHO|CALCULO|HIPOTESIS|AFIRMACION SIN VERIFICAR|INFERENCIA|"
    r"CONTRADICCIONES|DATOS INSUFICIENTES|CONCLUSION|FOTO DE EVIDENCIA|NOTICIAS)"
    r"\s*$"
)


def _prose_answer_valid(
    text: str | None, *, max_chars: int = 2000, expected_language: str = "es"
) -> bool:
    """La respuesta visible es prosa, no el volcado del contrato.

    Rechaza IDs de cita, etiquetas de seccion, URLs y volcados en OTRO idioma
    (i18n B: ingles cuando se genera en espanol, espanol cuando se genera en
    ingles): cualquiera de esos significa que el modelo pego estructura
    interna en la respuesta que lee el usuario.
    """
    body = (text or "").strip()
    if not body or len(body) > max_chars:
        return False
    if _CITATION_ID_RE.search(body):
        return False
    if len(_SECTION_LABEL_DUMP_RE.findall(body)) >= 2:
        return False
    if re.search(r"https?://|www[.]", body, re.IGNORECASE):
        return False
    if expected_language == "en":
        hits, total = _spanish_hits(body)
    else:
        hits, total = _english_hits(body)
    if hits >= 2 and hits / max(total, 1) >= 0.15:
        return False
    return True



_CURRENCY_WORDS = r"(?:USD|EUR|GBP|JPY|CHF|dólares?|dolares?|euros?|libras?)"
_MONEY_NEAR_RE = re.compile(
    rf"(?:[$€£]\s*\d|\d[\d.,]*(?:\s+\w+){{0,2}}\s*(?:[$€£]|{_CURRENCY_WORDS}\b)|\b{_CURRENCY_WORDS}\s*\d)",
    re.IGNORECASE,
)
_PORTFOLIO_CLAIM_RE = re.compile(
    r"(?i)\b(?:tu|mi|su|vuestra|nuestra)\s+"
    r"(?:rentabilidad|rendimiento|cartera|posici[oó]n|posiciones|inversi[oó]n)\b"
)

# Alcance de entrada: conceptos, charla y conocimiento empresarial pueden
# llegar al modelo. Cartera privada y ordenes no se deducen de esa ruta.
_FIN_WORDS_RE = re.compile(
    r"(?i)\b(acci[oó]n(?:es)?|cartera|portfolio|posici[oó]n(?:es)?|rentabilidad|"
    r"rendimiento|cotiza\w*|cotizaci[oó]n|precio|bolsa|burs[aá]til\w*|dividendos?|"
    r"inversi[oó]n(?:es)?|invertir|ganancias?|p[eé]rdidas?|beneficios?|"
    r"capitalizaci[oó]n|valoraci[oó]n|stock|shares?|earnings|etf|ebitda|"
    r"ingresos?|facturaci[oó]n|ventas?|revenue|sales|empleados?|employees?|headcount|"
    r"workforce|personnel|staffing|deuda|debt|flujo\s+de\s+caja|cash\s+flow|cuota\s+de\s+mercado|"
    r"market\s+share|sube|suben|baja|bajan|cae|caen|duplic\w*|tripl\w*|vale|valen)\b"
    r"|[$€£%]"
)
# Tickers: 2-5 mayusculas, SENSIBLE a mayusculas (el flag (?i) de arriba no
# aplica aqui), salvo siglas conceptuales y de divisa.
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
_FIN_ACRONYMS = frozenset({"PER", "ETF", "ROE", "ROA", "ROIC", "EPS", "FCF", "EBITDA", "PEG", "CAGR"})
_CONCEPT_ACRONYMS = frozenset({"PER", "ETF", "ROE", "ROA", "ROIC", "EPS", "FCF", "EBITDA", "PEG", "IPO", "CAGR", "OK"})


def _has_ticker(text: str) -> bool:
    return any(t not in _CONCEPT_ACRONYMS for t in _TICKER_RE.findall(text))


class _FinScope:
    @staticmethod
    def search(text: str) -> bool:
        return (
            bool(_FIN_WORDS_RE.search(text))
            or (
                bool(re.search(r"(?i)\bplantilla\b", text))
                and not re.search(r"(?i)\b(correo|email|e-mail|carta|curr[ií]culum|documento)\b", text)
            )
            or _has_ticker(text)
            or any(t in _FIN_ACRONYMS for t in _TICKER_RE.findall(text))
        )


_FIN_SCOPE_RE = _FinScope
# Solo una peticion COMPLETA de concepto conocido entra al generador de
# definiciones. Un prefijo "explica" no basta: "de apple", fechas, posiciones
# personales o cualquier resto no consumido queda en consulta especifica.
_CONCEPT_TERM = (
    r"(?:PER|ETF|ROE|ROA|ROIC|EPS|FCF|EBITDA|PEG|IPO|CAGR|"
    r"ingresos?|revenue|ventas?|sales|facturaci[oó]n|deuda|debt|"
    r"dividendo|dividendos|rentabilidad|rendimiento|inversi[oó]n|"
    r"precio(?: de mercado)?|cotizaci[oó]n(?: burs[aá]til)?|"
    r"flujo de caja|cash flow|market cap|capitalizaci[oó]n|"
    r"margen|beneficios?|earnings|employees?|empleados?|"
    r"cuota de mercado|market share)"
)
_CONCEPT_Q_RE = re.compile(
    r"(?i)\s*[¿¡]?\s*(?:"
    r"(?:qu[eé] (?:es|son|significa)|c[oó]mo (?:funciona|funcionan|se calcula)|"
    r"expl[ií]ca(?:me)?|define|para qu[eé] sirve|what (?:is|are)|explain)\s+"
    r"(?:(?:el|la|los|las|un|una|the|an|a)\s+)?" + _CONCEPT_TERM +
    r"|how does (?:(?:the|an|a)\s+)?" + _CONCEPT_TERM + r" work)"
    r"(?:\s+(?:en general|de una empresa|de un negocio|in general|of a company))?\s*[?!.]*\s*"
)
# "su/sus" es ambiguo: en "su cartera" es el usuario (usted), en "sus cartas"
# (las de Buffett) es un tercero. Solo cuenta como ambito privado cuando
# modifica a un sustantivo de datos privados; lo demas pasa al generador.
# Marcas de magnitud financiera: su presencia en una clausula convierte sus
# cifras en datos que exigen aproximador; sin ellas, "tres ideas" es un
# recuento del propio texto, no un dato empresarial.
_MAGNITUDE_MARKER_RE = re.compile(
    r"[$€£%]|\b(?:USD|EUR|GBP|JPY|d[oó]lares?|dolares?|euros?|libras?|"
    r"mill[oó]n|millones|billones?|mil|acciones|empleados?|por\s+ciento)\b",
    re.IGNORECASE,
)

_PERSONAL_RE = re.compile(
    r"(?i)\b(mi|mis|tu|tus|nuestr[oa]s?|vuestr[oa]s?|m[ií]o|m[ií]a)\b"
    r"|\bsu(?:s)?\s+(?:cartera|posici[oó]n(?:es)?|cuenta|inversi[oó]n(?:es)?|"
    r"acciones|rentabilidad|patrimonio|beneficios?)\b"
)
_NUMBER_WORD_RE = re.compile(
    r"(?i)\b(cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|"
    r"catorce|quince|veinte\w*|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|"
    r"noventa|cien|ciento|doscientos|trescientos|cuatrocientos|quinientos|"
    r"seiscientos|setecientos|ochocientos|novecientos|mil|mill[oó]n|millones|"
    r"billones?|por\s+ciento|porcentaje|duplic\w*|tripl\w*|doblad\w*)\b"
)
# Prueba real 2026-11-03 (Go, preguntas de concepto): 8 de 8 respuestas
# educativas correctas caían al degradado por recuentos («dos formas»),
# ejemplos («un PER de 15») o «según el sector». Lo que sigue protegido: una
# cantidad con dinero o escala (millones, €, $) sin aproximador.
_SMALL_COUNT_RE = re.compile(r"(?i)uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez")
_COUNT_IS_MAGNITUDE_RE = re.compile(
    r"(?i)\s*(?:[$€£%]|mil\b|mill[oó]n|millones|billones?|d[oó]lares?|euros?|libras?|usd|eur\b|"
    r"por\s+ciento|veces\b|puntos?\b|empleados?|acciones\b)"
)
_MONEY_OR_SCALE_AFTER_RE = re.compile(
    r"(?i)\s*(?:[.,]\d+\s*)?(?:[$€£%]|por\s+ciento|mil\b|mill[oó]n|millones|billones?|d[oó]lares?|euros?|libras?|usd|eur\b)"
)
_ILLUSTRATIVE_PREFIX_RE = re.compile(
    r"(?i)\b(?:un|una)\s+(?:[a-záéíóúñ]+\s+){1,2}(?:de|del)\s+$"
)
_HYPOTHETICAL_RE = re.compile(
    r"(?i)\b(?:por\s+ejemplo|pongamos(?:\s+que)?|imagina(?:\s+que)?|supongamos(?:\s+que)?|sup[oó]n(?:\s+que)?|"
    r"si\s+(?:una|un)\s+(?:acci[oó]n|empresa|fondo|valor)"
    r"|si\s+(?:hab[ií]a|hay|tienes|tuvieras|compras|compraras|estimas|inviertes|invirtieras|ahorras|pagas|"
    r"cotiza|cotizara|vale|valiera|cae|cayera|sube|subiera|baja|bajara))\b"
)
_CONDITIONAL_SEGUN_RE = re.compile(
    r"(?i)\bseg[uú]n\s+(?:"
    r"(?:c[oó]mo|qu[eé]|cu[aá]ndo|cu[aá]nt[oa]s?|si|d[oó]nde|cada)\b"
    r"|(?:(?:el|la|los|las|tu|tus|su|sus)\s+)?(?:sector(?:es)?|ratios?|casos?|periodos?|per[ií]odos?|plazos?|"
    r"horizonte|perfil|objetivos?|tipos?|negocios?|pa[ií]s(?:es)?|momento|situaci[oó]n|circunstancias|"
    r"necesidades|tolerancia|edad|fiscalidad|estrategia|uso|criterios?|m[eé]tricas?|industria)\b)"
)
_POSTFIX_APPROX_RE = re.compile(
    r"(?i)\s*(?:%|por\s+ciento)?\s*(?:[-–]\s*\d[\d.,]*\s*(?:%|por\s+ciento)?\s*)?"
    r"(?:o\s+m[aá]s|o\s+menos|como\s+m[ií]nimo|como\s+poco|o\s+as[ií]|aproximadamente)\b"
)
_FUND_RE = re.compile(r"(?i)\b(?:fondos?|etfs?|[ií]ndices?|indexad\w*)\b")


def _general_scope(question: str) -> str:
    """Clasifica charla, concepto, conocimiento empresarial o contexto privado."""
    q = (question or "").strip()
    if not _FIN_SCOPE_RE.search(q):
        return "ordinary"
    if _CONCEPT_Q_RE.fullmatch(q):
        return "concept"
    # Datos privados y ordenes no se deducen del conocimiento del modelo.
    if _PERSONAL_RE.search(q) or re.search(
        r"(?i)\b(my|your|our|buy|sell|compra|vende|ejecuta)\b", q
    ):
        return "abstain"
    return "inferred"


def _clock_context(question: str) -> dict | None:
    """Runtime clock, not model memory. Only attach a requested known zone."""
    from zoneinfo import ZoneInfo

    if re.search(r"(?i)\bhora\b", question) and re.search(r"(?i)\b(?:Tokio|Tokyo)\b", question):
        return {"place": "Tokio", "timezone": "Asia/Tokyo",
                "local_time": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="minutes")}
    return None


def _general_quantity_context(text: str) -> bool:
    # Un porcentaje de bateria no es un dato financiero. Moneda junto a una
    # cantidad si lo es, incluso cuando falta un nombre de empresa.
    return bool(_FIN_SCOPE_RE.search(re.sub(r"[$€£%]", "", text)) or _MONEY_NEAR_RE.search(text))


def _plain(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", (text or "").lower())
        if not unicodedata.combining(c)
    )


_INVESTOR_NAME_LIST = ("buffett", "munger", "graham", "marks", "klarman", "lynch", "fisher", "templeton")
_INVESTOR_NAMES = r"(?:" + "|".join(_INVESTOR_NAME_LIST) + r")"
_REPORTING_VERBS = (
    r"(?:dicho|dijo|dice|exige|exigia|insiste|insistia|recomienda|aconseja|considera|consideraba|"
    r"prefiere|defiende|ensena|explica|afirma|reiterado|reitera|enfatiza|enfatizado|enfatizo|subraya|"
    r"subrayado|subrayo|senala|senalado|senalo|sostiene|sostenido|sostuvo|describe|descrito|describio|"
    r"destaca|destacado|resalta|advierte|advertido|advirtio|cree|creia|piensa|pensaba|plantea|"
    r"argumenta|comenta|escribe|escribio|sugiere|opina|asegura|propone|recuerda|insistido|afirmado|"
    r"afirmo|explicado|explico|defendido|defendio|recomendado|recomendo|aconsejado|aconsejo|"
    r"predica|practica|aplica|busca|advierte|valora|entiende|concibe|define|definio)"
)


def _reports_named_investor_opinion(text: str) -> bool:
    """True si la prosa pone opiniones en boca de un inversor famoso.

    Sin fragmentos de ese autor en el contexto no hay fuente para decir "Buffett
    ha reiterado/enfatiza/describe...". Se normalizan los acentos y se admiten
    hasta 50 caracteres (sin cortar la frase) entre el nombre y el verbo
    ("Buffett ha reiterado en varias ocasiones que"). Tambien se caza el
    pronombre de la frase siguiente ("Él lo describe como", "Buffett enfatiza").
    """
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    if re.search(rf"\b{_INVESTOR_NAMES}\b[^.!?\n]{{0,50}}?\b{_REPORTING_VERBS}\b", plain):
        return True
    if re.search(rf"\b{_INVESTOR_NAMES}\b", plain) and re.search(
        rf"(?:^|[.!?]\s+|\n)(?:el|este inversor|este autor|el inversor)\s+(?:lo\s+|la\s+|nos\s+)?{_REPORTING_VERBS}\b",
        plain,
    ):
        return True
    return False


def _number_key(token: str) -> str:
    """Forma canonica de una cifra para compararla con el fragmento: sin
    separadores de miles ni signo ("13,6" y "13.6" son la misma cifra)."""
    digits = re.sub(r"[^\d.,]", "", token).strip(".,")
    return digits.replace(",", ".")


def grounded_numbers_in(texts: list[str]) -> frozenset[str]:
    """Cifras literales de los fragmentos de doctrina (mas de un digito o con
    decimales: un "3" suelto no legitima nada)."""
    found = set()
    for text in texts:
        for match in re.finditer(r"\d[\d.,]*\d|\d", text or ""):
            key = _number_key(match.group())
            if len(key.replace(".", "")) >= 2:
                found.add(key)
    return frozenset(found)


_SECRET_RE = re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{16,}|ghp_[a-z0-9]{20,}|akia[0-9a-z]{12,}|bearer\s+[a-z0-9._-]{20,})")
_SECTION_LINK_RE = re.compile(r"(?i)https?://|www[.]|<\s*(?:img|a|script|iframe)\b|!?\[[^\]]*\]\([^)]*\)")
_CREDENTIAL_PAIR_RE = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[=:]\s*\S+")
FALLBACK_DETAIL_MAX = 200


# Proveedor caído (402, 429, plazo agotado o caída): qué falta y por qué, sin
# cifras. Benchmark Cerebro 2026-11-08 (pasada 2, clave de Go en 402): 11
# preguntas sin ticker acabaron en «No puedo responderte con fuentes ahora
# mismo; prueba de nuevo…», que no dice qué falta ni deja nada útil.
_MODEL_DOWN_MOTIVES = {
    "budget": ("se ha alcanzado el tope de gasto en modelos de la app",
               "the app's model spending cap has been reached"),
    "limit": ("el proveedor del modelo no tiene saldo o ha llegado a su límite de uso",
              "the model provider is out of credit or has hit its usage limit"),
    "rejected": ("la redacción del modelo no superó el control de fuentes",
                 "the model's write-up did not pass the source check"),
    "timeout": ("el modelo no respondió a tiempo", "the model did not answer in time"),
    "down": ("el proveedor del modelo no responde", "the model provider is not answering"),
}

_GUARD_MISSING = (
    (r"cartera", "tus posiciones guardadas en el contexto de esta pregunta (motivo: la respuesta hablaba de tu cartera sin tenerlas)",
     "your saved positions in this question's context (reason: the answer talked about your portfolio without them)"),
    (r"inversor|doctrina", "un texto de ese inversor en la biblioteca o su 13F (motivo: la respuesta le atribuía una opinión sin fragmento suyo)",
     "a text by that investor in the library or their 13F (reason: the answer attributed an opinion without an excerpt of theirs)"),
    (r"fuente|seg[uú]n|dominio|enlace",
     "la fuente documental que citaba la respuesta (motivo: no está entre los datos de la app)",
     "the document the answer cited (reason: it is not in the app's data)"),
    (r"cifra|decimal|cantidad|n[uú]mero",
     "la fuente de las cifras exactas que daba la respuesta (motivo: no están en los datos de la app para esta pregunta)",
     "a source for the exact figures in the answer (reason: they are not in the app's data for this question)"),
)


def _missing_from_guard(reason: str | None, lang: str = "es") -> str | None:
    """Qué dato falta, en palabras del usuario, a partir del motivo del guard.

    Nunca repite el motivo literal: puede llevar cifras del candidato
    rechazado («cifra con decimales no aproximada: 12,34») y esas cifras no
    tienen fuente.
    """
    if not reason or re.search(r"vac[ií]o|empty|language|idioma", reason, re.I):
        # Respuesta vacía o en otro idioma: fallo del proveedor, no un dato que falte.
        return None
    for pattern, es, en in _GUARD_MISSING:
        if re.search(pattern, reason, re.I):
            return en if lang == "en" else es
    return (
        "a source in the app's data for that answer (reason: the source check rejected it)"
        if lang == "en"
        else "una fuente en los datos de la app para esa respuesta (motivo: el control de fuentes la rechazó)"
    )


def _model_down_kind(exc: BaseException | None, reason: str) -> str:
    """Clase del fallo del modelo para el texto de «proveedor caído».

    Recorre la cadena de la excepción (``__cause__``/``__context__``) y la
    etiqueta del primario que deja ChatFallbackProvider («backup chain
    exhausted after primary go:modelo:ProviderHTTPError402»). Determinista.
    """
    if reason == "budget_exhausted":
        return "budget"
    if reason == "ungrounded":
        return "rejected"
    from app.llm.errors import ProviderHTTPError, ProviderTransportError

    chain: list[BaseException] = []
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    texts = " ".join(str(item) for item in chain)
    if re.search(r"after primary \S*:(?:ProviderResponseError|ValueError)\b", texts):
        return "rejected"
    if reason == "quota" or re.search(r"HTTPError(?:402|429)\b|:cooling\b|HTTP (?:402|429)\b", texts) or any(
        isinstance(item, ProviderHTTPError) and item.status_code in {402, 429} for item in chain
    ):
        return "limit"
    if re.search(r"Candidate rejected", texts):
        return "rejected"
    if re.search(r":timeout\b|timed? ?out", texts, re.I) or any(
        isinstance(item, (ProviderTransportError, TimeoutError)) for item in chain
    ):
        return "timeout"
    return "down"


def _fallback_detail(exc: BaseException) -> str:
    """Mensaje del fallo para la traza (sin secretos, acotado).

    Prueba real 2026-11-03: una de cada ~7 respuestas caia al degradado y la
    traza solo guardaba el tipo («ValueError»), sin forma de saber cual de
    las ~10 validaciones la habia tirado.
    """
    text = " ".join(str(exc).split()) or type(exc).__name__
    text = _SECRET_RE.sub("[redactado]", text)
    text = _CREDENTIAL_PAIR_RE.sub(lambda m: f"{m.group(1)}=[redactado]", text)
    return text[:FALLBACK_DETAIL_MAX]


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _flatten_text(v)]
    if isinstance(value, (list, tuple)):
        return [t for v in value for t in _flatten_text(v)]
    return []


def _reject_untrusted_output(payload: dict, baseline: Any, question: str) -> None:
    """Defensa contra inyeccion indirecta: lo que un modelo obediente a un texto
    plantado en noticias/documentos NO debe llegar al usuario. Rechaza (y asi se
    cae al baseline determinista) secretos, enlaces/HTML en secciones y cifras
    de la prosa que no estan en la pregunta ni en el contexto recuperado."""
    answer = str(payload.get("answer") or "")
    bodies = [str(s.get("body") or "") for s in payload.get("sections", []) if isinstance(s, dict)]
    for text in [answer, *bodies]:
        if _SECRET_RE.search(text):
            raise ValueError("Secret-like token in model output")
    if any(_SECTION_LINK_RE.search(body) for body in bodies):
        raise ValueError("External link or HTML in section body")
    context = [question or "", *_flatten_text([s.model_dump() for s in baseline.sections]),
               *_flatten_text(baseline.sources)]
    missing = _ungrounded_figures(answer, context)
    if missing:
        raise ValueError(f"Ungrounded number in model answer: {', '.join(missing[:5])}")


def _figure_readings(token: str) -> list[tuple[float, int]]:
    """Lecturas (valor, decimales escritos) de una cifra en formato ES o EN."""
    token = token.strip(".,")
    candidates = {token.replace(",", ""), token.replace(".", "").replace(",", ".")}
    if token.count(",") == 1 and "." not in token:
        candidates.add(token.replace(",", "."))
    out = []
    for cand in candidates:
        try:
            value = float(cand)
        except ValueError:
            continue
        out.append((value, len(cand.split(".", 1)[1]) if "." in cand else 0))
    return out


def _ungrounded_figures(answer: str, context: list[str]) -> list[str]:
    """Cifras de la prosa que no están en el contexto ni tal cual ni reescaladas.

    El modelo escribe «51.200 millones de dólares» donde el dato guardado es
    51200000000 y la respuesta de datos dice «51,2 mil millones»: es la misma
    cifra. Prueba real 2026-11-03: comparar solo el texto tiraba todas las
    respuestas sobre empresas. Vale el mismo número en miles, millones o miles
    de millones (o ratio ↔ %), redondeado a los decimales que se escriben
    (o con un 0,5 % de margen, como el validador del equipo de expertos).
    """
    known = grounded_numbers_in(context)
    values = [
        abs(value)
        for text in context
        for match in re.finditer(r"\d[\d.,]*\d|\d", text or "")
        for value, _ in _figure_readings(match.group())
    ]
    missing = []
    for match in re.finditer(r"\d[\d.,]*\d|\d", answer or ""):
        token = match.group()
        key = _number_key(token)
        if len(key.replace(".", "")) < 2 or key in known:
            continue
        if not any(
            abs(written - data * scale) <= max(0.5 * 10 ** -decimals + 1e-9, 0.005 * data * scale)
            for written, decimals in _figure_readings(token)
            for data in values
            for scale in ((1, 1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9, 100) if data <= 1.5 else (1, 1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9))
        ):
            missing.append(token)
    return missing


# --- Validacion EN (i18n B) ------------------------------------------------
# Espejo en ingles de los controles de prosa libre: misma regla (cada
# clausula con cifra exige aproximador propio, nada de atribuciones a fuentes
# no aportadas ni de claims de cartera sin posiciones en el prompt), con los
# marcadores en ingles. El camino espanol de _inferred_general_text_valid no
# se toca.
_EN_PORTFOLIO_CLAIM_RE = re.compile(
    r"(?i)\b(?:my|your|our)\s+(?:portfolio|positions?|holdings?|returns?|investments?|performance)\b"
)
_EN_ATTRIBUTION_RE = re.compile(
    r"(?i)\b(?:official(?:ly)?|reported|annual report|10-K|10-Q|"
    r"filed|filing|stated|announced|press release)\b"
)
_EN_ACCORDING_TO_RE = re.compile(r"(?i)\baccording to\b")
_EN_APPROXIMATE_RE = re.compile(
    r"(?i)(?:roughly|about|around|approximately|approx\w*|estimated?\w*|"
    r"some|over|under|more than|less than|fewer than|nearly|almost|"
    r"on the order of|tens of|hundreds of|thousands of|close to|up to|"
    r"between)\s+(?:(?:the|a|an|of)\s+){0,2}$"
)
_EN_NUMBER_RE = re.compile(r"\d[\d.,]*")
_EN_SCALE_WORD_RE = re.compile(r"(?i)(?:thousand|million|billion|trillion)")


_LIST_MARKER_RE = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+")


def _without_list_markers(text: str) -> str:
    """Quita el número de cada punto de una lista numerada («1. », «2) »).

    Ese número ordena la lista, no es una cifra: antes «1. Distingue…» hacía
    que una respuesta general sin ninguna cifra se tirase como inventada.
    """
    return _LIST_MARKER_RE.sub("", text)


def _inferred_general_text_valid_en(
    text: str, *, allow_placeholders: bool = False, quantitative: bool = True,
    allow_named_attribution: bool = False,
    allowed_investors: frozenset[str] = frozenset(),
    grounded_numbers: frozenset[str] = frozenset(),
    allow_portfolio_claims: bool = False,
) -> bool:
    """Version EN de la validacion de prosa libre (ver el espejo ES)."""
    if len(text) > 8000 or not text.strip() or re.search(r"https?://|www[.]|\bdoi:", text, re.I):
        return False
    if _SECRET_RE.search(text):
        return False
    if re.search(
        r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"(?:com|org|net|io|ai|es|gov|edu|co|uk|de|fr|app|dev|info|biz|eu)\b(?:/[^\s]*)?",
        text,
    ):
        return False
    if allow_placeholders:
        def placeholder(match: re.Match[str]) -> str:
            content = match.group(1).strip()
            if content.upper() in {"INFERIDO", "SIN_DATOS", "OFICIAL"}:
                return match.group()
            if _FIN_WORDS_RE.search(content) or re.search(r"\d", content):
                return match.group()
            return ""
        text = re.sub(r"\[([^\]]+)\]", placeholder, text)
    if re.search(r"\[[^\]]+\]", text):
        return False
    if _EN_ATTRIBUTION_RE.search(text):
        return False
    # «according to X» se trata como el «segun X» espanol: solo con doctrina
    # aportada (allow_named_attribution) y nombre autorizado.
    if _EN_ACCORDING_TO_RE.search(text) and not allow_named_attribution:
        return False
    if _reports_named_investor_opinion(text):
        if not allow_named_attribution:
            return False
        plain = "".join(
            c for c in unicodedata.normalize("NFKD", text.lower())
            if not unicodedata.combining(c)
        )
        named = {
            name for name in _INVESTOR_NAME_LIST
            if re.search(rf"\b{name}\b", plain)
        }
        if not named <= allowed_investors:
            return False
    # Una cifra contable con decimales no la convierte en estimacion un "about".
    if any(
        _number_key(m.group()) not in grounded_numbers
        for m in re.finditer(r"\d[\d.,]*[.,]\d{2}(?!\d)", text)
    ):
        return False
    hits, total = _spanish_hits(text)
    if hits >= 2 and hits / max(total, 1) >= 0.15:
        return False
    if _EN_PORTFOLIO_CLAIM_RE.search(text) and not allow_portfolio_claims:
        return False
    if not quantitative:
        return True
    clauses = re.split(r"[;!?\n]|(?<!\d)[.](?!\d)|\b(?:and|but)\b", _without_list_markers(text))
    for clause in clauses:
        if allow_named_attribution and not _MAGNITUDE_MARKER_RE.search(clause):
            continue
        for match in _EN_NUMBER_RE.finditer(clause):
            token = match.group().strip().rstrip(".,")
            if grounded_numbers and _number_key(token) in grounded_numbers:
                continue
            prefix = clause[max(0, match.start() - 90):match.start()]
            # Un año aislado en contexto de fecha no es una cifra empresarial.
            if re.fullmatch(r"(?:19|20)\d{2}", token) and re.search(
                r"(?i)(?:\bin\b|\bof\b|\bfor\b|\bfiscal\b|\byear\b|\bfrom\b|\bto\b|"
                r"(?:19|20)\d{2}\s*(?:[-–]|and))\s*$", prefix,
            ):
                continue
            # Unidad de escala que sigue a una cifra ya aproximada (8000 million).
            if _EN_SCALE_WORD_RE.fullmatch(token) and re.search(
                r"(?:\d[\d.,]*| thousand| million| billion)\s*$", prefix, re.I
            ):
                continue
            if not _EN_APPROXIMATE_RE.search(prefix):
                previous = clause[:match.start()]
                range_start = re.search(r"\d[\d.,]*%?\s*(?:-|–|to|and)\s*$", previous)
                if range_start is None or not _EN_APPROXIMATE_RE.search(previous[:range_start.start()]):
                    return False
    return True


def _general_text_rejection(
    text: str, *, allow_placeholders: bool = False, quantitative: bool = True,
    allow_named_attribution: bool = False,
    allowed_investors: frozenset[str] = frozenset(),
    grounded_numbers: frozenset[str] = frozenset(),
    allow_portfolio_claims: bool = False,
) -> str | None:
    """Motivo por el que se rechaza la prosa libre (None = valida).

    Prosa natural: no atribuciones/citas falsas, cifras aproximadas locales.

    ``allow_portfolio_claims``: solo la ruta mixta carta + cartera, que pasa
    las posiciones guardadas al prompt, puede hablar de la cartera del usuario.

    ``grounded_numbers``: cifras que aparecen literalmente en los fragmentos de
    doctrina que se le pasaron (p. ej. "+202%" de una carta de Numantia). Esas
    no son inventadas y no necesitan aproximador.

    Con doctrina recuperada (cartas de la biblioteca) el modelo SI puede decir
    "en sus cartas, Buffett...": la atribucion es a fragmentos que se le
    pasaron. Lo que sigue prohibido es invocar informes oficiales, fuentes o
    datos que nadie le ha dado.
    """
    if len(text) > 8000 or not text.strip() or re.search(r"https?://|www[.]|\bdoi:", text, re.I):
        return "texto vacío, demasiado largo o con enlace"
    if _SECRET_RE.search(text):
        return "token con forma de secreto"
    if re.search(
        r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"(?:com|org|net|io|ai|es|gov|edu|co|uk|de|fr|app|dev|info|biz|eu)\b(?:/[^\s]*)?",
        text,
    ):
        return "dominio web en el texto"
    if allow_placeholders:
        def placeholder(match: re.Match[str]) -> str:
            content = match.group(1).strip()
            human = re.sub(r"(?i)\b\d\s*[-–]\s*\d\s+frases\b", "frases", content)
            human = re.sub(r"(?i)acci[oó]n o siguiente paso", "siguiente paso", human)
            if content.upper() in {"INFERIDO", "SIN_DATOS", "OFICIAL"}:
                return match.group()
            if _FIN_WORDS_RE.search(human) or _NUMBER_WORD_RE.search(human) or re.search(r"\d", human):
                return match.group()
            if re.match(r"[a-z_]+:", human, re.I) and not re.match(
                r"(?i)(?:motivo|asunto|nombre|cargo|correo|telefono):", human,
            ):
                return match.group()
            return ""
        text = re.sub(r"\[([^\]]+)\]", placeholder, text)
    if re.search(r"\[[^\]]+\]", text):
        return "marcador entre corchetes"
    attribution = re.sub(r"(?i)seg[uú]n lo que (?:s[eé]|recuerdo)", "", text)
    # Una recomendacion sin cantidades no atribuye datos a esa fuente.
    attribution = re.sub(
        r"(?i)(?:consultar|verificar|mirar|revisar)[^.!?\d]*(?:informe anual|annual report|resultados oficiales|cifras oficiales)",
        "", attribution,
    )
    if re.search(
        r"(?i)\b(oficial(?:es|mente)?|reportad[oa]s?|reported|official|according to|"
        r"informe anual|annual report|present[oó]|declar[oó]|public[oó]|"
        r"seg[uú]n\s+(?:(?:su|el|la|los|las|un|una)\s+)?"
        r"(?:informe|fuentes?|documentos?|datos|comunicado|reporte|balance|estudio|sec))\b", attribution
    ):
        return "atribución a una fuente oficial no dada"
    attribution = re.sub(r"(?i)seg[uú]n (?:la [eé]poca|normativa contable)\b", "", attribution)
    # «según el sector», «según el periodo que mires», «según cómo…»: «según»
    # como «dependiendo de», no como fuente (prueba real 2026-11-03: tiraba
    # respuestas educativas correctas).
    attribution = _CONDITIONAL_SEGUN_RE.sub("", attribution)
    if not allow_named_attribution and re.search(r"(?i)\bseg[uú]n\b", attribution):
        return "«según» sin fuente dada"
    if _reports_named_investor_opinion(attribution):
        if not allow_named_attribution:
            return "opinión de un inversor sin doctrina"
        # Atribuir a un inversor concreto exige un fragmento DE ESE autor en
        # el contexto: con doctrina de otros (p. ej. cartas de un fondo) no
        # se puede poner la opinion en boca de Buffett.
        plain = "".join(
            c for c in unicodedata.normalize("NFKD", attribution.lower())
            if not unicodedata.combining(c)
        )
        named = {
            name for name in _INVESTOR_NAME_LIST
            if re.search(rf"\b{name}\b", plain)
        }
        if not named <= allowed_investors:
            return "inversor que no está en la doctrina recuperada"
    # Aproximar no convierte una cifra contable con decimales en estimacion.
    bad_decimals = [
        m.group() for m in re.finditer(r"\d[\d.,]*[.,]\d{2}(?!\d)", text)
        if _number_key(m.group()) not in grounded_numbers
    ]
    if bad_decimals:
        return "cifra con decimales no aproximada: " + bad_decimals[0]
    hits, total = _english_hits(text)
    if hits >= 2 and hits / max(total, 1) >= 0.15:
        return "texto en inglés"
    if not allow_portfolio_claims and any(
        not (m.group().lower().startswith("su ") and _FUND_RE.search(text))
        for m in _PORTFOLIO_CLAIM_RE.finditer(text)
    ):
        # «las empresas de su cartera» hablando de un fondo o ETF es la cartera
        # del fondo, no la del usuario.
        return "afirmación sobre la cartera del usuario"
    if not quantitative:
        return None
    # Cada clausula con cantidad requiere su propio aproximador. Una frase
    # previa o una cantidad marcada no legitima otra cantidad exacta.
    # Cláusulas con la frase a la que pertenecen: un ejemplo («si había 100
    # acciones y se amortizan 10») sigue siéndolo en su segunda cláusula.
    clauses = [
        (clause, sentence)
        for sentence in re.split(r"[!?\n]|(?<!\d)[.](?!\d)", _without_list_markers(text))
        for clause in re.split(r";|\b(?:y(?!\s*(?:el\s+)?\d)|pero|and|but)\b", sentence)
    ]
    number = re.compile(r"\d[\d.,]*|" + _NUMBER_WORD_RE.pattern.replace("(?i)", ""), re.I)
    approximate = re.compile(
        r"(?i)(?:unos?|unas?|aproximadamente|aproximad\w*|estimad\w*|"
        r"estimaci[oó]n|alrededor de(?:l)?|en torno al?|cerca de(?:l)?|del orden de(?:l)?|"
        r"en el orden de(?:l)?|algo m[aá]s de(?:l)?|m[aá]s de(?:l)?|menos de(?:l)?|"
        r"por encima de(?:l)?|por debajo de(?:l)?|"
        r"superan?(?: holgadamente| con holgura)?|rondar[ií]a|"
        r"rondar[ií]an|ronda|rondan|rondaba|rondaban|cercan[oa]s? al?|decenas de|cientos de|miles de|entre)\s+(?:(?:el|la|los|las|de|del|un|una)\s+){0,3}$"
    )
    for clause, sentence in clauses:
        if allow_named_attribution and not _MAGNITUDE_MARKER_RE.search(clause):
            # Respuesta de doctrina: los recuentos del propio texto ("tres
            # ideas", "dos condiciones") no son cifras empresariales. Las
            # clausulas con magnitud financiera siguen exigiendo aproximador.
            continue
        for match in number.finditer(clause):
            token = match.group().strip().rstrip(".,")
            if grounded_numbers and _number_key(token) in grounded_numbers:
                continue
            after = clause[match.end():]
            if token.lower() == "porcentaje":
                continue  # la palabra «porcentaje» no es una cantidad
            if (
                _SMALL_COUNT_RE.fullmatch(token)
                and re.match(r"\s+[a-záéíóúñ]", after, re.I)
                and not _COUNT_IS_MAGNITUDE_RE.match(after)
            ):
                continue  # recuento («dos formas», «los dos meses»), no una cifra
            if not _MONEY_OR_SCALE_AFTER_RE.match(after) and (
                _ILLUSTRATIVE_PREFIX_RE.search(clause[max(0, match.start() - 60):match.start()])
                or _HYPOTHETICAL_RE.search(sentence)
            ):
                continue  # ejemplo («un PER de 15», «por ejemplo, si vale 100»), sin dinero ni escala
            if _POSTFIX_APPROX_RE.match(after):
                continue  # «un 40-50 % o más», «20 como mínimo»
            if re.search(r"[×*/]\s*$|\bx\s*$", clause[:match.start()]):
                continue  # operando de una fórmula («… × 100»)
            # Periodos/fechas no son una cifra empresarial. No convertirlos
            # en fuente: solo se permite el formato de fecha o año aislado.
            prefix = clause[max(0, match.start() - 90):match.start()]
            if token.lower() == "uno" and re.search(r"(?i)\bcada\s+$", prefix):
                continue
            if (
                re.fullmatch(r"(?:19|20)\d{2}", token)
                and prefix.rstrip().endswith("(")
                and re.match(r"[-–](?:19|20)\d{2}\)", clause[match.end():])
            ):
                continue
            date_not_quantity = not re.match(
                r"(?i)\s*(?:empleados?|millones?|mil\b|d[oó]lares?|euros?|%|acciones?|personas?)",
                clause[match.end():],
            )
            if date_not_quantity and re.fullmatch(r"(?:19|20)\d{2}", token) and re.search(
                r"(?i)(?:\b(?:en|de|del|para|hacia|desde|hasta|fiscal|ejercicio|a[nñ]o|periodo)|"
                r"\b(?:19|20)\d{2}\s*(?:[-–]|y))\s*(?:el\s+)?$", prefix,
            ):
                continue
            # Unidad de escala que sigue a una cifra ya aproximada, no otra
            # cantidad independiente (8000 millones).
            if re.fullmatch(r"(?i)(?:mil|mill[oó]n|millones|billones?)", token) and re.search(r"(?:\d[\d.,]*|\bmil|\bmill[oó]n|\bmillones)\s*$", prefix, re.I):
                continue
            if not approximate.search(prefix):
                # Rango: el segundo extremo comparte aproximador SOLO cuando
                # lo une 'a'/guion, no una nueva afirmacion.
                previous = clause[:match.start()]
                range_start = re.search(r"\d[\d.,]*%?\s*(?:-|–|a|o|y(?:\s+el)?)\s*$", previous)
                if range_start is None or not approximate.search(previous[:range_start.start()]):
                    return f"cifra exacta sin aproximador: {token}"
    return None

def _inferred_general_text_valid(text: str, **kwargs: Any) -> bool:
    """Prosa natural valida (ver ``_general_text_rejection`` para el motivo)."""
    return _general_text_rejection(text, **kwargs) is None


def _general_rejection(text: str, *, lang: str | None, **kwargs: Any) -> str | None:
    """Motivo de rechazo de la prosa libre en el idioma de la respuesta."""
    if lang == "en":
        return None if _inferred_general_text_valid_en(text, **kwargs) else "prosa en inglés no válida"
    return _general_text_rejection(text, **kwargs)


_HISTORY_TURNS = 4
_HISTORY_TURN_CHARS = 400
_HISTORY_TOTAL_CHARS = 1600


# Fragmentos de las respuestas deterministas con datos privados de cartera
# (recuento, ranking de coste/valor, posicion por ticker, patrimonio): esos
# turnos no viajan al generador libre.
PRIVATE_PORTFOLIO_MARKERS = (
    "posiciones abiertas",
    "posición guardada",
    "posicion guardada",
    "cartera guardada",
    "la posición con el",
    "la posicion con el",
    "valor de tus posiciones",
    "datos guardados en la app",
    "patrimonio neto",
)


def is_private_portfolio_turn(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in PRIVATE_PORTFOLIO_MARKERS)


def _history_for_prompt(history: list[Any] | None) -> list[dict[str, str]]:
    """Últimos turnos con tope de tamaño para el generador libre.

    Las respuestas con datos de cartera guardados (posiciones, costes) no
    viajan: el generador libre no ve contexto privado. Se conserva el hilo
    con el resto de turnos, del más reciente hacia atrás.
    """
    kept: list[dict[str, str]] = []
    total = 0
    for turn in reversed((history or [])[-_HISTORY_TURNS:]):
        role = getattr(turn, "role", None)
        text = " ".join((getattr(turn, "content", "") or "").split())
        if role not in ("user", "assistant") or not text:
            continue
        if role == "assistant" and is_private_portfolio_turn(text):
            continue
        text = text[:_HISTORY_TURN_CHARS]
        if total + len(text) > _HISTORY_TOTAL_CHARS:
            break
        total += len(text)
        kept.append({"role": role, "content": text})
    kept.reverse()
    return kept


def _with_fallback_notice(answer: str, response: Any) -> str:
    """Antepone «Respondido por respaldo (...) porque OpenCode Go falló: ...».

    Decision del dueno (2026-10-27): una respuesta de respaldo nunca se
    presenta como si fuera de OpenCode Go.
    """
    notice = fallback_notice(response, lang=current_language())
    if not notice or not answer:
        return answer
    return f"{notice}\n\n{answer}"


class ChatSynthesisService:
    def __init__(self, provider: LLMProvider, tracer: LangfuseTracer | None = None) -> None:
        self.provider = provider
        self.tracer = tracer or LangfuseTracer()

    async def synthesize(
        self,
        *,
        question: str,
        ticker: str | None,
        baseline: ChatResponse,
        db: Session | None = None,
        enable_debate: bool | None = None,
        page: dict | None = None,
    ) -> ChatResponse:
        # «¿Qué diría Buffett de ASTS?» con la biblioteca sin ese autor: la
        # ruta de empresa tampoco puede ponerle palabras en boca; misma
        # respuesta honesta que la ruta general (author-source-missing-v1).
        question_plain = _plain(question)
        asked_investors = {
            name for name in _INVESTOR_NAME_LIST
            if re.search(rf"\b{name}\b", question_plain)
        }
        if asked_investors:
            author_chunks = [
                source for source in baseline.sources
                if source.get("type") == "knowledge_chunk" and source.get("text")
                and any(name in _plain(str(source.get("author") or "")) for name in asked_investors)
            ]
            if not author_chunks:
                return ChatResponse(
                    answer=("No tengo un fragmento verificable de ese autor para darte una cita literal. "
                            "Puedes añadir su carta o documento a la biblioteca; también puedo explicar "
                            "el concepto sin atribuírselo ni presentarlo como una cita."),
                    sources=[], model="deterministic", prompt_version="author-source-missing-v1",
                    confidence=0.9, llm_trace={"path": "author_source_missing", "provider_calls": 0},
                )
        retrieval_ids = [
            f"{source.get('type')}:{source.get('id')}"
            for source in baseline.sources
            if source.get("id") is not None
        ]
        trace_seed = {
            "workflow": "chat_source_aware_synthesis",
            "prompt_version": PROMPT_VERSION,
            "retrieval_set": retrieval_ids,
            "tools": [],
            "fallback": False,
            "escalation": False,
            "escalation_reason": "premium escalation requires a passing evaluation gate",
        }
        with self.tracer.workflow("ChatSourceAwareSynthesis", trace_seed) as trace:
            try:
                budget = BudgetController()
                if db is not None and not budget.can_spend(db, 0.02):
                    raise BudgetExceededError("LLM budget exhausted")
                request = LLMRequest(
                    messages=[
                        Message(
                            "system",
                            get_prompt("chat_source_synthesis", allow_remote=False).text,
                        ),
                        Message(
                            "user",
                            json.dumps(
                                {
                                    "question": question,
                                    "ticker": ticker,
                                    "current_page": page,
                                    "allowed_source_ids": retrieval_ids,
                                    "deterministic_sections": [
                                        section.model_dump() for section in baseline.sections
                                    ],
                                    "retrieved_sources": baseline.sources[:40],
                                },
                                default=str,
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                    task="main_financial_analysis",
                    temperature=0.1,
                    # El analisis de cartera en high usa hasta ~3,9k tokens con
                    # el razonamiento (medido 2026-10-27): 1800 lo truncaba.
                    max_tokens=4000,
                    # Consulta rapida = low, analisis de cartera = high (tabla por seccion).
                    reasoning_effort=chat_reasoning_effort(question),
                    response_format=ResponseFormat.json_schema(
                        RESPONSE_SCHEMA,
                        name="source_aware_chat",
                        strict=True,
                    ),
                    metadata={
                        "prompt_version": PROMPT_VERSION,
                        **get_prompt("chat_source_synthesis", allow_remote=False).trace_metadata(),
                    },
                )
                spent = {"cost": 0.0}

                def _record(resp: Any) -> None:
                    # CADA respuesta del proveedor consume presupuesto, tambien
                    # la que el validador descarta.
                    resp_cost = budget.estimate_cost_eur(
                        resp.model,
                        resp.usage.input_tokens,
                        resp.usage.output_tokens,
                    )
                    spent["cost"] += resp_cost
                    if db is not None:
                        budget.record(
                            db,
                            resp.model,
                            "chat_source_aware_synthesis",
                            resp_cost,
                            resp.usage.total_tokens,
                        )

                def _can_retry() -> None:
                    if db is not None and not budget.can_spend(db, 0.02):
                        raise BudgetExceededError("LLM budget exhausted")

                def _validate_candidate(resp):
                    if inspect_response_text(resp.text, expected_language=current_language()):
                        raise ValueError("Invalid response language")
                    data = parse_json_response(resp.text)
                    self._verified_sections(data, baseline, set(retrieval_ids))
                    float(data["confidence"])
                    data["insufficient_data"]
                    if not _prose_answer_valid(
                        data.get("answer"), expected_language=current_language()
                    ):
                        raise ValueError("Invalid prose answer")
                    _reject_untrusted_output(data, baseline, question)

                bind = getattr(self.provider, "with_candidate_validator", None)
                provider = bind(_validate_candidate, _record) if bind else self.provider
                guarded = await complete_with_deadline(
                    provider,
                    request,
                    source="chat_synthesis",
                    expected_language=current_language(),
                    on_response=None if bind else _record,
                    before_retry=_can_retry,
                )
                response = guarded.response
                cost = spent["cost"]
                payload = parse_json_response(response.text)
                if not _prose_answer_valid(
                    payload.get("answer"), expected_language=current_language()
                ):
                    raise ValueError("Invalid prose answer")
                _reject_untrusted_output(payload, baseline, question)
                sections = self._verified_sections(payload, baseline, set(retrieval_ids))
                declared_confidence = max(0.0, min(1.0, float(payload["confidence"])))
                declared_insufficient = bool(payload["insufficient_data"])
                has_financial_facts = any(
                    source.get("type") == "financial_fact" for source in baseline.sources
                )
                # `insufficient_data` is a SAFETY state, so it is re-derived
                # from the verified output instead of taken from the model. The
                # model could otherwise declare sufficiency with confidence
                # 0.99 while its own FACT section read "no se han encontrado
                # datos financieros suficientes", and that combination was
                # accepted verbatim: the clamp only looked at the CONTEXT, never
                # at what the model actually produced.
                produced_nothing = _section_is_empty(
                    next((s for s in sections if s.key == "facts"), None)
                )
                states_no_data = _section_states_no_data(
                    next((s for s in sections if s.key == "facts"), None)
                )
                insufficient = (
                    declared_insufficient
                    or not has_financial_facts
                    or produced_nothing
                    or states_no_data
                )
                confidence = declared_confidence
                if insufficient:
                    # No evidence, or the model itself said there is none: a
                    # confident answer would be the most misleading output the
                    # system can produce.
                    confidence = min(confidence, MAX_CONFIDENCE_WITHOUT_FACTS)

                baseline.sections = sections
                # Lo visible es la prosa natural; las secciones verificadas
                # quedan plegadas con sus citas.
                baseline.answer = _with_fallback_notice((payload.get("answer") or "").strip(), response)
                baseline.prompt_version = PROMPT_VERSION
                baseline.model = response.model
                baseline.confidence = confidence
                baseline.insufficient_data = insufficient
                baseline.llm_trace = {
                    **trace.metadata,
                    "model": response.model,
                    "provider": response.provider,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_read_tokens": response.usage.cache_read_tokens,
                    "cache_write_tokens": response.usage.cache_write_tokens,
                    "cost": cost,
                    "citations": sum(len(section.citations) for section in sections),
                    "citation_verification": True,
                    "json_validity": True,
                    "evaluation_score": confidence,
                    "request_id": response.request_id,
                    # Que miembros fallaron antes de responder este (vacio = el primero).
                    "fallback_trail": list(response.fallback_trail),
                }
                trace.update(**baseline.llm_trace)
                trace.output = {
                    "confidence": confidence,
                    "insufficient_data": insufficient,
                    "citation_verification": True,
                }
                await self._maybe_attach_debate(baseline, ticker, enable_debate, db=db)
                return baseline
            except Exception as exc:
                # The deterministic response is the safe product contract and fallback.
                baseline.model = "deterministic"
                baseline.confidence = self._baseline_confidence(baseline)
                baseline.insufficient_data = baseline.confidence < 0.5
                baseline.llm_trace = {
                    **trace.metadata,
                    "model": "deterministic",
                    "provider": getattr(self.provider, "name", "unknown"),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "cost": None,
                    "citations": sum(len(section.citations) for section in baseline.sections),
                    "citation_verification": False,
                    "json_validity": not isinstance(exc, (ValueError, ValidationError)),
                    "fallback": True,
                    "fallback_reason": type(exc).__name__,
                    "fallback_detail": _fallback_detail(exc),
                    "evaluation_score": baseline.confidence,
                }
                trace.update(**baseline.llm_trace)
                trace.output = {"fallback": True, "reason": type(exc).__name__}
                logger.warning(
                    "chat synthesis fallback for %s: %s: %s",
                    ticker, type(exc).__name__, baseline.llm_trace["fallback_detail"],
                )
                return baseline

    async def synthesize_general(
        self,
        *,
        question: str,
        baseline: ChatResponse,
        db: Session | None = None,
        history: list[Any] | None = None,
        page: dict | None = None,
        portfolio_context: list[dict] | None = None,
    ) -> ChatResponse:
        """Respuesta natural en espanol para preguntas sin ticker.

        ``portfolio_context`` (posiciones guardadas del usuario) solo lo pasa la
        ruta mixta carta + cartera («¿Qué diría Numantia de mi cartera?»): con
        él y con doctrina recuperada, la pregunta personal no se abstiene.

        El contrato estructurado (HECHO/CALCULO/...) es para respuestas de
        datos. Esta ruta responde con conocimiento natural y, cuando el
        baseline trae doctrina de la biblioteca (cartas de inversores), con
        esos fragmentos como apoyo citable de forma natural.
        """
        from app.llm.general_concepts import followup_definition, local_definition

        definition = local_definition(question)
        if definition is None and history:
            last_user = next(
                (turn.content for turn in reversed(history)
                 if getattr(turn, "role", None) == "user" and getattr(turn, "content", "")),
                None,
            )
            definition = followup_definition(question, last_user)
        if definition is not None:
            return ChatResponse(
                answer=definition, sources=[], proposed_actions=[],
                model="local-educational", prompt_version="local-glossary-v1", confidence=0.8,
                llm_trace={"path": "local_educational", "generated": False, "provider_calls": 0},
            )
        scope = _general_scope(question)
        mixed_portfolio = bool(portfolio_context) and scope == "abstain"
        if mixed_portfolio and re.search(
            r"(?i)\b(buy|sell|compra|compro|comprar|vende|vendo|vender|ejecuta)\b", question or ""
        ):
            mixed_portfolio = False
        if mixed_portfolio and not any(
            source.get("type") == "knowledge_chunk" and source.get("text") for source in baseline.sources
        ):
            mixed_portfolio = False
        if mixed_portfolio:
            scope = "doctrine_portfolio"
        if scope == "abstain":
            # Cartera privada u ordenes: nunca deducir del generador libre.
            return ChatResponse(
                answer=(
                    "No tengo fuentes verificadas en esta ruta para responder "
                    "a esa consulta sobre empresas o inversiones. Los datos actuales "
                    "necesitan una fuente y fecha; los futuros no son hechos oficiales. "
                    "Selecciona la empresa o su ticker para consultar sus fuentes."
                ),
                sources=[],
                model="abstain",
                prompt_version=GENERAL_PROMPT_VERSION,
                confidence=0.2,
                llm_trace={"path": "general", "abstain": True, "reason": "financial_scope"},
            )
        # Doctrina recuperada por el baseline (cartas de Buffett y compania):
        # es contexto real consultado, asi que la respuesta puede apoyarse en
        # el y decir de donde viene. Nunca datos de empresa ni cifras de mercado.
        def _clip(text: str, limit: int) -> str:
            compact = " ".join((text or "").split())
            return compact if len(compact) <= limit else f"{compact[: limit - 3]}..."

        # Esquema unificado de fuentes de doctrina (type, page_number, autor,
        # año, fragmento): el frontend pliega citas de TODAS las rutas con el
        # mismo contrato. El prompt recibe la vista recortada; la respuesta
        # devuelve la fuente completa y plegable.
        def _author_key(author: object) -> str:
            # Apellido o nombre completo normalizado, para cotejar autorias.
            return _plain(str(author or "")).strip()

        doctrine_sources = [
            {
                "type": "knowledge_chunk",
                "id": source.get("id"),
                "title": source.get("title"),
                "author": source.get("author"),
                "year": source.get("year"),
                "page_number": source.get("page_number"),
                "chunk_index": source.get("chunk_index"),
                "source_type": source.get("source_type"),
                "url": source.get("url"),
                "text": _clip(str(source.get("text") or ""), 600),
            }
            for source in baseline.sources
            if source.get("type") == "knowledge_chunk" and source.get("text")
        ]
        # Si la pregunta nombra a un inversor ("segun Buffett") solo sirven
        # fragmentos DE ese autor: citar cartas de otros fondos como fuente de
        # "Buffett" es una atribucion falsa.
        question_plain = _plain(question)
        asked_investors = {
            name for name in _INVESTOR_NAME_LIST
            if re.search(rf"\b{name}\b", question_plain)
        }
        if asked_investors:
            doctrine_sources = [
                source for source in doctrine_sources
                if any(name in _author_key(source.get("author")) for name in asked_investors)
            ]
        if asked_investors and not doctrine_sources:
            return ChatResponse(
                answer=("No tengo un fragmento verificable de ese autor para darte una cita literal. "
                        "Puedes añadir su carta o documento a la biblioteca; también puedo explicar "
                        "el concepto sin atribuírselo ni presentarlo como una cita."),
                sources=[], model="deterministic", prompt_version="author-source-missing-v1",
                confidence=0.9, llm_trace={"path": "author_source_missing", "provider_calls": 0},
            )
        doctrine_sources = doctrine_sources[:3]
        if mixed_portfolio and not doctrine_sources:
            # La doctrina no era del autor pedido: sin carta no hay respuesta mixta.
            scope = "abstain"
            return ChatResponse(
                answer=(
                    "No tengo fuentes verificadas en esta ruta para responder "
                    "a esa consulta sobre empresas o inversiones. Los datos actuales "
                    "necesitan una fuente y fecha; los futuros no son hechos oficiales. "
                    "Selecciona la empresa o su ticker para consultar sus fuentes."
                ),
                sources=[], model="abstain", prompt_version=GENERAL_PROMPT_VERSION, confidence=0.2,
                llm_trace={"path": "general", "abstain": True, "reason": "financial_scope"},
            )
        portfolio_rows = list(portfolio_context or []) if mixed_portfolio else []
        # Autores con fragmento propio en contexto: solo a ellos se puede
        # atribuir una opinion en la respuesta.
        allowed_investors = frozenset(
            name
            for name in _INVESTOR_NAME_LIST
            if any(name in _author_key(source.get("author")) for source in doctrine_sources)
        )
        doctrine = [
            {
                "author": source.get("author"),
                "title": source.get("title"),
                "page": source.get("page_number"),
                "text": source["text"],
            }
            for source in doctrine_sources
        ]
        budget = BudgetController()
        # Mismo control de presupuesto que la ruta estructurada: sin saldo
        # NO hay primera llamada (antes solo se comprobaba el reintento).
        if db is not None and not budget.can_spend(db, 0.02):
            return self._general_fallback(baseline, reason="budget_exhausted")
        request = LLMRequest(
            messages=[
                Message("system", get_prompt("chat_general", allow_remote=False).text),
                Message(
                    "user",
                    json.dumps(
                        {
                            # Sin contexto privado (cartera/memorias/fuentes):
                            # el generador libre solo ve la pregunta.
                            "question": question,
                            "conversation": _history_for_prompt(history) or None,
                            "conversation_note": (
                                "Turnos previos de esta conversación, solo para entender la pregunta actual; "
                                "no son fuentes ni datos verificados."
                            ) if history else None,
                            "scope": scope,
                            "current_page": page,
                            "current_time_context": _clock_context(question),
                            "reviewed_at_utc": datetime.now(UTC).date().isoformat(),
                            "sources_available": bool(doctrine),
                            "doctrine_context": doctrine or None,
                            "portfolio_positions": portfolio_rows or None,
                            "portfolio_note": (
                                "Posiciones guardadas del usuario (datos de su cartera, verificados). "
                                "Relaciona lo que dice la doctrina citada con estas posiciones; "
                                "no atribuyas a la carta nada que su fragmento no diga y no des órdenes."
                            ) if portfolio_rows else None,
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                ),
            ],
            task="chat",
            temperature=0.3,
            max_tokens=600,
            reasoning_effort=get_settings().reasoning_effort_for("chat_general"),
        )
        spent = {"cost": 0.0}
        # Cifras que la respuesta puede dar tal cual porque estan en la doctrina
        # recuperada. Antes "+202% desde su inicio" (literal en la carta) se
        # rechazaba por no llevar "aproximadamente" y el usuario recibia el
        # fallback "no tengo datos" con la carta en el prompt.
        # Las cifras que da el propio usuario (en la pregunta o en sus turnos
        # previos) tampoco son inventadas: «¿y si aporto los 600 € del plan?»
        # se rechazaba por repetir «600» sin «unos» (benchmark 2026-11-08).
        user_words = [question or ""] + [
            str(getattr(turn, "content", "") or "")
            for turn in history or []
            if getattr(turn, "role", None) == "user"
        ]
        doctrine_numbers = grounded_numbers_in(
            [str(item.get("text") or "") for item in doctrine or []]
            + [json.dumps(row, default=str, ensure_ascii=False) for row in portfolio_rows]
            + user_words
        )

        def _record(resp: Any) -> None:
            # CADA respuesta consume presupuesto y se registra en DB como en
            # la ruta estructurada, tambien la descartada por el guard.
            resp_cost = budget.estimate_cost_eur(
                getattr(resp, "model", None) or "unknown",
                resp.usage.input_tokens,
                resp.usage.output_tokens,
            )
            spent["cost"] += resp_cost
            if db is not None:
                budget.record(
                    db,
                    getattr(resp, "model", None) or "unknown",
                    "chat_general",
                    resp_cost,
                    resp.usage.total_tokens,
                )

        def _can_retry() -> None:
            if db is not None and not budget.can_spend(db, 0.02):
                raise BudgetExceededError("LLM budget exhausted")

        try:
            def _validate_candidate(resp):
                lang = current_language()
                if inspect_response_text(resp.text, english="strict", expected_language=lang):
                    raise ValueError("Invalid response language")
                rejection = _general_rejection(
                    resp.text.strip(), lang=lang, allow_placeholders=scope == "ordinary",
                    quantitative=scope != "ordinary" or _general_quantity_context(resp.text),
                    allow_named_attribution=bool(doctrine),
                    allowed_investors=allowed_investors,
                    grounded_numbers=doctrine_numbers,
                    allow_portfolio_claims=bool(portfolio_rows),
                )
                if rejection is not None:
                    raise ValueError(f"Ungrounded general output: {rejection}")

            bind = getattr(self.provider, "with_candidate_validator", None)
            provider = bind(_validate_candidate, _record) if bind else self.provider
            guarded = await complete_with_deadline(
                provider,
                request,
                source="chat_general",
                english="strict",
                expected_language=current_language(),
                on_response=None if bind else _record,
                before_retry=_can_retry,
            )
        except Exception as exc:  # proveedor caido, guard agotado o presupuesto: fallback honesto
            from app.llm.chat_provider import is_quota_exhausted

            logger.warning("chat general fallback: %s: %s", type(exc).__name__, _fallback_detail(exc))
            return self._general_fallback(
                baseline,
                reason="quota" if is_quota_exhausted(exc) else "provider_or_guard_failure",
                detail=f"{type(exc).__name__}: {_fallback_detail(exc)}",
                exc=exc,
            )
        text = (guarded.response.text or "").strip()
        rejection = _general_rejection(
            text,
            lang=current_language(),
            allow_placeholders=scope == "ordinary",
            quantitative=scope != "ordinary" or _general_quantity_context(text),
            allow_named_attribution=bool(doctrine),
            allowed_investors=allowed_investors,
            grounded_numbers=doctrine_numbers,
            allow_portfolio_claims=bool(portfolio_rows),
        )
        if rejection is not None:
            logger.warning("chat general fallback: ungrounded: %s", rejection)
            return self._general_fallback(
                baseline, reason="ungrounded", detail=_fallback_detail(ValueError(rejection)), guard_reason=rejection,
            )
        # Fuentes visibles: SOLO la doctrina que la respuesta usa de verdad
        # (autor o titulo mencionado). Antes se adjuntaban siempre las top-3,
        # usadas o no ("Hola" salia con "Fuentes" de cartas de fondos).
        answer_plain = _plain(text)
        def _author_cited(author: object) -> bool:
            tokens = [t for t in re.findall(r"\w+", _author_key(author)) if len(t) >= 4]
            return bool(tokens) and any(t in answer_plain for t in tokens)

        used_sources = [
            source for source in doctrine_sources
            if _author_cited(source.get("author"))
            or (_plain(str(source.get("title") or "")) and _plain(str(source.get("title") or "")) in answer_plain)
        ]
        return ChatResponse(
            answer=_with_fallback_notice(text, guarded.response),
            # La doctrina consultada viaja como fuente visible y plegable
            # (esquema unificado); sin doctrina usada la prosa no se presenta
            # como respaldada.
            sources=used_sources,
            proposed_actions=[],
            model=guarded.response.model,
            prompt_version=GENERAL_PROMPT_VERSION,
            confidence=0.5 if doctrine else (0.35 if baseline.sources else 0.2),
            llm_trace={
                "path": "general",
                "provider": guarded.response.provider,
                "fallback_trail": list(guarded.response.fallback_trail),
                "cost": spent["cost"],
                "doctrine_chunks": len(doctrine),
            },
        )

    @staticmethod
    def _general_fallback(
        baseline: ChatResponse,
        *,
        reason: str,
        detail: str | None = None,
        guard_reason: str | None = None,
        exc: BaseException | None = None,
    ) -> ChatResponse:
        """Proveedor caído o respuesta rechazada: respuesta determinista, sin modelo.

        Nunca texto crudo del proveedor ni «No puedo responderte con fuentes»
        (benchmark Cerebro 2026-11-08). Con datos de la app (``baseline`` con
        fuentes que no son doctrina) responde con ellos tal cual y añade lo
        que falta como «N/D: falta X (motivo)». Sin datos, solo el N/D y cómo
        seguir. El texto añadido no lleva cifras: toda cifra de la respuesta
        sale del ``baseline`` determinista (0 cifras inventadas).
        """
        from app.core.i18n import current_language

        lang = current_language()
        en = lang == "en"
        kind = _model_down_kind(exc, reason)
        if guard_reason is None and exc is not None:
            found = re.search(r"Ungrounded general output: ([^\n]+)", f"{exc} {exc.__cause__ or ''}")
            guard_reason = found.group(1) if found else None
        missing = _missing_from_guard(guard_reason, lang) if kind == "rejected" else None
        if missing is None:
            es_motive, en_motive = _MODEL_DOWN_MOTIVES[kind]
            missing = (
                f"the model's write-up (reason: {en_motive})" if en
                else f"la redacción del modelo (motivo: {es_motive})"
            )
        nd = f"N/D: {'missing' if en else 'falta'} {missing}."
        # Datos de herramientas de la app (precio, cifras, posiciones); la
        # doctrina recuperada (cartas) no es una respuesta por sí sola.
        data_sources = [
            source for source in baseline.sources or []
            if not (isinstance(source, dict) and source.get("type") == "knowledge_chunk")
        ]
        trace = {
            "path": "general", "fallback": True, "reason": reason, "deterministic": True,
            "model_down": kind,
            **({"fallback_detail": detail} if detail else {}),
        }
        if data_sources and (baseline.answer or "").strip():
            return ChatResponse(
                answer=f"{baseline.answer.strip()}\n\n{nd}",
                sources=data_sources,
                proposed_actions=baseline.proposed_actions,
                model="deterministic",
                prompt_version=GENERAL_PROMPT_VERSION,
                confidence=0.3,
                llm_trace=trace,
            )
        answer = (
            f"I'll only tell you what has a source. {nd} "
            "Give me a company or ticker and I'll answer with its sourced data."
            if en
            else f"Te digo solo lo que tiene fuente. {nd} "
            "Dime una empresa o ticker y te respondo con sus datos con fuente."
        )
        # Sin fuentes adjuntas: el degradado no usó ninguna y enseñarlas
        # sugeriría un respaldo que no existe.
        return ChatResponse(
            answer=answer,
            sources=[],
            proposed_actions=baseline.proposed_actions,
            model="fallback",
            prompt_version=GENERAL_PROMPT_VERSION,
            confidence=0.2,
            llm_trace=trace,
        )

    @staticmethod
    def _verified_sections(
        payload: Any,
        baseline: ChatResponse,
        allowed: set[str],
    ) -> list[SynthesisSection]:
        if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
            raise ValueError("Invalid synthesis envelope")
        parsed = [SynthesisSection.model_validate(item) for item in payload["sections"]]
        by_key = {section.key: section for section in parsed}
        if set(by_key) != set(SECTION_ORDER) or len(parsed) != len(SECTION_ORDER):
            raise ValueError("Synthesis must contain each contract section exactly once")
        baseline_by_key = {section.key: section for section in baseline.sections}
        for section in parsed:
            if any(citation not in allowed for citation in section.citations):
                raise ValueError("Unsupported citation returned by model")
            if section.key not in GROUNDED_SECTIONS:
                continue
            baseline_section = baseline_by_key.get(section.key)
            if not baseline_section or not baseline_section.citations:
                continue
            if not section.citations:
                raise ValueError("Grounded section omitted required citations")
            # A citation must be BOTH in the global allowed set AND in the
            # baseline set of ITS OWN section. Checking only the global set let
            # a `memory_item:*` citation render a user's own hypothesis under the
            # FACT heading with citation_verification: true, which is exactly
            # the five-way classification (fact / calculation / user assumption
            # / inference / unverified) the product sells.
            baseline_citations = set(baseline_section.citations)
            outside = [c for c in section.citations if c not in baseline_citations]
            if outside:
                raise ValueError(
                    f"Citation not sourced from this section's baseline: {outside}"
                )
            # And the source TYPE has to be one a section may legitimately
            # rest on, so a memory or a news item can never pose as a fact.
            for citation in section.citations:
                source_type = citation.split(":", 1)[0]
                permitted = SECTION_SOURCE_TYPES.get(section.key, set())
                if permitted and source_type not in permitted:
                    raise ValueError(
                        f"Citation type {source_type!r} is not permitted in section "
                        f"{section.key!r}"
                    )
        return [by_key[key] for key in SECTION_ORDER]

    @staticmethod
    def _baseline_confidence(baseline: ChatResponse) -> float:
        facts = sum(source.get("type") == "financial_fact" for source in baseline.sources)
        primary = sum(
            source.get("type") in {"document_chunk", "claim_evidence"}
            for source in baseline.sources
        )
        return min(0.75, 0.20 + facts * 0.06 + primary * 0.04)

    @staticmethod
    def _debate_enabled(enable_debate: bool | None) -> bool:
        if enable_debate is not None:
            return enable_debate
        return os.getenv("CAVA_THESIS_DEBATE_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    async def _maybe_attach_debate(
        self,
        baseline: ChatResponse,
        ticker: str | None,
        enable_debate: bool | None,
        db: Any | None = None,
    ) -> None:
        """Enganche opcional del debate bull/bear. Nunca rompe el flujo."""
        if not ticker or not self._debate_enabled(enable_debate):
            return
        # nosemgrep: gerarai-broad-except-pass -- enriquecimiento opcional (Jev/debate) de una respuesta ya construida
        try:
            from app.services.jev_gates import (
                DEBATE_WORTHWHILE_CRITERIA,
                DEBATE_WORTHWHILE_INSTRUCTIONS,
                DEBATE_WORTHWHILE_THRESHOLD,
                jev_choice_or_none,
            )

            gate = await jev_choice_or_none(
                name="debate_worthwhile",
                text=baseline.answer,
                instructions=DEBATE_WORTHWHILE_INSTRUCTIONS,
                criteria=DEBATE_WORTHWHILE_CRITERIA,
            )
            if (
                gate is not None
                and gate.label == "clear_cut"
                and gate.confidence >= DEBATE_WORTHWHILE_THRESHOLD
            ):
                baseline.llm_trace["thesis_debate"] = {
                    "skipped": True,
                    "reason": "jev_clear_cut",
                    "jev_gate": {
                        "label": gate.label,
                        "confidence": gate.confidence,
                    },
                }
                return
        except Exception:
            pass
        # nosemgrep: gerarai-broad-except-pass -- enriquecimiento opcional (Jev/debate) de una respuesta ya construida
        try:
            from app.services.thesis_debate_service import debate_thesis

            baseline.llm_trace["thesis_debate"] = await debate_thesis(
                ticker, baseline.answer, provider=self.provider,
                skip_jev_gate=True, db=db,
            )
        except Exception:
            pass
