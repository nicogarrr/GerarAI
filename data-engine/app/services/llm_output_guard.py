"""Validador de salida del LLM para texto libre en espanol.

Algunos modelos gratuitos (medido con space-bunny-free) sueltan de vez en
cuando caracteres CJK/hangul, frases en ingles o tokens corruptos dentro de una
respuesta en espanol. Este modulo detecta esos tres fallos ANTES de guardar o
mostrar el texto, reintenta UNA vez y, si el reintento tambien falla, levanta
``LLMOutputRejected`` para que el llamador degrade a su respuesta determinista
en vez de publicar basura (mejor "sin datos" que texto roto).

No juzga calidad ni veracidad: solo el idioma y la integridad de los tokens.
El texto entre comillas se ignora para el ingles (citas literales de fuentes) y
los terminos financieros habituales, tickers y siglas no cuentan.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from app.llm import LLMRequest, Message

logger = logging.getLogger(__name__)

EnglishMode = Literal["strict", "off"]

REASON_CJK = "cjk"
REASON_ENGLISH = "english"
REASON_CORRUPT = "corrupt_token"
# i18n B: prosa en espanol cuando la peticion generaba en ingles.
REASON_SPANISH = "spanish"

# Hangul, Hiragana, Katakana, CJK unificado y extensiones, formas de ancho
# completo y signos CJK. Cubre el "문화?" medido.
_CJK_RE = re.compile(
    "[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff\u3400-\u4dbf"
    "\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef\u3000-\u303f]"
)
_CONTROL_RE = re.compile("[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")

# Palabras funcionales que NO existen en espanol. Se excluyen a proposito las
# que coinciden con una palabra espanola (a, he, me, son, es, no, he, come...).
_EN_WORDS = frozenset(
    [
        "the",
        "and",
        "of",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "which",
        "that",
        "this",
        "these",
        "those",
        "therefore",
        "however",
        "provided",
        "because",
        "with",
        "without",
        "from",
        "has",
        "have",
        "had",
        "will",
        "would",
        "should",
        "could",
        "can",
        "may",
        "might",
        "their",
        "its",
        "than",
        "into",
        "over",
        "under",
        "between",
        "while",
        "although",
        "whereas",
        "thus",
        "hence",
        "moreover",
        "furthermore",
        "given",
        "since",
        "also",
        "not",
        "but",
        "for",
        "your",
        "our",
        "they",
        "them",
        "then",
        "there",
        "where",
        "when",
        "what",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "each",
        "every",
        "both",
        "either",
        "neither",
        "more",
        "most",
        "less",
        "least",
        "very",
        "much",
        "many",
        "such",
        "only",
        "just",
        "still",
        "already",
        "based",
        "due",
        "per",
        "about",
        "above",
        "below",
        "after",
        "before",
        "during",
        "if",
        "or",
        "as",
        "at",
        "by",
        "on",
        "it",
        "we",
        "you",
        "he",
        "she",
        "an",
    ]
)
# Se quitan las ambiguas con el espanol o demasiado comunes en terminos
# financieros ("per" de P/E, "as"/"on"/"he"/"or"/"it"/"an"/"at"/"by"/"if").
_EN_WORDS = _EN_WORDS - {
    "per",
    "as",
    "on",
    "he",
    "she",
    "or",
    "it",
    "an",
    "at",
    "by",
    "if",
    "we",
    "you",
    "may",
    "can",
    "more",
    "most",
    "about",
    "over",
    "under",
    "such",
    "given",
    "only",
    "just",
    "still",
    "each",
    "every",
    "both",
    "between",
    "due",
    "since",
    "also",
    "very",
    "much",
    "many",
    "less",
    "least",
    "will",
    "would",
    "be",
}
_EN_MARKERS = frozenset(
    ["therefore", "however", "provided", "thus", "hence", "moreover", "furthermore", "whereas", "although"]
)

# Espejo para generacion en ingles (i18n B): palabras funcionales que NO
# existen en ingles. Se excluyen a proposito las ambiguas con el ingles o el
# dominio financiero ("a", "no", "sin", "son", "en", "es", "se", "su", "o",
# "un", "y"): un texto ingles limpio no debe sumar aciertos aqui, igual que
# uno espanol no los suma en _EN_WORDS. Los nombres propios con articulo
# espanol ("Los Angeles", "El Nino", "La Liga") suman 1-2 aciertos como mucho:
# por debajo de SPANISH_MIN_HITS, igual que en el sentido contrario.
_ES_WORDS = frozenset(
    [
        "el", "la", "los", "las", "una", "unas", "del", "que", "está", "están",
        "fue", "era", "eran", "ha", "han", "con", "por", "para", "como",
        "más", "muy", "ya", "sí", "este", "esta", "estos", "estas", "pero",
        "porque", "cuando", "donde", "qué", "cuál", "cuánto", "también",
        "entre", "sobre", "hasta", "desde", "durante", "según", "precio",
        "cartera", "empresa", "acciones", "datos", "año", "años", "último",
        "última", "puede", "pueden", "tiene", "tienen", "hace", "después",
        "antes", "mismo", "misma", "toda", "todo", "todas", "todos", "otra",
        "otro", "dos", "cada", "parte", "contra", "sigue", "siguen",
    ]
)

_WORD_RE = re.compile(r"[A-Za-z\u00c0-\u024f]+(?:[\u2019\x27][A-Za-z]+)?")
_QUOTED_RE = re.compile(r"\"[^\"\n]{0,600}\"|\u201c[^\u201d\n]{0,600}\u201d|\u00ab[^\u00bb\n]{0,600}\u00bb")
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?\n]\s+)([A-Za-z]+)[,\s]")

_GLUED_EN_RE = re.compile(
    r"\b[a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]{3,}"
    r"(?:depends|components|consensus|therefore|provided|which|because|however|"
    r"based|given|while|where|should|would|could)\b",
    re.IGNORECASE,
)
_HYPHEN_Q_RE = re.compile(r"\b[\w\u00c0-\u024f]+-[a-z]{3,}\?(?=\s|$)")
_LONG_WORD_RE = re.compile(r"[A-Za-z\u00c0-\u024f]{28,}")
_MID_Q_RE = re.compile(
    r"[a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]{3,}\?[a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]{2,}"
)
# Palabras largas legitimas del dominio (no son corrupcion).
_LONG_OK = frozenset({"electroencefalografista"})

ENGLISH_MIN_HITS = 4
ENGLISH_MIN_RATIO = 0.08
# Frase corta claramente inglesa ("The company is profitable."): pocas palabras
# pero casi todas funcionales inglesas.
ENGLISH_SHORT_HITS = 2
ENGLISH_SHORT_RATIO = 0.3


def _strip_quoted(text: str) -> str:
    return _QUOTED_RE.sub(" ", text)


SPANISH_MIN_HITS = 4
SPANISH_MIN_RATIO = 0.08
SPANISH_SHORT_HITS = 2
SPANISH_SHORT_RATIO = 0.3


def _english_hits(text: str) -> tuple[int, int]:
    words = _WORD_RE.findall(_strip_quoted(text))
    if not words:
        return 0, 0
    lowered = [w.lower() for w in words]
    hits = sum(1 for w in lowered if w in _EN_WORDS or w in _EN_MARKERS)
    return hits, len(words)


def _spanish_hits(text: str) -> tuple[int, int]:
    words = _WORD_RE.findall(_strip_quoted(text))
    if not words:
        return 0, 0
    lowered = [w.lower() for w in words]
    hits = sum(1 for w in lowered if w in _ES_WORDS)
    return hits, len(words)


def inspect_text(
    text: str,
    *,
    english: EnglishMode = "strict",
    expected_language: str = "es",
) -> list[str]:
    """Motivos por los que ``text`` no es publicable (lista vacia = limpio).

    ``expected_language`` es el idioma que la generacion debia producir
    (i18n B): con "es" (defecto) se rechaza el ingles segun ``english``;
    con "en" el chequeo se invierte: el ingles es el idioma esperado y se
    rechaza prosa en espanol con la misma heuristica en espejo.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    reasons: list[str] = []
    if _CJK_RE.search(text):
        reasons.append(REASON_CJK)
    if (
        _CONTROL_RE.search(text)
        or _GLUED_EN_RE.search(text)
        or _HYPHEN_Q_RE.search(text)
        or _MID_Q_RE.search(text)
        or any(w.lower() not in _LONG_OK for w in _LONG_WORD_RE.findall(text))
    ):
        reasons.append(REASON_CORRUPT)
    if expected_language == "en":
        hits, total = _spanish_hits(text)
        ratio = hits / max(total, 1)
        if (
            (hits >= SPANISH_MIN_HITS and ratio >= SPANISH_MIN_RATIO)
            or (hits >= SPANISH_SHORT_HITS and ratio >= SPANISH_SHORT_RATIO)
        ):
            reasons.append(REASON_SPANISH)
    elif english == "strict":
        hits, total = _english_hits(text)
        starters = {m.group(1).lower() for m in _SENTENCE_START_RE.finditer(_strip_quoted(text))}
        marker_start = bool(starters & _EN_MARKERS) and hits >= 2
        ratio = hits / max(total, 1)
        if (
            marker_start
            or (hits >= ENGLISH_MIN_HITS and ratio >= ENGLISH_MIN_RATIO)
            or (hits >= ENGLISH_SHORT_HITS and ratio >= ENGLISH_SHORT_RATIO)
        ):
            reasons.append(REASON_ENGLISH)
    return reasons


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _is_free_text(value: str) -> bool:
    """Los ids, enums y claves cortas (``facts``, ``financial_fact:12``) no son
    prosa: sin espacios no hay texto libre que juzgar."""
    return bool(value.strip()) and " " in value.strip()


def inspect_response_text(
    text: str,
    *,
    english: EnglishMode = "strict",
    expected_language: str = "es",
) -> list[str]:
    """Como ``inspect_text`` pero, si la respuesta es JSON, evalua el CONJUNTO de
    los valores de texto libre (no cada uno por separado, o varias frases
    cortas en ingles sumarian por debajo del umbral) y no mira las claves ni los
    ids/enums sin espacios."""
    if not isinstance(text, str):
        return []
    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            parsed = json.loads(stripped)
        except ValueError:
            return inspect_text(text, english=english, expected_language=expected_language)
        values = list(_walk_strings(parsed))
        reasons: list[str] = []
        # CJK, control y tokens corruptos: tambien en valores de una palabra.
        for chunk in values:
            for reason in inspect_text(chunk, english="off"):
                if reason not in reasons:
                    reasons.append(reason)
        if english == "strict" or expected_language == "en":
            prose = " . ".join(v for v in values if _is_free_text(v))
            for reason in inspect_text(prose, english=english, expected_language=expected_language):
                if reason not in reasons:
                    reasons.append(reason)
        return reasons
    return inspect_text(text, english=english, expected_language=expected_language)


class LLMOutputRejected(Exception):
    """El texto del modelo no paso el validador ni tras el reintento."""

    def __init__(self, source: str, reasons: list[str]) -> None:
        super().__init__(f"{source}: salida LLM rechazada ({', '.join(reasons)})")
        self.source = source
        self.reasons = reasons


@dataclass
class GuardedResponse:
    response: Any
    #: Respuestas descartadas por el validador (ya pasaron por ``on_response``).
    discarded: list = field(default_factory=list)
    retried: bool = False
    #: Llamadas reales al proveedor (1 o 2).
    calls: int = 1


_stats_lock = threading.Lock()
_stats: Counter = Counter()

RETRY_HINT = (
    "\n\nREINTENTO: tu respuesta anterior mezclaba idiomas o tenia tokens "
    "corruptos. Responde SOLO en espanol, sin caracteres chinos, coreanos ni "
    "japoneses y sin frases en ingles (salvo tickers, siglas y terminos "
    "financieros habituales)."
)

RETRY_HINT_EN = (
    "\n\nRETRY: your previous answer mixed languages or contained corrupt "
    "tokens. Reply ONLY in English, with no Chinese, Korean or Japanese "
    "characters and no Spanish phrases (except tickers, acronyms and standard "
    "financial terms)."
)


def guard_stats() -> dict[str, int]:
    """Contadores acumulados del proceso: llamadas, disparos, reintentos
    rescatados y rechazos finales, mas el motivo de cada disparo."""
    with _stats_lock:
        return dict(_stats)


def reset_guard_stats() -> None:
    with _stats_lock:
        _stats.clear()


def _count(source: str, key: str) -> None:
    with _stats_lock:
        _stats[key] += 1
        _stats[f"{source}.{key}"] += 1


def _with_retry_hint(request: LLMRequest, *, expected_language: str = "es") -> LLMRequest:
    hint = RETRY_HINT_EN if expected_language == "en" else RETRY_HINT
    messages = list(request.messages)
    for index, message in enumerate(messages):
        if str(getattr(message.role, "value", message.role)) == "system":
            messages[index] = Message(message.role, message.content + hint)
            break
    else:
        messages.insert(0, Message("system", hint.strip()))
    return replace(request, messages=messages)


async def _evict(provider: Any, response: Any) -> None:
    """Una salida rechazada no se queda en la cache de respuestas."""
    evict = getattr(provider, "evict_cached", None)
    if callable(evict) and getattr(response, "cache_key", None):
        try:
            await evict(response)
        except Exception:  # noqa: BLE001 - la cache nunca rompe la llamada
            logger.debug("llm_output_guard: no se pudo retirar la entrada de cache", exc_info=True)


async def complete_guarded(
    provider: Any,
    request: LLMRequest,
    *,
    source: str,
    english: EnglishMode = "strict",
    expected_language: str = "es",
    on_response: Callable[[Any], None] | None = None,
    before_retry: Callable[[], None] | None = None,
) -> GuardedResponse:
    """``provider.complete`` con validacion y UN reintento.

    ``on_response`` se llama con CADA respuesta del proveedor (tambien las
    descartadas) para que el llamador registre su coste. ``before_retry`` se
    llama antes del segundo intento y puede levantar (p. ej. presupuesto
    agotado) para cancelarlo; la excepcion se propaga y el llamador degrada.
    Si las dos respuestas fallan levanta ``LLMOutputRejected`` con ``calls``.
    Los errores del proveedor se propagan sin tocar.
    """
    _count(source, "calls")
    first = await provider.complete(request)
    if on_response is not None:
        on_response(first)
    reasons = inspect_response_text(
        getattr(first, "text", "") or "", english=english, expected_language=expected_language
    )
    if not reasons:
        return GuardedResponse(first)
    _count(source, "triggered")
    await _evict(provider, first)
    for reason in reasons:
        _count(source, f"reason.{reason}")
    logger.warning("llm_output_guard[%s]: salida rechazada (%s), reintento unico", source, ",".join(reasons))
    if before_retry is not None:
        before_retry()
    retry_request = _with_retry_hint(request, expected_language=expected_language)
    cjk_retry = getattr(provider, "complete_cjk_retry", None)
    if REASON_CJK in reasons and callable(cjk_retry):
        # Chat real medido: 94,6 s cuando el primario gratuito lento fallaba
        # en idioma y el reintento repetia la carrera completa con el mismo
        # modelo. Tras un rechazo CJK el reintento salta a la cadena de
        # respaldo verificada (Groq) cuando el proveedor la ofrece.
        _count(source, "cjk_backup_retry")
        cjk_complete = cast(Callable[[LLMRequest], Awaitable[Any]], cjk_retry)
        second = await cjk_complete(retry_request)
    else:
        second = await provider.complete(retry_request)
    if on_response is not None:
        on_response(second)
    retry_reasons = inspect_response_text(
        getattr(second, "text", "") or "", english=english, expected_language=expected_language
    )
    if not retry_reasons:
        _count(source, "recovered")
        return GuardedResponse(second, discarded=[first], retried=True, calls=2)
    _count(source, "rejected")
    await _evict(provider, second)
    logger.warning(
        "llm_output_guard[%s]: reintento tambien rechazado (%s), degradando", source, ",".join(retry_reasons)
    )
    exc = LLMOutputRejected(source, retry_reasons)
    exc.discarded = [first, second]  # type: ignore[attr-defined]
    exc.calls = 2  # type: ignore[attr-defined]
    raise exc
