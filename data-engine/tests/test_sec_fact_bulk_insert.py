"""Insercion en lote de hechos SEC (perf): una executemany por tanda.

Antes: una sentencia INSERT por hecho (medido con companyfacts reales:
765 INSERT en CHTR por refresh). Ahora los hechos de los bucles principal
(trimestres, FY, DEI) se acumulan y se vuelcan en UNA insercion en lote
antes de la primera lectura (shadows/derivadas/conflictos/chunks).

Reglas que fijan estos tests (contadores, sin reloj):
- un refresh con N hechos emite MUCHAS menos sentencias INSERT que N;
- tenant_id se estampa en la tanda igual que hacia el guardia
  before_flush (la via Core no lo esquiva: se copia de la sesion);
- sin tenant en la sesion se cae al camino ORM de siempre (el guardia
  de database.py manda) y la ingesta funciona igual.
"""

import asyncio

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from tests.test_sec_refresh_unchanged_skip import _company, _FakeSECMini


def _session(*, tenant="tenant-test"):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = factory()
    if tenant is not None:
        session.info["tenant_id"] = tenant
    return session, engine


def _refresh(db, company):
    service = FinancialIngestionService()
    return asyncio.run(service.refresh_from_sec(db=db, company=company))


def test_los_hechos_entran_en_pocas_tandas(monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = _session()
    company = _company(db)

    inserts = []

    @event.listens_for(engine, "before_cursor_execute")
    def contar(conn, cursor, statement, parameters, context, executemany):
        s = " ".join(statement.split()).upper()
        if s.startswith("INSERT INTO FINANCIAL_FACTS"):
            inserts.append(len(parameters) if executemany and isinstance(parameters, list) else 1)

    result = _refresh(db, company)
    assert result["status"] == "ingested"
    n_facts = result["facts_imported"]
    assert n_facts >= 5  # el payload mini ya genera varios hechos + derivadas
    # La prueba del lote: muchas menos SENTENCIAS que hechos (antes eran
    # exactamente n_facts sentencias de una fila).
    assert 0 < len(inserts) <= max(3, n_facts // 3)
    assert sum(inserts) >= n_facts


def test_la_tanda_estampa_el_tenant(monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = _session(tenant="tenant-test")
    company = _company(db)
    _refresh(db, company)

    tenants = {
        f.tenant_id
        for f in db.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company.id)
        )
    }
    assert tenants == {"tenant-test"}


def test_sin_tenant_cae_al_orm_y_la_ingesta_funciona(monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = _session(tenant=None)  # RESEARCH_AUTH_REQUIRED=false en tests
    company = _company(db)
    result = _refresh(db, company)

    assert result["status"] == "ingested"
    assert result["facts_imported"] > 0
