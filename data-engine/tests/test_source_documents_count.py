"""GET /api/sources/documents/count: total real, no el tamano de pagina (F131).

La lista /documents pagina (50 por defecto); la cabecera de /research/sources
mostraba ese 50 como si fuera el inventario completo. El total tiene que ser
real y estar aislado por tenant.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.sources import documents_count
from app.core.database import Base
from app.models import Company, Document, Tenant


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def test_count_is_real_total_beyond_page_and_tenant_scoped():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant_a = Tenant(external_id="count-a", name="Count A")
        tenant_b = Tenant(external_id="count-b", name="Count B")
        db.add_all([tenant_a, tenant_b])
        db.flush()

        db.info["tenant_id"] = tenant_a.id
        msft = _company("MSFT")
        aapl = _company("AAPL")
        db.add_all([msft, aapl])
        db.flush()
        for i in range(60):
            db.add(
                Document(
                    company_id=msft.id, title=f"msft doc {i}", source_type="manual_upload"
                )
            )
        db.add(Document(company_id=aapl.id, title="aapl doc", source_type="manual_upload"))
        db.flush()  # el tenant se asigna en flush: los docs de A quedan en A

        db.info["tenant_id"] = tenant_b.id
        other = _company("V")
        db.add(other)
        db.flush()
        for i in range(3):
            db.add(Document(company_id=other.id, title=f"other {i}", source_type="manual_upload"))
        db.flush()  # idem: los docs de B quedan en B antes de cambiar el contexto

        # Tenant A: 61 documentos reales (la pagina por defecto daria 50)
        db.info["tenant_id"] = tenant_a.id
        assert documents_count(scope="all", db=db) == {"total": 61}
        assert documents_count(ticker="msft", scope="all", db=db) == {"total": 60}
        assert documents_count(ticker="AAPL", scope="all", db=db) == {"total": 1}

        # Tenant B: solo los suyos
        db.info["tenant_id"] = tenant_b.id
        assert documents_count(scope="all", db=db) == {"total": 3}
