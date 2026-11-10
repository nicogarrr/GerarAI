"""Pasajes de documentos del recopilador: las queries no crecen con los docs.

Antes, ``company_documents`` lanzaba una query de chunks POR CADA documento
del panel (hasta DOC_MAX_DOCUMENTS=12): 6 sentencias con 3 documentos, 15 con
12. Ahora los chunks de todos los documentos salen de una sola query con IN y
se agrupan en memoria. Este test fija que el coste no depende de cuantos
documentos tenga la empresa y que el resultado (orden de documentos por fecha
descendente, pasajes por chunk_index, tope por documento) es el mismo que
devolvia el bucle anterior.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Company, Tenant
from app.models.entities import Base, Document, DocumentChunk
from app.services.expert_team.models import RunContext
from app.services.expert_team.recopilador import (
    DOC_MAX_PASSAGES_PER_DOC,
    company_documents_tool,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _session(n_docs: int, n_chunks: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"rc-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    ticker = f"RC{uuid.uuid4().hex[:4].upper()}"
    company = Company(
        ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
        sector="Test", industry="Test", company_type="standard",
        valuation_model="standard_dcf",
    )
    db.add(company)
    db.flush()
    for d in range(n_docs):
        doc = Document(
            tenant_id=tenant.id, company_id=company.id, title=f"Filing {d}",
            source_type="sec_filing", published_at=BASE + timedelta(days=d),
        )
        db.add(doc)
        db.flush()
        for i in range(n_chunks):
            text = (
                f"contract backlog segment {d}-{i} " + "x" * 40
                if i % 5 == 0
                else f"texto sin señal {d}-{i}"
            )
            db.add(
                DocumentChunk(
                    tenant_id=tenant.id, document_id=doc.id, chunk_index=i, text=text,
                )
            )
    db.commit()
    return engine, db, tenant, company


def _count_and_run(n_docs: int, n_chunks: int = 40) -> tuple[int, list]:
    engine, db, tenant, company = _session(n_docs, n_chunks)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    ctx = RunContext(tenant_id=tenant.id, ticker=company.ticker, question="impulsores")
    out = company_documents_tool(db).fn(ctx)
    db.close()
    return len(statements), out


def test_pasajes_documentos_no_escalan_con_el_numero_de_documentos():
    pocas, _ = _count_and_run(3)
    muchas, _ = _count_and_run(12)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 5


def test_pasajes_conservan_orden_y_tope_por_documento():
    _, out = _count_and_run(3, 40)
    # Cada documento aporta 8 chunks con señal (i % 5 == 0), recortados al
    # tope por documento; el documento mas reciente va primero.
    assert len(out) == 3 * DOC_MAX_PASSAGES_PER_DOC
    por_doc: dict[str, list[str]] = {}
    for passage in out:
        por_doc.setdefault(passage.source["document_id"], []).append(passage.data["text"])
    assert len(por_doc) == 3
    for textos in por_doc.values():
        assert len(textos) == DOC_MAX_PASSAGES_PER_DOC
        # Orden por chunk_index: los indices con señal son 0, 5, 10, 15...
        assert [t.split()[3] for t in textos] == sorted(
            (t.split()[3] for t in textos), key=lambda s: int(s.split("-")[1])
        )
