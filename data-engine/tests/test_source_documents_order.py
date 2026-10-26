"""GET /api/sources/documents: «mas recientes» = fecha de PUBLICACION global.

Antes ordenaba por created_at (ingesta): las tandas de ingesta agrupaban por
ticker y desplazaban filings recientes de otros emisores fuera del limite de
50 (F162). Ahora published_at DESC con los sin fecha al final y created_at
como desempate.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.sources import documents
from app.core.database import Base
from app.models import Company, Document, Tenant


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker, name=f"{ticker} Co", exchange="TEST", currency="USD",
        sector="Test", industry="Test", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
    )


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="order-test", name="Order test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_documents_ordered_by_publication_date_nulls_last():
    with _db() as db:
        v = _company("V")
        msft = _company("MSFT")
        db.add_all([v, msft])
        db.flush()
        # Ingerido PRIMERO (created_at mas viejo) pero publicado hace poco:
        # con el orden antiguo quedaba enterrado tras la tanda de V.
        db.add(Document(
            company_id=msft.id, title="8-K reciente de otro emisor",
            source_type="sec_filing",
            published_at=datetime(2026, 9, 23, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ))
        db.add(Document(
            company_id=v.id, title="filing V 2025",
            source_type="sec_filing",
            published_at=datetime(2025, 10, 28, tzinfo=UTC),
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        ))
        db.add(Document(
            company_id=v.id, title="companyfacts sin fecha",
            source_type="sec_companyfacts",
            published_at=None,
            created_at=datetime(2026, 9, 26, tzinfo=UTC),
        ))
        db.commit()

        rows = documents(
            ticker=None, scope="all", include_chunks=False, page=1, page_size=50,
            chunk_limit=1000, chunk_text_limit=1500, db=db,
        )

        titles = [row["title"] for row in rows]
        assert titles == [
            "8-K reciente de otro emisor",   # publicacion mas reciente gana
            "filing V 2025",
            "companyfacts sin fecha",         # sin fecha: al final
        ]
