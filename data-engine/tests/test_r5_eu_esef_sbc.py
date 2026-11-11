"""Remuneración en acciones (SBC) en la ingesta ESEF, como en los 20-F (r5-eu, 11-nov-2026).

Antes: ``ESEF_METRIC_MAP`` no leía ``ifrs-full:AdjustmentsForSharebasedPayments`` ni
``ifrs-full:ExpenseFromSharebasedPaymentTransactionsWithEmployees``, aunque el mapa IFRS de los 20-F/40-F de la SEC
(``SEC_IFRS_METRIC_MAP``) sí. Ningún emisor europeo tenía SBC: el SOTP y la TIR del accionista no restaban la
dilución por remuneración en acciones. Nico aprobó leerla (11-nov 23:45) sabiendo que cambia valoraciones.
Comprobado en filings.xbrl.org (11-nov-2026): Intertek FY2025 AdjustmentsForSharebasedPayments 24,3 M£ (FY2024
24,4 M£); Eurofins solo etiqueta una extensión que suma SBC y costes de adquisición (no se toma); Airbus no etiqueta
un SBC consolidado sin dimensiones (sigue N/D).
"""
import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _dur(val, y, dims=None):
    return {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": str(val), "decimals": -5, "lei": "L",
            "dims": dims or []}


def _inst(val, y):
    return {"instant": f"{y}-12-31", "val": str(val), "decimals": -5, "lei": "L", "dims": []}


def _snapshot(sbc_concept="ifrs-full:AdjustmentsForSharebasedPayments"):
    facts: dict = {}

    def put(concept, entry):
        facts.setdefault(concept, {}).setdefault("iso4217:GBP", []).append(entry)

    for y, rev in ((2025, 3400e6), (2024, 3390e6)):
        put("ifrs-full:Revenue", _dur(rev, y))
        put("ifrs-full:ProfitLoss", _dur(400e6, y))
        put("ifrs-full:Assets", _inst(4200e6, y))
        put("ifrs-full:CashFlowsFromUsedInOperatingActivities", _dur(600e6, y))
    if sbc_concept:
        put(sbc_concept, _dur(24.3e6, 2025))
        put(sbc_concept, _dur(24.4e6, 2024))
    # Movimiento de patrimonio por componente: no es el gasto consolidado y nunca entra.
    put("ifrs-full:IncreaseDecreaseThroughSharebasedPaymentTransactions",
        _dur(99e6, 2025, dims=["ifrs-full:ComponentsOfEquityAxis"]))
    # Extensión que mezcla SBC con costes de adquisición (patrón Eurofins): no es la cifra.
    put("erf:AdjustmentsForExpenseFromShareBasedPaymentTransactionsWithEmployeesAndAcquisitionRelatedCosts",
        _dur(137.7e6, 2025))
    return {"lei": "2138003GAT25WW1RN369", "ticker": "ITRK.L", "entity_name": "INTERTEK GROUP PLC",
            "period_end": "2025-12-31", "fxo_id": "fxo-itrk", "fetched_at": "2026-11-11", "facts": facts}


def _ingest(db, monkeypatch, snap):
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: snap)
    company = Company(ticker="ITRK.L", name="Intertek Group plc", exchange="LSE", currency="GBP", sector="Industrials",
                      industry="I", company_type="operating", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    return {(f.metric, f.period): f for f in db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id))}


def test_esef_importa_sbc_consolidado_en_la_divisa_del_informe(db, monkeypatch):
    by = _ingest(db, monkeypatch, _snapshot())
    fact = by[("stock_based_compensation", "2025-12-31:FY")]
    assert fact.value == Decimal("24300000")
    assert fact.unit == "GBP" and fact.source_type == "ESEF" and fact.is_reported
    assert by[("stock_based_compensation", "2024-12-31:FY")].value == Decimal("24400000")


def test_esef_sbc_alias_del_mapa_20f(db, monkeypatch):
    by = _ingest(db, monkeypatch, _snapshot("ifrs-full:ExpenseFromSharebasedPaymentTransactionsWithEmployees"))
    assert by[("stock_based_compensation", "2025-12-31:FY")].value == Decimal("24300000")


def test_sin_concepto_estandar_no_hay_sbc_inventado(db, monkeypatch):
    # Solo el movimiento de patrimonio con dimensión y la extensión mezclada: N/D, nunca 99 ni 137,7 M.
    by = _ingest(db, monkeypatch, _snapshot(None))
    assert not [k for k in by if k[0] == "stock_based_compensation"]


def test_mismos_conceptos_que_el_mapa_20f_y_version_subida():
    esef = {m: c for m, c, _u in ingestion.ESEF_METRIC_MAP}
    sec = {m: c for m, c, _u in ingestion.SEC_IFRS_METRIC_MAP}
    assert [c.removeprefix("ifrs-full:") for c in esef["stock_based_compensation"]] == sec["stock_based_compensation"]
    assert ingestion.ESEF_INGESTION_RULES_VERSION >= 9
