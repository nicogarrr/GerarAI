"""Refresh ESEF sin cambios: huella de los hechos del snapshot + version.

Gemelo del carril SEC (test_sec_refresh_unchanged_skip): reingerir el MISMO
snapshot reescribia todos los hechos (DELETE + INSERT identicos, derivadas
recalculadas, chunks RAG resincronizados) en cada refresh. Con la huella en
el Document la segunda pasada se omite entera.

Reglas que fijan estos tests:
- snapshot identico + misma version de reglas -> status "unchanged", 0
  INSERT/DELETE en financial_facts, ids estables;
- la envoltura (fetched_at, origen) NO forma parte de la huella: cambia en
  cada lectura aunque no cambie ningun hecho;
- snapshot con un periodo nuevo -> reingesta completa;
- bump de ESEF_INGESTION_RULES_VERSION -> reingesta con el mismo snapshot.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session, engine


def _company(db, ticker="ITX", name="Inditex"):
    company = Company(
        ticker=ticker, name=name, exchange="BME", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _dur(val, start, end):
    return {"start": start, "end": end, "val": str(val), "decimals": 0, "lei": "L", "dims": []}


def _snapshot(*, fy_nuevo=False, fetched_at="2026-09-24"):
    revenue = [
        _dur(35900000000, "2023-02-01", "2024-01-31"),
        _dur(38600000000, "2024-02-01", "2025-01-31"),
    ]
    if fy_nuevo:
        revenue.append(_dur(40000000000, "2025-02-01", "2026-01-31"))
    return {
        "lei": "549300TTCXZOGZM2EY83",
        "ticker": "ITX",
        "entity_name": "INDUSTRIA DE DISENO TEXTIL, S.A.",
        "period_end": "2026-01-31" if fy_nuevo else "2025-01-31",
        "fxo_id": "fxo-1",
        "fetched_at": fetched_at,
        "facts": {
            "ifrs-full:Revenue": {"iso4217:EUR": revenue},
            "ifrs-full:ProfitLoss": {"iso4217:EUR": [
                _dur(5870000000, "2024-02-01", "2025-01-31")]},
            "ifrs-full:Assets": {"iso4217:EUR": [
                {"instant": "2025-01-31", "val": "32000000000", "decimals": 0,
                 "lei": "L", "dims": []}]},
            "ifrs-full:CashFlowsFromUsedInOperatingActivities": {"iso4217:EUR": [
                _dur(7200000000, "2024-02-01", "2025-01-31")]},
            "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": {
                "iso4217:EUR": [_dur(1100000000, "2024-02-01", "2025-01-31")]},
        },
    }


def _patch_snapshot(monkeypatch, snapshot):
    monkeypatch.setattr(
        ingestion.esef_connector, "read_esef_snapshot", lambda ticker: snapshot
    )


def _refresh(db, company):
    service = FinancialIngestionService()
    return asyncio.run(service.refresh_from_esef(db, company))


def _contar_escrituras_hechos(engine):
    cuenta = {"insert": 0, "delete": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def contar(conn, cursor, statement, parameters, context, executemany):
        s = " ".join(statement.split()).upper()
        if s.startswith("INSERT INTO FINANCIAL_FACTS"):
            cuenta["insert"] += 1
        elif s.startswith("DELETE FROM FINANCIAL_FACTS"):
            cuenta["delete"] += 1

    return cuenta


def _fact_ids(db, company):
    return sorted(
        db.scalars(
            select(FinancialFact.id).where(FinancialFact.company_id == company.id)
        ).all()
    )


def test_segunda_pasada_identica_no_reescribe(db_engine, monkeypatch):
    _patch_snapshot(monkeypatch, _snapshot())
    db, engine = db_engine
    company = _company(db)

    first = _refresh(db, company)
    assert first["status"] == "ingested"
    assert first["facts_imported"] > 0
    ids_antes = _fact_ids(db, company)

    cuenta = _contar_escrituras_hechos(engine)
    second = _refresh(db, company)

    assert second["status"] == "unchanged"
    assert second["facts_imported"] == 0
    assert second["unchanged"] is True
    assert cuenta == {"insert": 0, "delete": 0}
    assert _fact_ids(db, company) == ids_antes


def test_la_envoltura_no_invalidate_la_huella(db_engine, monkeypatch):
    """fetched_at cambia en cada lectura aunque no cambie ningun hecho."""
    _patch_snapshot(monkeypatch, _snapshot(fetched_at="2026-09-24"))
    db, engine = db_engine
    company = _company(db)
    _refresh(db, company)

    _patch_snapshot(monkeypatch, _snapshot(fetched_at="2026-11-05"))
    cuenta = _contar_escrituras_hechos(engine)
    second = _refresh(db, company)
    assert second["status"] == "unchanged"
    assert cuenta == {"insert": 0, "delete": 0}


def test_snapshot_con_periodo_nuevo_reingiere(db_engine, monkeypatch):
    _patch_snapshot(monkeypatch, _snapshot())
    db, engine = db_engine
    company = _company(db)
    _refresh(db, company)

    _patch_snapshot(monkeypatch, _snapshot(fy_nuevo=True))
    third = _refresh(db, company)
    assert third["status"] == "ingested"
    years = {
        f.fiscal_year
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "revenue",
            )
        )
    }
    assert 2026 in years


def test_bump_de_version_de_reglas_reingiere(db_engine, monkeypatch):
    _patch_snapshot(monkeypatch, _snapshot())
    db, engine = db_engine
    company = _company(db)
    _refresh(db, company)

    monkeypatch.setattr(ingestion, "ESEF_INGESTION_RULES_VERSION", 999)
    rerun = _refresh(db, company)
    assert rerun["status"] == "ingested"
    assert rerun["facts_imported"] > 0
