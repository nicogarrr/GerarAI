"""Pasajes de evidencia de la tesis v2: las queries no crecen con los docs.

Antes, ``evidence_passages`` lanzaba una query de chunks POR CADA documento
de la empresa (hasta 8): 5 sentencias con 2 documentos, 11 con 8. Ahora los
chunks salen de una sola query con IN agrupada en memoria. Este test fija que
el coste no depende de cuantos documentos tenga la empresa y que el resultado
es identico al del bucle anterior (referencia ingenua copiada aqui): mismo
orden de documentos, mismo tope de chunks por documento, mismo salto de los
documentos «SEC XBRL facts».
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models import Company, Tenant
from app.models.entities import Base, Document, DocumentChunk
from app.services.expert_team.thesis_v2 import (
    MAX_CHUNKS_PER_DOC,
    PASSAGES_PER_GROUP,
    evidence_passages,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
WORDS = ["segment", "risk", "outlook", "founder", "marca", "guidance", "clientes", "regulat"]

_GROUPS = {
    "negocio": ("segment", "segmento", "customers", "clientes", "business", "negocio", "strategy", "estrategia"),
    "ventaja": ("competit", "market share", "cuota", "network", "red ", "scale", "escala", "brand", "marca"),
    "directivos": ("chief executive", "consejero delegado", "founder", "fundador", "repurchase", "recompra",
                   "dividend", "acquisition", "adquisici", "capital allocation"),
    "riesgos": ("risk", "riesgo", "litigation", "regulat", "uncertain"),
    "guia": ("outlook", "guidance", "expects", "perspectivas", "objetivo", "target"),
}


def _reference(db, company, tenant_id):
    """Algoritmo anterior: una query de chunks por documento."""
    query = select(Document).where(Document.company_id == company.id,
                                   Document.retention_tombstoned_at.is_(None))
    if tenant_id is not None:
        query = query.where(Document.tenant_id == tenant_id)
    docs = db.scalars(query.order_by(Document.published_at.desc().nullslast(), Document.id.desc()).limit(8)).all()
    chunks = []
    for doc in docs:
        if (doc.title or "").startswith("SEC XBRL facts"):
            continue
        for ch in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
                             .order_by(DocumentChunk.chunk_index).limit(MAX_CHUNKS_PER_DOC)).all():
            text = " ".join((ch.text or "").split())
            if len(text) >= 200 and text.count(".") >= 3:
                chunks.append((doc, text))
    out, seen = [], set()
    for group, words in _GROUPS.items():
        scored = []
        for i, (doc, text) in enumerate(chunks):
            low = text.casefold()
            score = sum(low.count(w) for w in words)
            if score:
                scored.append((-score, i, doc, text))
        for _s, _i, doc, text in sorted(scored)[:PASSAGES_PER_GROUP]:
            key = text[:200]
            if key in seen:
                continue
            seen.add(key)
            out.append({"group": group, "document": doc.title, "url": doc.source_url,
                        "date": doc.published_at.date().isoformat() if doc.published_at else None,
                        "text": text[:1200]})
    return out


def _session(n_docs: int, chunks_per_doc, *, seed: int = 7):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"tv2-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    ticker = f"TV{uuid.uuid4().hex[:4].upper()}"
    company = Company(
        ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
        sector="T", industry="T", company_type="standard", valuation_model="standard_dcf",
    )
    db.add(company)
    db.flush()
    rng = random.Random(seed)
    for d in range(n_docs):
        title = "SEC XBRL facts" if d == 1 else f"Annual report {d}"
        doc = Document(
            tenant_id=tenant.id, company_id=company.id, title=title,
            source_type="sec_filing", source_url=f"https://example.test/{d}",
            published_at=BASE + timedelta(days=d),
        )
        db.add(doc)
        db.flush()
        n_chunks = chunks_per_doc(rng) if callable(chunks_per_doc) else chunks_per_doc
        for i in range(n_chunks):
            words = " ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 12)))
            text = f"Frase {d}-{i}. {words}. " * rng.randint(2, 8)
            db.add(DocumentChunk(tenant_id=tenant.id, document_id=doc.id, chunk_index=i, text=text))
    db.commit()
    return engine, db, tenant, company


def _count_and_run(n_docs: int, chunks_per_doc=30) -> tuple[int, list]:
    engine, db, tenant, company = _session(n_docs, chunks_per_doc)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    out = evidence_passages(db, company, tenant.id)
    db.close()
    return len(statements), out


def test_pasajes_tesis_v2_no_escalan_con_el_numero_de_documentos():
    pocas, _ = _count_and_run(2)
    muchas, _ = _count_and_run(8)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 5


def test_pasajes_tesis_v2_identicos_al_bucle_anterior():
    engine, db, tenant, company = _session(10, lambda rng: rng.randint(5, 60), seed=11)
    esperado = _reference(db, company, tenant.id)
    db.expire_all()
    actual = evidence_passages(db, company, tenant.id)
    assert actual == esperado
    assert len(actual) > 0
    db.close()


def test_tope_por_documento_se_aplica_en_sql_sin_hidratar_de_mas(monkeypatch):
    # Tope 5 en vez de 1500: sin el row_number de SQL se hidratarían los 40
    # chunks; con él, solo 5 por documento. El contador de loads del ORM
    # mide filas hidratadas, no statements.
    monkeypatch.setattr("app.services.expert_team.thesis_v2.MAX_CHUNKS_PER_DOC", 5)
    engine, db, tenant, company = _session(2, 20)
    loaded = {"n": 0}

    def _on_load(*a):
        loaded["n"] += 1

    # Listener nombrado y retirado en finally: un listener sobre la clase
    # mapeada es global y sobrevive al engine si no se quita.
    event.listen(DocumentChunk, "load", _on_load)
    try:
        out = evidence_passages(db, company, tenant.id)
        assert loaded["n"] <= 2 * 5, loaded
        assert len(out) > 0
    finally:
        event.remove(DocumentChunk, "load", _on_load)
        db.close()
        engine.dispose()
