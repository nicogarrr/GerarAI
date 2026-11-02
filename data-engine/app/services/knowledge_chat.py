"""Preguntas sobre doctrina con citas rehidratadas desde la biblioteca del tenant."""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm import LLMRequest, Message, ResponseFormat
from app.llm.chat_provider import create_chat_llm_provider
from app.llm.json import parse_json_response
from app.llm.model_aliases import is_owner_approved_model
from app.models import KnowledgeChunk, KnowledgeDocument
from app.services import knowledge_analysis
from app.services.prompt_registry import get_prompt

_PROMPT = get_prompt("knowledge_chat", allow_remote=False)


def _prompt():
    """i18n B: resuelve el prompt en el idioma activo de la peticion.

    La constante de modulo queda en espanol (los tests la fijan); cada
    llamada pasa por ``get_prompt`` para heredar el idioma del scope.
    """
    return get_prompt("knowledge_chat", allow_remote=False)


logger = logging.getLogger(__name__)
STOP = frozenset([
    "que", "qué", "dice", "dicen", "sobre", "de", "del", "la", "el", "los", "las", "un", "una", "y", "en", "por", "para", "como", "cómo", "what", "does", "say", "about", "the", "and", "on", "is", "a", "an", "investment", "investing", "inversión", "inversor", "cartas", "carta", "biblioteca", "buffett", "magallanes",
    # Palabras corrientes de pregunta: sin ellas un solo termino generico
    # ("sentido", "tiene") recupera fragmentos irrelevantes.
    "tiene", "tienen", "tenemos", "sentido", "cuándo", "cuando", "hace", "hacen",
    "puede", "pueden", "podemos", "debe", "deben", "debería", "quiero", "saber",
    "mejor", "peor", "bueno", "buena", "buenos", "momento", "cosa", "cosas",
    "importante", "importantes", "según", "segun", "forma", "manera", "caso",
    "casos", "vez", "veces", "hay", "más", "mas", "muy", "cada", "siempre",
    "nunca", "porque", "entre", "desde", "hasta", "donde", "dónde", "cuales",
    "cuáles", "cual", "cuál", "son", "ser", "es", "está", "están", "unos",
    "unas", "este", "esta", "esto", "ese", "esa", "eso", "piensa", "piensan",
])

# Puente ES->EN sin LLM: gran parte del corpus (Buffett, Marks, Munger) esta
# en ingles y una pregunta en castellano no la alcanza por texto. Frases
# primero (margen de seguridad), luego palabras sueltas.
_ES_EN_GLOSSARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("margen de seguridad", ("margin of safety",)),
    ("circulo de competencia", ("circle of competence",)),
    ("círculo de competencia", ("circle of competence",)),
    ("flujo de caja", ("cash flow",)),
    ("valor intrinseco", ("intrinsic value",)),
    ("valor intrínseco", ("intrinsic value",)),
    ("recomprar", ("repurchase", "buyback")),
    ("recompras", ("repurchase", "buyback")),
    ("recompra", ("repurchase", "buyback")),
    ("acciones", ("share", "stock")),
    ("accion", ("share", "stock")),
    ("beneficio", ("earnings", "profit")),
    ("beneficios", ("earnings", "profit")),
    ("deuda", ("debt",)),
    ("dividendo", ("dividend",)),
    ("dividendos", ("dividend",)),
    ("valoracion", ("valuation",)),
    ("valoración", ("valuation",)),
    ("negocio", ("business",)),
    ("negocios", ("business",)),
    ("precio", ("price",)),
    ("riesgo", ("risk",)),
    ("foso", ("moat",)),
    ("calidad", ("quality",)),
    ("crecimiento", ("growth",)),
    ("gestor", ("manager",)),
    ("gestores", ("manager",)),
    ("cartera", ("portfolio",)),
    ("invertir", ("invest",)),
    ("inversion", ("invest",)),
    ("inversión", ("invest",)),
    ("tesis", ("thesis",)),
    ("resultados", ("results", "earnings")),
    ("empresa", ("company", "business")),
    ("empresas", ("company", "business")),
    ("barato", ("cheap",)),
    ("barata", ("cheap",)),
    ("largo plazo", ("long term", "long-term")),
    ("contable", ("accounting",)),
    ("contabilidad", ("accounting",)),
    ("mercado", ("market",)),
)


def _terms(question: str) -> list[str]:
    base = [w for w in re.findall(r"\w+", question.lower()) if len(w) > 2 and w not in STOP]
    expanded = list(base)
    # Flexion: la pregunta dice "recomprar" y la carta dice "recompras".
    for word in base:
        for ending in ("ar", "er", "ir", "ando", "iendo"):
            if word.endswith(ending) and len(word) - len(ending) >= 4:
                expanded.append(word[: -len(ending)])
                break
    folded_question = _fold(question)
    for spanish, english in _ES_EN_GLOSSARY:
        if spanish in folded_question or spanish in base:
            expanded.extend(english)
    return list(dict.fromkeys(expanded))[:16]


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _phrase_priority(question: str, terms: list[str]):
    """Los fragmentos con la frase exacta ("margin of safety") van antes del tope de
    120 candidatos: con terminos sueltos comunes ("margen", "seguridad") el orden por
    id los dejaba fuera. Solo reordena candidatos, no relaja ningun filtro."""
    folded = _fold(question)
    phrases = [t for t in terms if " " in t]
    phrases += [es for es, _ in _ES_EN_GLOSSARY if " " in es and es in folded]
    phrases = list(dict.fromkeys(phrases))
    if not phrases:
        return KnowledgeChunk.id * 0
    return case((or_(*[KnowledgeChunk.content.icontains(p, autoescape=True) for p in phrases]), 0), else_=1)


def retrieve(db: Session, question: str, *, scope: str, author: str | None = None,
             document_id: int | None = None, collection_id: int | None = None) -> tuple[list, str]:
    tenant = db.info.get("tenant_id")
    if tenant is None:
        return [], "sin_datos"
    statement = select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id
    ).where(KnowledgeChunk.tenant_id == tenant, KnowledgeDocument.tenant_id == tenant,
            KnowledgeDocument.status == "ready")
    if scope == "letters":
        statement = statement.where(KnowledgeDocument.document_type == "fund_letter")
    if author:
        statement = statement.where(KnowledgeDocument.author == author)
    if document_id:
        statement = statement.where(KnowledgeDocument.id == document_id)
    if collection_id:
        statement = statement.where(KnowledgeDocument.collection_id == collection_id)
    # El lookup de tenant del request puede haber abierto ya una transacción.
    # Esta operación es de solo lectura: cerrar ANTES del embedder/Qdrant.
    db.rollback()
    ids = []
    if os.getenv("CAVAAI_ENABLE_VECTOR_SEARCH") == "1":
        from app.services.rag import RAGIndex
        try:
            hits = RAGIndex().search(question, tenant_id=tenant, entity_type="knowledge_chunk", limit=40)
        except Exception as exc:
            logger.warning("Knowledge retrieval unavailable: %s", type(exc).__name__)
            hits = []
        ids = [h.get("entity_id") for h in hits if isinstance(h.get("entity_id"), int)]
    # Solo tras terminar todo el I/O vectorial se abre la lectura SQL.
    terms = _terms(question)
    lexical = []
    if terms:
        lexical = list(db.execute(statement.where(or_(
            *[KnowledgeChunk.content.icontains(term, autoescape=True) for term in terms]
        )).order_by(_phrase_priority(question, terms), KnowledgeChunk.id).limit(120)).all())
        covered = sorted(
            (
                # Una frase exacta ("margin of safety") pesa mas que dos palabras sueltas.
                (sum((2 if " " in t else 1) for t in terms if _fold(t) in _fold(row[0].content)), row)
                for row in lexical
            ),
            key=lambda item: -item[0],
        )
        best = covered[0][0] if covered else 0
        if best >= 2:
            # Un solo termino comun no basta: sin este suelo la respuesta a
            # "cuando tiene sentido recomprar acciones" era un fragmento sobre
            # camiones que solo compartia una palabra generica.
            covered = [item for item in covered if item[0] >= 2]
        lexical = [row for _, row in covered]
    semantic = []
    if ids:
        verified = {c.id: (c, d) for c, d in db.execute(statement.where(KnowledgeChunk.id.in_(ids))).all()}
        semantic = [verified[i] for i in ids if i in verified]
    # Alternar conserva resultados semánticos y lexicales; no lee el texto del vector como evidencia.
    chosen = []
    seen = set()
    for i in range(max(len(semantic), min(len(lexical), 6))):
        for group in (semantic, lexical):
            if i < len(group) and group[i][0].id not in seen:
                chosen.append(group[i])
                seen.add(group[i][0].id)
            if len(chosen) >= 6:
                return chosen, "semantica_y_texto" if semantic else "solo_texto"
    return chosen, "semantica_y_texto" if semantic else "solo_texto"


def _citation(chunk, document, quote: str) -> dict:
    pages = {b.get("page") for b in (chunk.metadata_ or {}).get("block_metadata", [])
             if isinstance(b, dict) and isinstance(b.get("page"), int)}
    page = chunk.page_number if len(pages) <= 1 else None
    return {"chunk_id": chunk.id, "document_id": document.id, "title": document.title,
            "author": document.author, "page_number": page,
            "chunk_index": chunk.chunk_index, "quote": quote, "source_url": document.source_url,
            "publication_date": document.publication_date.isoformat() if document.publication_date else None,
            "document_type": document.document_type}


def degraded_analysis(result: dict) -> dict:
    """Sin análisis válido: solo los fragmentos recuperados, dicho con claridad."""
    result.pop("analysis", None)
    result.update(status="fragmentos", message="El análisis estructurado no está disponible ahora mismo. Estos son los fragmentos más relacionados de la biblioteca.")
    return result


async def ask_library(db: Session, question: str, *, scope: str = "letters",
                      author: str | None = None, document_id: int | None = None,
                      collection_id: int | None = None, mode: str = "respuesta", provider=None) -> dict:
    rows, retrieval = retrieve(db, question, scope=scope, author=author,
                              document_id=document_id, collection_id=collection_id)
    result = {"status": "sin_datos", "kind": "doctrina", "mode": mode, "retrieval": retrieval, "answers": [],
              "message": "No hay fragmentos de la biblioteca para esta pregunta."}
    if not rows:
        db.rollback()
        return result
    # Los modelos solo pueden citar el texto efectivamente enviado; nunca adjudicar páginas o URLs.
    sources = {c.id: {"text": c.content[:2200], "citation": _citation(c, d, c.content[:2200])} for c, d in rows}
    # Termina la lectura antes de esperar al LLM: no retiene una conexión del pool.
    db.rollback()
    fallback = [{"text": None, "citation": source["citation"]} for source in sources.values()]
    result.update(status="fragmentos", answers=fallback,
                  message="Fragmentos encontrados. Síntesis no disponible.")
    if mode == "analisis":
        degraded_analysis(result)
    try:
        if provider is None:
            settings = get_settings()
            model = settings.opencode_go_model
            if not is_owner_approved_model(model, settings):
                result["message"] = (
                    "Fragmentos encontrados. Sintesis no disponible: el modelo "
                    "configurado para la biblioteca no es un modelo aprobado "
                    "(free verificado o suscripcion Go)."
                )
                return result
            # Ni overrides ni el fallback de OpenCode pueden salir de los
            # modelos aprobados (free verificado o Go del dueno). La cadena de
            # chat (OpenCode -> Groq -> Gemini) sí: sin ella, un 403 dejaba el
            # análisis siempre degradado.
            settings = settings.model_copy(update={"llm_model_overrides": {}, "opencode_go_fallback_model": ""})
            provider = create_chat_llm_provider(settings)
        else:
            model = "space-bunny-free"
        if mode == "analisis":
            response = await provider.complete(LLMRequest(
                model=model, task="chat", temperature=0, max_tokens=2600,
                metadata=knowledge_analysis.current_prompt().trace_metadata(),
                messages=[Message(role, content) for role, content in knowledge_analysis.build_messages(question, sources)],
                response_format=ResponseFormat.json_object()))
            if response.degraded:
                return degraded_analysis(result)
            analysis = knowledge_analysis.validate(parse_json_response(response.text), sources)
            if analysis is None:
                return degraded_analysis(result)
            result.update(status="ok", answers=[], analysis=analysis, message=None)
            return result
        response = await provider.complete(LLMRequest(
            model=model, task="chat", temperature=0, max_tokens=1600,
            metadata=_prompt().trace_metadata(),
            messages=[Message("system", _prompt().text),
                      Message("user", json.dumps({"question": question, "sources": [{"chunk_id": i, "text": source["text"], "author": source["citation"]["author"], "title": source["citation"]["title"]} for i, source in sources.items()]}, ensure_ascii=False))],
            response_format=ResponseFormat.json_object()))
        if response.degraded:
            return result
        payload = parse_json_response(response.text)
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), list):
            return result
        answers = []
        dropped = 0
        reasons: dict[str, int] = {}

        def drop(reason: str) -> None:
            nonlocal dropped
            dropped += 1
            reasons[reason] = reasons.get(reason, 0) + 1

        for item in payload.get("answers", [])[:6]:
            if not isinstance(item, dict):
                drop("item_no_objeto")
                continue
            # Los modelos devuelven a menudo chunk_id como cadena ("3" en vez
            # de 3): se acepta el entero literal, nunca un redondeo ni un float.
            raw_id = item.get("chunk_id")
            if isinstance(raw_id, str) and raw_id.isdecimal():
                raw_id = int(raw_id)
            if type(raw_id) is not int:
                drop("chunk_id_invalido")
                continue
            source = sources.get(raw_id)
            text = item.get("text")
            if not source:
                drop("chunk_id_no_enviado")
                continue
            if not isinstance(text, str):
                drop("texto_no_cadena")
                continue
            quote = knowledge_analysis.clean_quote(item.get("quote"), source["text"])
            if quote is None:
                drop("cita_no_literal_o_longitud")
                continue
            if not 1 <= len(text) <= 1400:
                drop("texto_longitud")
                continue
            # Cifras nuevas se rechazan en vez de presentarlas como verificadas.
            if not set(re.findall(r"\d+(?:[.,]\d+)*", text)) <= set(re.findall(r"\d+(?:[.,]\d+)*", quote)):
                drop("cifras_fuera_de_la_cita")
                continue
            answers.append({"text": text, "citation": {**source["citation"], "quote": quote}})
        if answers:
            result.update(status="ok", answers=answers, message=None)
        elif payload.get("answers"):
            # El modelo respondio pero nada supero la verificacion de citas:
            # se dice, distinto de un fallo del proveedor o de cuota.
            logger.warning("Knowledge chat: %s respuestas descartadas en verificacion motivos=%s", dropped, reasons)
            result["message"] = (
                "Fragmentos encontrados. El modelo respondio pero sus respuestas "
                "no superaron la verificacion de citas. Los fragmentos citados "
                "son literales y siguen siendo validos."
            )
        elif payload.get("answers") == []:
            result.update(status="sin_datos", answers=[], message="Los fragmentos encontrados no responden a esta pregunta.")
    except Exception as exc:
        logger.warning("Knowledge chat synthesis unavailable: %s", type(exc).__name__)
        if mode == "analisis":
            return degraded_analysis(result)
        result["message"] = (
            "Fragmentos encontrados. Sintesis no disponible ahora mismo: el "
            "proveedor del modelo no respondio. Los fragmentos citados son "
            "literales y siguen siendo validos."
        )
    return result
