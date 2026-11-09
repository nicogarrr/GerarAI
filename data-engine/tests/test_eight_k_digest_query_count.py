"""8-K digest: los chunks de todos los documentos salen de UNA query.

Antes, ``eight_k_digest`` lanzaba una query de chunks POR documento (hasta
MAX_SCAN=300) y un db.get por documento. Ahora las companias salen de una IN
y los chunks de una ventana row_number por document_id con el mismo tope
MAX_CHUNKS+1 y orden chunk_index EN SQL (patron probado por el auditor en
evidence_passages), sin hidratar instancias ORM de DocumentChunk. Este test
fija el coste plano, la paridad del tope por documento (un doc con mas de
MAX_CHUNKS no se resume) y la hidratacion cero de chunks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, DocumentChunk, Tenant, WatchItem
from app.services.eight_k_digest import MAX_CHUNKS, eight_k_digest


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id=1, external_id="k8-count", name="K8 count"))
    db.flush()
    db.info["tenant_id"] = 1
    db.add(Company(id=1, ticker="INTC", name="Intel", exchange="NASDAQ",
                   company_type="large_cap", valuation_model="dcf"))
    db.add(WatchItem(symbol="INTC", company="Intel"))
    db.flush()
    return db


def _doc(i: int) -> Document:
    return Document(
        company_id=1,
        title="8-K presentado ante la SEC",
        source_type="SEC",
        source_url=f"https://www.sec.gov/Archives/edgar/data/50863/filing{i}/intc-8k.htm",
        published_at=datetime(2026, 10, 15, tzinfo=UTC) - timedelta(days=i),
        checksum=f"chk{i}",
        metadata_={"form": "8-K"},
    )


def _seed(db: Session, n_docs: int, chunks_per_doc: int = 3) -> None:
    for i in range(n_docs):
        doc = _doc(i)
        db.add(doc)
        db.flush()
        for c in range(chunks_per_doc):
            db.add(DocumentChunk(
                tenant_id=1, document_id=doc.id, chunk_index=c,
                text=f"Texto del chunk {c} sin apartados reconocibles del formulario.",
                token_count=10,
            ))
    db.commit()


def _count(db: Session) -> int:
    statements: list[str] = []
    event.listen(db.bind, "before_cursor_execute", lambda *a: statements.append(a[2]))
    result = eight_k_digest(db)
    assert result["scanned"] > 0
    return len(statements)


def test_digest_no_escala_por_documento():
    db = _db()
    _seed(db, 20)
    pocas = _count(db)
    db.close()
    db = _db()
    _seed(db, 60)
    muchas = _count(db)
    db.close()
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 8


def test_digest_paridad_tope_por_documento():
    # Un doc con MAX_CHUNKS+1 chunks no se resume (None), como antes; otro
    # con chunks sin apartados sigue informando de apartados no legibles.
    db = _db()
    over = _doc(0)
    db.add(over)
    db.flush()
    for c in range(MAX_CHUNKS + 1):
        db.add(DocumentChunk(
            tenant_id=1, document_id=over.id, chunk_index=c,
            text="Texto sin apartados.", token_count=3,
        ))
    normal = _doc(1)
    db.add(normal)
    db.flush()
    db.add(DocumentChunk(
        tenant_id=1, document_id=normal.id, chunk_index=0,
        text="Texto sin apartados reconocibles.", token_count=4,
    ))
    db.commit()
    result = eight_k_digest(db)
    by_id = {e["document_id"]: e for e in result["items"]}
    assert "Sin texto completo disponible" in by_id[over.id]["reason"]
    assert "No se identificaron apartados legibles" in by_id[normal.id]["reason"]
    db.close()


def test_digest_no_hidrata_chunks_orm():
    # La ventana devuelve filas planas: cero instancias ORM de DocumentChunk
    # aunque haya cientos de chunks en juego.
    db = _db()
    _seed(db, 30, chunks_per_doc=10)
    db.expire_all()
    loaded = {"n": 0}

    def _on_load(*a):
        loaded["n"] += 1

    # Listener nombrado y retirado en finally: un listener sobre la clase
    # mapeada es global y sobrevive al engine si no se quita.
    engine = db.bind
    event.listen(DocumentChunk, "load", _on_load)
    try:
        eight_k_digest(db)
        assert loaded["n"] == 0, loaded
    finally:
        event.remove(DocumentChunk, "load", _on_load)
        db.close()
        if engine is not None:
            engine.dispose()
