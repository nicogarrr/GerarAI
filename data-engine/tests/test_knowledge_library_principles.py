"""Contratos de knowledge_library_service: tickers de documentos, mensajes de
error legibles, ciclo de vida de principios (decidir, fusionar, revisar),
fingerprint estable, lotes por seccion/tamano y duplicados/contradicciones
semanticas.

El ciclo de vida es el contrato que importa: solo principios "proposed" se
aprueban/rechazan/fusionan, revisar crea una version nueva y marca la
anterior superseded, y el fingerprint es insensible al orden de condiciones.
"""


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, InvestmentPrinciple, KnowledgeChunk
from app.services.knowledge_library_service import (
    KnowledgeLibraryService,
    _slug,
    extraction_error_message,
    normalize_knowledge_ticker,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _principle(db: Session, text="Comprar barato con margen de seguridad", status="proposed", version=1) -> InvestmentPrinciple:
    svc = KnowledgeLibraryService()
    p = InvestmentPrinciple(
        knowledge_document_id=1,
        principle=text,
        principle_fingerprint=svc.principle_fingerprint(
            principle=text, category="general", application_conditions=[], exceptions=[]
        ),
        category="general",
        exact_fragment=text,
        status=status,
        version=version,
        author="autor",
        confidence="0.80",
    )
    db.add(p)
    db.commit()
    return p


# -- normalizacion de tickers y slugs ----------------------------------------


def test_normalize_knowledge_ticker_none_vacio_y_valido():
    assert normalize_knowledge_ticker(None) is None
    assert normalize_knowledge_ticker("   ") is None
    assert normalize_knowledge_ticker("  san.mc ") == "SAN.MC"


def test_normalize_knowledge_ticker_invalido_valueerror():
    with pytest.raises(ValueError, match="no es válido"):
        normalize_knowledge_ticker("NO VALIDO")
    with pytest.raises(ValueError, match="no es válido"):
        normalize_knowledge_ticker("A" * 33)
    with pytest.raises(ValueError, match="no es válido"):
        normalize_knowledge_ticker("---")


def test_slug_normaliza_y_exige_contenido():
    assert _slug("  Mis Cartas 2024! ") == "mis-cartas-2024"
    with pytest.raises(ValueError, match="letters or numbers"):
        _slug("  --- ")
    assert len(_slug("x" * 300)) == 160


# -- mensaje de error legible -------------------------------------------------


def test_extraction_error_message_llm_error_en_espanol():
    from app.llm.errors import LLMError

    class _MiLLMError(LLMError):
        pass

    msg = extraction_error_message(_MiLLMError("timeout tecnico"))
    assert "modelo de lenguaje" in msg
    assert "timeout tecnico" not in msg


def test_extraction_error_message_redacta_secretos():
    msg = extraction_error_message(RuntimeError("fallo con apikey=secreto123 en la url"))
    assert "secreto123" not in msg  # la URL del proveedor nunca llega a la UI
    assert "RuntimeError" in msg


# -- ciclo de vida de principios ----------------------------------------------


def test_decide_principle_aprueba_y_rechaza(db):
    svc = KnowledgeLibraryService()
    p = _principle(db)
    svc.decide_principle(db, p, action="approve", actor="nico")
    assert p.status == "approved" and p.approved_by == "nico" and p.approved_at is not None
    p2 = _principle(db, text="Vender caro sin mirar atras")
    svc.decide_principle(db, p2, action="reject", actor="nico")
    assert p2.status == "rejected"


def test_decide_principle_solo_propuestos_y_acciones_validas(db):
    svc = KnowledgeLibraryService()
    p = _principle(db, status="approved")
    with pytest.raises(ValueError, match="proposed"):
        svc.decide_principle(db, p, action="approve", actor="nico")
    p2 = _principle(db, text="Otro principio distinto aqui")
    with pytest.raises(ValueError, match="approve or reject"):
        svc.decide_principle(db, p2, action="archivar", actor="nico")


def test_merge_principle_enlaza_con_el_canonico(db):
    svc = KnowledgeLibraryService()
    canonical = _principle(db, text="Principio canonico ya aprobado", status="approved")
    dup = _principle(db, text="Principio canonico ya aprobado (duplicado)")
    svc.merge_principle(db, dup, canonical=canonical, actor="nico")
    assert dup.status == "merged"
    assert dup.semantic_duplicate_of_id == canonical.id
    assert dup.canonical_principle_id == canonical.id


def test_merge_principle_valida_estado_y_objetivo(db):
    svc = KnowledgeLibraryService()
    p = _principle(db)
    with pytest.raises(ValueError, match="another active principle"):
        svc.merge_principle(db, p, canonical=p, actor="nico")  # consigo mismo
    rejected = _principle(db, text="Rechazado de antes", status="rejected")
    with pytest.raises(ValueError, match="another active principle"):
        svc.merge_principle(db, p, canonical=rejected, actor="nico")


def test_revise_principle_crea_version_y_supersede(db):
    svc = KnowledgeLibraryService()
    p = _principle(db)
    revised = svc.revise_principle(db, p, changes={"principle": "Comprar barato con mucho margen"}, actor="nico")
    assert revised.id != p.id
    assert revised.principle == "Comprar barato con mucho margen"
    assert revised.version == 2
    assert revised.status == "proposed"
    assert revised.canonical_principle_id == p.id
    db.refresh(p)
    assert p.status == "superseded" and p.superseded_by_id == revised.id


def test_revise_principle_valida_estado_y_texto(db):
    svc = KnowledgeLibraryService()
    p = _principle(db, status="merged")
    with pytest.raises(ValueError, match="active principles"):
        svc.revise_principle(db, p, changes={}, actor="nico")
    p2 = _principle(db, text="Principio activo para revisar")
    with pytest.raises(ValueError, match="required"):
        svc.revise_principle(db, p2, changes={"principle": "   "}, actor="nico")


# -- fingerprint ---------------------------------------------------------------


def test_fingerprint_insensible_al_orden_y_espacios():
    svc = KnowledgeLibraryService()
    a = svc.principle_fingerprint(
        principle="Comprar  Barato", category="Value",
        application_conditions=["mercado bajista", "caja neta"],
        exceptions=["bancos", "utilities"],
    )
    b = svc.principle_fingerprint(
        principle="comprar barato", category="value",
        application_conditions=["caja neta", "mercado bajista"],
        exceptions=["utilities", "bancos"],
    )
    assert a == b
    c = svc.principle_fingerprint(
        principle="comprar caro", category="value",
        application_conditions=["caja neta", "mercado bajista"],
        exceptions=["utilities", "bancos"],
    )
    assert a != c


# -- lotes de extraccion --------------------------------------------------------


def _chunk(content: str, section: str | None = None, index: int = 0) -> KnowledgeChunk:
    return KnowledgeChunk(
        knowledge_document_id=1, chunk_index=index, content=content, section_title=section
    )


def test_principle_batches_por_seccion_y_tamano():
    from app.services.knowledge_library_service import (
        PRINCIPLE_BATCH_MAX_CHARS,
        PRINCIPLE_BATCH_MAX_CHUNKS,
    )

    chunks = [
        _chunk("a" * 10, "Intro", 0),
        _chunk("b" * 10, "Intro", 1),
        _chunk("c" * 10, "Cierre", 2),  # cambio de seccion: nuevo lote
    ]
    batches = KnowledgeLibraryService._principle_batches(chunks)
    assert [len(b) for b in batches] == [2, 1]
    # tamano: mas de MAX_CHUNKS chunks fuerzan un nuevo lote
    many = [_chunk("x", "S", i) for i in range(PRINCIPLE_BATCH_MAX_CHUNKS + 1)]
    batches = KnowledgeLibraryService._principle_batches(many)
    assert [len(b) for b in batches] == [PRINCIPLE_BATCH_MAX_CHUNKS, 1]
    # caracteres: un chunk que desborda cierra el lote abierto
    big = [_chunk("x" * PRINCIPLE_BATCH_MAX_CHARS, "S", 0), _chunk("y", "S", 1)]
    batches = KnowledgeLibraryService._principle_batches(big)
    assert [len(b) for b in batches] == [1, 1]


# -- duplicados y contradicciones semanticas ------------------------------------


def test_semantic_tokens_sin_stopwords():
    tokens = KnowledgeLibraryService._semantic_tokens("The Value of a Moat in the Market")
    assert tokens == {"value", "moat", "market"}


def _tokens(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i:02d}" for i in range(1, n + 1))


def test_semantic_duplicate_frontera_082(db):
    svc = KnowledgeLibraryService()
    # candidato de 45 tokens: t01..t45
    p = _principle(db, text=_tokens("t", 45))
    # 41 compartidos sobre union 50 = 0.82 exacto: acepta
    assert svc._semantic_duplicate(db, _tokens("t", 41) + " " + _tokens("u", 5)) is p
    # 40 compartidos sobre union 49 ~= 0.816: rechaza
    assert svc._semantic_duplicate(db, _tokens("t", 40) + " " + _tokens("u", 4)) is None


def test_semantic_duplicate_solo_estados_activos(db):
    svc = KnowledgeLibraryService()
    rejected = _principle(db, text="principio rechazado con foso defensivo", status="rejected")
    assert svc._semantic_duplicate(db, "principio rechazado con foso defensivo") is None
    approved = _principle(db, text="principio aprobado con foso defensivo", status="approved")
    assert svc._semantic_duplicate(db, "principio aprobado con foso defensivo") is approved


def test_semantic_duplicate_texto_distinto_es_none(db):
    svc = KnowledgeLibraryService()
    _principle(db, text="comprar empresas con foso defensivo y caja neta")
    assert svc._semantic_duplicate(db, "vender cuando la tesis se rompe del todo") is None


def test_contradicciones_negacion_asimetrica(db):
    svc = KnowledgeLibraryService()
    left = _principle(db, text="comprar bancos siempre con caja neta y margen amplio")
    right = _principle(db, text="never comprar bancos siempre con caja neta y margen amplio")
    contras = svc._contradictions([left, right])
    assert contras == [{"left_id": left.id, "right_id": right.id}]
    # misma polaridad (positivo-positivo): sin contradiccion
    same = _principle(db, text="comprar bancos siempre con caja neta y margen amplio tambien")
    assert svc._contradictions([left, same]) == []


def test_contradicciones_negativo_negativo_no_es_contradiccion(db):
    svc = KnowledgeLibraryService()
    left = _principle(db, text="never comprar bancos siempre con caja neta")
    right = _principle(db, text="avoid comprar bancos siempre con caja neta")
    assert svc._contradictions([left, right]) == []


def test_contradicciones_baja_similitud_no_es_contradiccion(db):
    svc = KnowledgeLibraryService()
    left = _principle(db, text="never comprar bancos con apalancamiento excesivo")
    right = _principle(db, text="comprar utilities reguladas con dividendo creciente sostenible")
    assert svc._contradictions([left, right]) == []
