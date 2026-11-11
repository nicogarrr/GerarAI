"""La D&A de la SEC es la de alcance más amplio, no la amortización de PP&E sola.

Caso real (prod, 4-nov-2026): UnitedHealth presenta en el mismo 10-K
``Depreciation`` (solo inmovilizado material, 1.000 M) y
``DepreciationAndAmortization`` (4.361 M, la del estado de flujos). El mapa
trataba los conceptos como alias y, con la misma fecha de presentación, ganaba
el primero de la lista, ``Depreciation``. Con 1.000 M de «D&A» frente a
3.622 M de capex, la normalización de capex tomaba 2.622 M como capex de
crecimiento, subía el margen FCF del 3,6 % al 6,9 % y el valor base pasaba de
~645 $ a 1.259 $. Son conceptos de distinto alcance, no alias: por periodo
gana el más amplio que exista y ``Depreciation`` solo rellena huecos.
Tests sintéticos, sin ningún ticker en la lógica.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture(autouse=True)
def _sin_free_data(monkeypatch):
    async def _stub(ticker, cik):
        return {"status": "skipped", "recent_filings": [], "macro": None}

    monkeypatch.setattr(ingestion, "_free_data_snapshot", _stub)


def _company(db):
    company = Company(
        ticker="ACME",
        name="Acme",
        exchange="NYSE",
        currency="USD",
        sector="S",
        industry="I",
        company_type="general",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _row(fy: int, val: float, accn: str, filed: str) -> dict:
    return {
        "fy": fy,
        "fp": "FY",
        "form": "10-K",
        "start": f"{fy}-01-01",
        "end": f"{fy}-12-31",
        "val": val,
        "filed": filed,
        "accn": accn,
    }


ACC_25 = "0000000001-26-000001"
ACC_24 = "0000000001-25-000001"


def _fake(concepts: dict[str, list[dict]]):
    class _Fake:
        async def cik_for_ticker(self, ticker, entity_name=None):
            return "0000000001"

        async def company_facts(self, cik):
            # Ingresos de los dos ejercicios: anclan el calendario fiscal.
            revenue = [_row(2025, 50e9, ACC_25, "2026-02-20"), _row(2024, 45e9, ACC_24, "2025-02-20")]
            facts = {name: {"units": {"USD": rows}} for name, rows in concepts.items()}
            facts["Revenues"] = {"units": {"USD": revenue}}
            return {"cik": 1, "facts": {"us-gaap": facts}}

        async def annual_report_anchors(self, cik):
            return {ACC_25: "2025-12-31", ACC_24: "2024-12-31"}

    return _Fake


def _da(db, company) -> dict[str, float]:
    return {
        f.period: float(f.value)
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "depreciation_amortization",
            )
        )
    }


def test_la_d_y_a_completa_gana_a_la_depreciacion_sola_en_el_mismo_10k(db, monkeypatch):
    monkeypatch.setattr(
        ingestion,
        "SECClient",
        _fake(
            {
                "Depreciation": [_row(2025, 1_000_000_000, ACC_25, "2026-02-20")],
                "DepreciationAndAmortization": [_row(2025, 4_361_000_000, ACC_25, "2026-02-20")],
            }
        ),
    )
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _da(db, company) == {"2025-12-31:FY": 4_361_000_000}


def test_una_depreciacion_presentada_despues_no_pisa_la_d_y_a(db, monkeypatch):
    """Ni siquiera si el concepto estrecho viene de un filing más reciente."""
    monkeypatch.setattr(
        ingestion,
        "SECClient",
        _fake(
            {
                "DepreciationAndAmortization": [_row(2024, 4_099_000_000, ACC_24, "2025-02-20")],
                "Depreciation": [_row(2024, 1_000_000_000, ACC_25, "2026-02-20")],
            }
        ),
    )
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _da(db, company) == {"2024-12-31:FY": 4_099_000_000}


def test_solo_depreciacion_sigue_rellenando_el_hueco(db, monkeypatch):
    monkeypatch.setattr(
        ingestion,
        "SECClient",
        _fake(
            {
                "DepreciationAndAmortization": [_row(2025, 4_361_000_000, ACC_25, "2026-02-20")],
                "Depreciation": [_row(2024, 900_000_000, ACC_24, "2025-02-20")],
            }
        ),
    )
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _da(db, company) == {
        "2025-12-31:FY": 4_361_000_000,
        "2024-12-31:FY": 900_000_000,
    }


def test_dda_con_agotamiento_sigue_siendo_la_primera(db, monkeypatch):
    monkeypatch.setattr(
        ingestion,
        "SECClient",
        _fake(
            {
                "DepreciationAndAmortization": [_row(2025, 4_000_000_000, ACC_25, "2026-02-20")],
                "DepreciationDepletionAndAmortization": [_row(2025, 4_200_000_000, ACC_25, "2026-02-20")],
            }
        ),
    )
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _da(db, company) == {"2025-12-31:FY": 4_200_000_000}
