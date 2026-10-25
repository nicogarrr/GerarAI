"""Traduccion de consulta ES -> EN para el RAG de conocimiento (F372).

Limite medido en el piloto (docs/knowledge-rag.md): BM25 no cruza idiomas y la
biblioteca mezcla doctrina en ingles (cartas de Buffett, libros) y en espanol.
Una pregunta en espanol solo alcanzaba bien la mitad espanola del indice.

Solucion: si la consulta parece espanol se traduce al ingles con el modelo
gratuito verificado y la busqueda corre con AMBAS variantes (parametro
``query_variants`` de ``retrieval.search_knowledge``). La traduccion es solo
una expansion de busqueda: nunca se presenta como dato ni sustituye a la
consulta original, que siempre se busca tambien.

Fail-closed: modelo no verificado como gratuito, proveedor sin clave, caido o
con salida invalida => (None, nota) y la busqueda sigue solo con la original.
Esta funcion nunca lanza.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from app.core.config import Settings, get_settings
from app.llm import LLMRequest, Message, create_llm_provider
from app.llm.model_aliases import MODEL_ALIASES, is_owner_approved_model

logger = logging.getLogger(__name__)

MAX_TRANSLATION_CHARS = 400
_CACHE_OK_TTL_S = 24 * 3600
_CACHE_FAIL_TTL_S = 300
_CACHE_MAX = 512
# query normalizada -> (expira en monotonic, traduccion o None en fallo)
_cache: dict[str, tuple[float, str | None]] = {}

_SPANISH_MARKERS = re.compile(r"[¿¡ñáéíóúü]")
# Palabras espanolas frecuentes en preguntas de inversion. Hacen falta >=2
# para no marcar como espanol una consulta inglesa con un prestamo suelto.
_SPANISH_WORDS = frozenset({
    "que", "qué", "como", "cómo", "cual", "cuál", "cuando", "cuándo", "donde", "dónde",
    "porque", "porqué", "sobre", "segun", "según", "entre", "cuanto", "cuánto", "cuantos", "cuántos",
    "acciones", "inversion", "inversión", "inversor", "inversores", "empresas", "beneficios",
    "dividendos", "riesgos", "ventajas", "competitivas", "margen", "seguridad", "deberia", "debería",
    "comprar", "vender", "cartera", "mercado", "dice", "dicen", "explica", "piensa", "escribe",
    "las", "los", "una", "para", "con", "sus", "mejores", "criterios", "diferencia", "hable",
})


def looks_spanish(text: str) -> bool:
    """Heuristica barata: marca diacritica clara o >=2 palabras espanolas."""
    if _SPANISH_MARKERS.search(text):
        return True
    words = re.findall(r"\w+", text.lower())
    return sum(1 for w in words if w in _SPANISH_WORDS) >= 2


def _clean_translation(raw: str) -> str | None:
    """Acepta solo una traduccion usable: una linea, acotada, con letras."""
    text = re.sub(r"\s+", " ", raw.strip().strip("\"'`")).strip()
    if not text or len(text) > MAX_TRANSLATION_CHARS:
        return None
    if not re.search(r"[a-zA-Z]", text):
        return None
    return text


def _resolved_verified_free_model(
    model: str, settings: Settings | None = None
) -> str | None:
    """ID de proveedor que se llamaria de verdad, o None si no esta aprobado.

    Aprobados: free verificados o el modelo Go de la suscripcion del dueno. El
    nombre historico se conserva por compatibilidad. No basta con el alias: el
    registro (persistido en DB, ``configure_model_aliases``) puede apuntar un
    alias aprobado a un ID de proveedor de pago. Se verifica el ID RESUELTO, el
    mismo que aplicara ``TaskModelRouter`` al enviar la peticion.
    """
    settings = settings or get_settings()
    if not is_owner_approved_model(model, settings):
        return None
    try:
        resolved = MODEL_ALIASES.resolve(model, provider="opencode-go")
    except ValueError:
        return None
    return resolved if is_owner_approved_model(resolved, settings) else None


def _cache_key(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _cache_get(key: str) -> tuple[bool, str | None]:
    """(hay entrada fresca, valor). Una entrada None es un fallo cacheado."""
    hit = _cache.get(key)
    if hit is None or hit[0] <= time.monotonic():
        return False, None
    return True, hit[1]


def _cache_put(key: str, value: str | None) -> None:
    if len(_cache) >= _CACHE_MAX:
        now = time.monotonic()
        for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
            del _cache[k]
        while len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    ttl = _CACHE_OK_TTL_S if value else _CACHE_FAIL_TTL_S
    _cache[key] = (time.monotonic() + ttl, value)


async def english_variant(
    query: str,
    *,
    settings: Settings | None = None,
    provider=None,
) -> tuple[str | None, str | None]:
    """(traduccion EN o None, nota de degradacion o None).

    La nota explica por que NO hay traduccion cuando se esperaba una; la ruta
    la devuelve en ``notes`` para que una degradacion no sea silenciosa.
    """
    if not looks_spanish(query):
        return None, None
    key = _cache_key(query)
    fresh, cached = _cache_get(key)
    if fresh:
        if cached:
            return cached, None
        return None, "traduccion de consulta no disponible (fallo reciente en cache)"
    settings = settings or get_settings()
    model = settings.opencode_go_model
    if _resolved_verified_free_model(model, settings) is None:
        return None, "traduccion de consulta omitida: modelo no aprobado (free o Go)"
    request = LLMRequest(
        model=model,
        temperature=0,
        max_tokens=180,
        messages=[
            Message(
                "system",
                "Traduce al ingles la pregunta de inversion del usuario para buscar en una "
                "biblioteca en ingles. Devuelve SOLO la traduccion, sin comillas ni "
                "explicaciones. Conserva nombres propios, tickers y cifras tal cual. "
                "Si ya esta en ingles, devuelvela sin cambios.",
            ),
            Message("user", query.strip()[:1000]),
        ],
    )
    # Regla del repo para flujos con guardia de coste: la cascada NO se admite
    # (sus claves de Gemini/OpenRouter pueden cobrar; ver llm/cascade.py).
    requested = (settings.llm_provider or "").strip().lower()
    if requested in {"auto", "opencode", "opencode_go"}:
        requested = "opencode-go"
    if requested != "opencode-go":
        return None, "traduccion de consulta omitida: proveedor LLM no verificado como gratuito"
    try:
        if provider is None:
            # Sin overrides ni fallback: solo el modelo gratuito verificado.
            pinned = settings.model_copy(
                update={"llm_model_overrides": {}, "opencode_go_fallback_model": ""}
            )
            provider = create_llm_provider(pinned)
        response = await asyncio.wait_for(
            provider.complete(request), timeout=settings.knowledge_rag_query_translation_timeout_s
        )
    except Exception as exc:
        logger.warning("knowledge query translation unavailable: %s", type(exc).__name__)
        _cache_put(key, None)
        return None, f"traduccion de consulta no disponible ({type(exc).__name__})"
    if response.degraded:
        _cache_put(key, None)
        return None, "traduccion de consulta no disponible (respuesta degradada)"
    text = _clean_translation(response.text)
    if text is None:
        _cache_put(key, None)
        return None, "traduccion de consulta descartada: salida invalida"
    if text.casefold() == query.strip().casefold():
        return None, None
    _cache_put(key, text)
    return text, None
