"""Palabras del usuario con «_» o «%» se buscan literalmente en la biblioteca.

Antes se quitaban del término («free_cash_flow» → «freecashflow») para que no
actuaran de comodín en LIKE, así que la nota que decía «free_cash_flow» no se
encontraba. Ahora se escapan; y el ticker de la empresa tampoco es un patrón.
"""
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.entities import Base
from app.services.knowledge_chat import retrieve
from app.services.library_context import company_library_context, lexical_library_context


def _db(rows):
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    for author, ticker, text in rows:
        doc = KnowledgeDocument(tenant_id=1, title=author, author=author, ticker=ticker,
                                document_type="note", status="ready")
        db.add(doc)
        db.flush()
        db.add(KnowledgeChunk(tenant_id=1, knowledge_document_id=doc.id, chunk_index=0, content=text, page_number=1))
    db.commit()
    db.info["tenant_id"] = 1
    return db


ROWS = [
    ("Nota", None, "Mi métrica clave es free_cash_flow por acción, no el beneficio contable."),
    ("Otra", None, "Las recompras crean valor por debajo del valor intrínseco del negocio."),
]


def test_lexico_de_biblioteca_encuentra_palabra_con_guion_bajo():
    rows = lexical_library_context(_db(ROWS), "¿Qué dice la biblioteca del free_cash_flow por acción?", authors=[])
    assert [r["author"] for r in rows] == ["Nota"]


def test_chat_de_biblioteca_encuentra_palabra_con_guion_bajo():
    rows, _ = retrieve(_db(ROWS), "free_cash_flow", scope="all")
    assert rows
    assert "free_cash_flow" in rows[0][0].content


def test_ticker_con_guion_bajo_no_es_comodin():
    db = _db([
        ("Propia", "AB_C", "Margen bruto estable y deuda baja en AB_C."),
        ("Ajena", "ABXC", "Margen bruto en caída y deuda alta en ABXC."),
    ])
    company = SimpleNamespace(ticker="AB_C", name="Ab C")
    rows = company_library_context(db, company, "¿Qué dicen mis notas del margen y la deuda?")
    assert rows
    assert {r["author"] for r in rows} == {"Propia"}
