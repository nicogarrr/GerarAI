"""D&A: dentro de un mismo 10-K gana el importe mayor entre los conceptos anidados.

Caso real (companyfacts de la SEC, 4-nov-2026). Los conceptos de la D&A están
anidados (``Depreciation`` ⊂ ``DepreciationAndAmortization`` ⊂
``DepreciationDepletionAndAmortization`` / ``…AccretionNet``) y #4532 los
ordena por alcance. Pero algunos emisores etiquetan el concepto «amplio» en una
línea PARCIAL del mismo 10-K: Salesforce presenta
``DepreciationDepletionAndAmortization`` 1.000 M y
``DepreciationAndAmortization`` 3.477 M (la del estado de flujos) para FY2025;
McDonald's 457 M frente a 2.199 M; UPS 3.000 M frente a 3.746 M. Ganaba el de
la etiqueta «amplia» aunque fuera una parte. En una misma presentación el
total de mayor alcance no puede ser menor que uno más estrecho, así que ahí
gana el mayor importe (con un 2 % de tolerancia para cifras redondeadas del
texto). Entre presentaciones distintas manda el orden declarado: un recast
posterior más pequeño (escisiones) no se cambia por una cifra vieja mayor.
Tests sintéticos, sin ningún ticker en la lógica.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.connectors import edgartools_facts
from app.services.financial_ingestion_service import FinancialIngestionService

ACC_25 = "0000000001-26-000001"
ACC_24 = "0000000001-25-000001"
FILED_25 = "2026-02-20"
FILED_24 = "2025-02-20"


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
        "fy": fy, "fp": "FY", "form": "10-K", "start": f"{fy}-01-01",
        "end": f"{fy}-12-31", "val": val, "filed": filed, "accn": accn,
    }


def _fake(concepts: dict[str, list[dict]]):
    class _Fake:
        async def cik_for_ticker(self, ticker):
            return "0000000001"

        async def company_facts(self, cik):
            revenue = [_row(2025, 50e9, ACC_25, FILED_25), _row(2024, 45e9, ACC_24, FILED_24)]
            facts = {name: {"units": {"USD": rows}} for name, rows in concepts.items()}
            facts["Revenues"] = {"units": {"USD": revenue}}
            return {"cik": 1, "facts": {"us-gaap": facts}}

        async def annual_report_anchors(self, cik):
            return {ACC_25: "2025-12-31", ACC_24: "2024-12-31"}

    return _Fake


def _da(db, monkeypatch, concepts) -> dict[str, float]:
    monkeypatch.setattr(ingestion, "SECClient", _fake(concepts))
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    return {
        f.period: float(f.value)
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "depreciation_amortization",
            )
        )
    }


def test_un_dda_parcial_no_gana_al_total_del_mismo_10k(db, monkeypatch):
    assert _da(db, monkeypatch, {
        "DepreciationDepletionAndAmortization": [_row(2025, 1_000_000_000, ACC_25, FILED_25)],
        "DepreciationAndAmortization": [_row(2025, 3_477_000_000, ACC_25, FILED_25)],
    }) == {"2025-12-31:FY": 3_477_000_000}


def test_la_depreciacion_mayor_del_mismo_10k_gana_a_una_d_y_a_parcial(db, monkeypatch):
    assert _da(db, monkeypatch, {
        "DepreciationAndAmortization": [_row(2025, 596_000_000, ACC_25, FILED_25)],
        "Depreciation": [_row(2025, 640_000_000, ACC_25, FILED_25)],
    }) == {"2025-12-31:FY": 640_000_000}


def test_entre_10k_distintos_manda_el_orden_declarado(db, monkeypatch):
    """Un recast posterior más pequeño no se cambia por la cifra vieja mayor."""
    assert _da(db, monkeypatch, {
        "DepreciationAmortizationAndAccretionNet": [_row(2024, 2_018_000_000, ACC_25, FILED_25)],
        "Depreciation": [_row(2024, 4_026_000_000, ACC_24, FILED_24)],
    }) == {"2024-12-31:FY": 2_018_000_000}


def test_una_cifra_redondeada_del_texto_no_pisa_a_la_exacta(db, monkeypatch):
    assert _da(db, monkeypatch, {
        "DepreciationDepletionAndAmortization": [_row(2025, 2_474_000_000, ACC_25, FILED_25)],
        "Depreciation": [_row(2025, 2_500_000_000, ACC_25, FILED_25)],
    }) == {"2025-12-31:FY": 2_474_000_000}


def test_la_via_edgartools_aplica_la_misma_regla():
    by_concept = {
        "DepreciationDepletionAndAmortization": {
            "2025-12-31": {"end": "2025-12-31", "val": 1.0e9, "filed": FILED_25, "accn": ACC_25,
                           "_concept": "DepreciationDepletionAndAmortization"},
        },
        "DepreciationAndAmortization": {
            "2025-12-31": {"end": "2025-12-31", "val": 3.477e9, "filed": FILED_25, "accn": ACC_25,
                           "_concept": "DepreciationAndAmortization"},
        },
    }
    metric = "depreciation_amortization"
    assert ingestion._merge_for_metric(by_concept, metric)["2025-12-31"]["val"] == 3.477e9
    assert edgartools_facts.merge_entries(by_concept, metric)["2025-12-31"]["val"] == 3.477e9
