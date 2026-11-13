"""Un fallo de BD dentro del enriquecimiento no debe romper el import IBKR.

El enriquecimiento es opcional (`except Exception: pass`). Si fallaba tras un
flush erróneo, la sesión quedaba en PendingRollback y las filas siguientes del
import no se guardaban. Ahora corre en un SAVEPOINT: se deshace solo él.
"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Tenant
from app.services.ibkr_import_service import IBKRImportService


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="enrich-savepoint", name="Fixture")
    session.add(tenant)
    session.flush()
    session.info["tenant_id"] = tenant.id
    return session


def test_enrichment_db_failure_keeps_session_and_prior_rows(monkeypatch):
    def broken_enrich(self, db, company, *args, **kwargs):
        # Flush inválido: ticker duplicado (unique) dentro del enriquecimiento.
        db.add(Company(ticker="AAA", name="dup", exchange="X", currency="USD",
                       company_type="standard", valuation_model="standard_dcf"))
        db.flush()

    monkeypatch.setattr(
        "app.services.company_enrichment_service.CompanyEnrichmentService.enrich", broken_enrich
    )
    with _session() as db:
        service = IBKRImportService()
        cache: dict[str, Company] = {}
        first = service._company(db, cache, "AAA")  # el duplicado falla dentro del savepoint
        second = service._company(db, cache, "BBB")  # la sesión sigue usable
        assert first.ticker == "AAA" and second.ticker == "BBB"
        db.commit()
        tickers = set(db.scalars(select(Company.ticker)).all())
        assert tickers == {"AAA", "BBB"}
