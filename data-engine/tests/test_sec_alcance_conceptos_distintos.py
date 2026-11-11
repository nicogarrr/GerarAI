"""Conceptos SEC de DISTINTO alcance no son alias: uno presentado después no pisa al preferido.

Caso real (companyfacts de la SEC, 4-nov-2026). ``_collapse_aliases`` elige por
periodo el hecho con el ``filed`` más reciente entre todos los conceptos de la
lista. Los estados financieros repiten saldos de años anteriores en distintos
sitios: el estado de flujos trae cuatro saldos de caja (con restringida), el
de patrimonio tres o cuatro saldos de patrimonio (con minoritarios). Así, para
los ejercicios previos ganaba el concepto de otro alcance solo porque aparecía
en un 10-K posterior, y la serie cambiaba de significado entre años:

- patrimonio: ``StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest``
  (con minoritarios) pisaba a ``StockholdersEquity`` (matriz): FCX FY2023
  27.310 M frente a 16.693 M;
- beneficio neto: ``ProfitLoss`` (con minoritarios) pisaba a ``NetIncomeLoss``:
  ASTS FY2020 −24 M frente a −52 M;
- caja: ``CashCashEquivalentsRestrictedCash…`` pisaba a la caja estricta: ABNB
  FY2023 12.667 M frente a 6.874 M;
- arrendamientos operativos: ``OperatingLeaseLiabilityNoncurrent`` (solo la
  parte no corriente) pisaba al total ``OperatingLeaseLiability``: AAPL.

Para estas métricas el orden declarado es la prioridad (``SCOPE_PRIORITY_METRICS``,
el mecanismo de #4532) y el resto solo rellena los periodos sin el preferido.
Tests sintéticos, sin ningún ticker en la lógica.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
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


def _flow(fy: int, val: float, accn: str, filed: str) -> dict:
    return {
        "fy": fy, "fp": "FY", "form": "10-K", "start": f"{fy}-01-01",
        "end": f"{fy}-12-31", "val": val, "filed": filed, "accn": accn,
    }


def _instant(fy: int, val: float, accn: str, filed: str) -> dict:
    return {
        "fy": fy, "fp": "FY", "form": "10-K", "end": f"{fy}-12-31",
        "val": val, "filed": filed, "accn": accn,
    }


def _fake(concepts: dict[str, list[dict]]):
    class _Fake:
        async def cik_for_ticker(self, ticker, entity_name=None):
            return "0000000001"

        async def company_facts(self, cik):
            revenue = [_flow(2025, 50e9, ACC_25, FILED_25), _flow(2024, 45e9, ACC_24, FILED_24)]
            facts = {name: {"units": {"USD": rows}} for name, rows in concepts.items()}
            facts.setdefault("Revenues", {"units": {"USD": revenue}})
            return {"cik": 1, "facts": {"us-gaap": facts}}

        async def annual_report_anchors(self, cik):
            return {ACC_25: "2025-12-31", ACC_24: "2024-12-31"}

    return _Fake


def _ingest(db, monkeypatch, concepts):
    monkeypatch.setattr(ingestion, "SECClient", _fake(concepts))
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    return company


def _facts(db, company, metric: str) -> dict[str, float]:
    return {
        f.period: float(f.value)
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
            )
        )
    }


def test_patrimonio_con_minoritarios_presentado_despues_no_pisa_al_de_la_matriz(db, monkeypatch):
    company = _ingest(db, monkeypatch, {
        # FY2024: balance del 10-K de 2024 (matriz) y estado de patrimonio del
        # 10-K de 2025 (total con minoritarios, saldo de apertura).
        "StockholdersEquity": [
            _instant(2025, 18e9, ACC_25, FILED_25),
            _instant(2024, 16.7e9, ACC_24, FILED_24),
        ],
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
            _instant(2025, 28.5e9, ACC_25, FILED_25),
            _instant(2024, 27.3e9, ACC_25, FILED_25),
        ],
    })
    assert _facts(db, company, "total_equity") == {
        "2025-12-31:FY": 18e9,
        "2024-12-31:FY": 16.7e9,
    }


def test_beneficio_con_minoritarios_presentado_despues_no_pisa_al_atribuible(db, monkeypatch):
    company = _ingest(db, monkeypatch, {
        "NetIncomeLoss": [_flow(2024, -52e6, ACC_24, FILED_24)],
        "ProfitLoss": [_flow(2024, -24e6, ACC_25, FILED_25)],
    })
    assert _facts(db, company, "net_income") == {"2024-12-31:FY": -52e6}


def test_caja_con_restringida_presentada_despues_no_pisa_a_la_caja_estricta(db, monkeypatch):
    company = _ingest(db, monkeypatch, {
        "CashAndCashEquivalentsAtCarryingValue": [
            _instant(2025, 7.4e9, ACC_25, FILED_25),
            _instant(2024, 6.9e9, ACC_24, FILED_24),
        ],
        # El estado de flujos del 10-K de 2025 repite el saldo de 2024 con la
        # caja restringida (fondos de clientes) dentro.
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": [
            _instant(2025, 12.1e9, ACC_25, FILED_25),
            _instant(2024, 12.7e9, ACC_25, FILED_25),
        ],
    })
    assert _facts(db, company, "cash_and_equivalents") == {
        "2025-12-31:FY": 7.4e9,
        "2024-12-31:FY": 6.9e9,
    }
    document = db.scalar(
        select(Document).where(Document.company_id == company.id, Document.source_type == "SEC")
    )
    assert "cash_includes_restricted_periods" not in (document.metadata_ or {})


def test_arrendamiento_no_corriente_presentado_despues_no_pisa_al_total(db, monkeypatch):
    company = _ingest(db, monkeypatch, {
        "OperatingLeaseLiability": [_instant(2024, 11.5e9, ACC_24, FILED_24)],
        "OperatingLeaseLiabilityNoncurrent": [_instant(2024, 10.0e9, ACC_25, FILED_25)],
    })
    assert _facts(db, company, "operating_lease_liabilities") == {"2024-12-31:FY": 11.5e9}


def test_el_concepto_secundario_sigue_rellenando_los_huecos(db, monkeypatch):
    company = _ingest(db, monkeypatch, {
        "StockholdersEquity": [_instant(2025, 18e9, ACC_25, FILED_25)],
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
            _instant(2024, 27.3e9, ACC_24, FILED_24),
        ],
        "CashAndCashEquivalentsAtCarryingValue": [_instant(2025, 7.4e9, ACC_25, FILED_25)],
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": [
            _instant(2024, 12.7e9, ACC_24, FILED_24),
        ],
    })
    assert _facts(db, company, "total_equity") == {
        "2025-12-31:FY": 18e9,
        "2024-12-31:FY": 27.3e9,
    }
    assert _facts(db, company, "cash_and_equivalents") == {
        "2025-12-31:FY": 7.4e9,
        "2024-12-31:FY": 12.7e9,
    }


@pytest.mark.parametrize(
    "metric",
    ["total_equity", "net_income", "cash_and_equivalents", "operating_lease_liabilities"],
)
def test_la_via_edgartools_usa_la_misma_prioridad(metric):
    """El conector edgartools replica _merge_for_metric con el mismo conjunto."""
    preferido, secundario = next(c for m, c, _u in ingestion.SEC_METRIC_MAP if m == metric)[:2]
    by_concept = {
        preferido: {"2024-12-31": {"end": "2024-12-31", "val": 1.0, "filed": FILED_24, "_concept": preferido}},
        secundario: {"2024-12-31": {"end": "2024-12-31", "val": 2.0, "filed": FILED_25, "_concept": secundario}},
    }
    assert ingestion._merge_for_metric(by_concept, metric)["2024-12-31"]["val"] == 1.0
    assert edgartools_facts.merge_entries(by_concept, metric)["2024-12-31"]["val"] == 1.0
