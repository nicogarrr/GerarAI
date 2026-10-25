"""Recuperacion de doctrina: puente ES->EN y suelo de relevancia lexica."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.entities import Base
from app.services.knowledge_chat import _terms, retrieve


def _library():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    rows = [
        # Ingles (Buffett): la pregunta en castellano debe alcanzarlo.
        ("Buffett", "fund_letter",
         "Repurchases can add value when the stock sells below intrinsic value "
         "and the business has no better use for the cash.", 8),
        # Relleno irrelevante: comparte solo una palabra generica.
        ("Otro", "fund_letter",
         "7 pequenas empresas de 2-10 camiones necesitan que sus camiones "
         "estén el máximo tiempo posible moviéndose con la máxima carga.", 3),
        # Castellano (Azvalor): tambien aparece.
        ("Azvalor", "fund_letter",
         "Las recompras de acciones crean valor cuando se hacen por debajo "
         "del valor intrinseco.", 5),
    ]
    for author, kind, text, page in rows:
        doc = KnowledgeDocument(tenant_id=1, title=author, author=author,
                                document_type=kind, status="ready")
        db.add(doc)
        db.flush()
        db.add(KnowledgeChunk(tenant_id=1, knowledge_document_id=doc.id,
                              chunk_index=0, content=text, page_number=page))
    db.commit()
    db.info["tenant_id"] = 1
    return db


def test_terminos_expanden_al_ingles():
    terms = _terms("¿Cuándo tiene sentido recomprar acciones?")
    assert "recomprar" in terms
    assert "repurchase" in terms and "buyback" in terms
    assert "share" in terms or "stock" in terms
    # Ruido generico fuera
    assert "tiene" not in terms and "sentido" not in terms


def test_margen_de_seguridad_cruza_idioma():
    assert "margin of safety" in _terms("¿Qué es el margen de seguridad?")


def test_pregunta_castellano_alcanza_carta_en_ingles():
    db = _library()
    rows, mode = retrieve(db, "¿Cuándo tiene sentido recomprar acciones?", scope="letters")
    assert mode == "solo_texto"  # sin vectores en el test
    contents = [row[0].content for row in rows]
    assert any("Repurchases can add value" in c for c in contents)
    assert any("recompras de acciones" in c for c in contents)


def test_fragmento_irrelevante_no_cuela():
    db = _library()
    rows, _ = retrieve(db, "¿Cuándo tiene sentido recomprar acciones?", scope="letters")
    contents = [row[0].content for row in rows]
    assert not any("camiones" in c for c in contents)


def test_frase_exacta_no_se_pierde_tras_120_fragmentos_genericos():
    """Con muchos fragmentos que solo comparten 'margen' y 'seguridad', el que
    contiene la frase 'margin of safety' (id mayor) debe entrar en el candidato."""
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    doc = KnowledgeDocument(tenant_id=1, title="A", author="A", document_type="fund_letter", status="ready")
    db.add(doc)
    db.flush()
    for i in range(130):
        db.add(KnowledgeChunk(tenant_id=1, knowledge_document_id=doc.id, chunk_index=i, page_number=1,
                              content=f"El margen de solvencia y la seguridad del asegurado {i} en seguros de vida."))
    db.add(KnowledgeChunk(tenant_id=1, knowledge_document_id=doc.id, chunk_index=999, page_number=2,
                          content="The margin of safety is the gap between price and intrinsic value."))
    db.commit()
    db.info["tenant_id"] = 1
    rows, _ = retrieve(db, "¿Qué es el margen de seguridad?", scope="letters")
    assert any("margin of safety" in row[0].content for row in rows)
