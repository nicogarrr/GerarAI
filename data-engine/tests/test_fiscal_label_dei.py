"""Año fiscal con la etiqueta del emisor (dei:DocumentFiscalYearFocus): ejercicios de 52/53 semanas.

Lowe's, Home Depot o Target nombran el ejercicio por el año en que EMPIEZA: el que cierra el 30-ene-2026
es su «fiscal 2025». Walmart o NVIDIA, por el año en que acaba: el que cierra el 31-ene-2026 es «fiscal
2026». La fecha no los distingue; el ``fy`` de companyfacts (DocumentFiscalYearFocus del filing) sí.
Antes los dos salían FY2026 y la guía «fiscal 2026» de Lowe's (cierre ene-2027) caía en un ejercicio ya
presentado.

Cifras reales copiadas del companyfacts de la SEC (9-nov-2026): Lowe's CIK 60667,
RevenueFromContractWithCustomerExcludingAssessedTax de sus 10-K de 2024, 2025 y 2026; Walmart CIK 104169,
Revenues de sus 10-K de 2025 y 2026. Sin red.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.fiscal_label import dei_label_offset, filing_offsets, label_offset_from_facts
from app.services.own_consensus import GuidanceRow, actuals_from_facts, build_cells, period_end

M = 1_000_000


def _e(start, end, val, fy, filed, accn):
    return {"start": start, "end": end, "val": val, "fy": fy, "fp": "FY", "form": "10-K", "filed": filed,
            "accn": accn}


LOW_REV = [  # RevenueFromContractWithCustomerExcludingAssessedTax, USD
    _e("2022-01-29", "2023-02-03", 97_059 * M, 2023, "2024-03-25", "0000060667-24-000033"),
    _e("2023-02-04", "2024-02-02", 86_377 * M, 2023, "2024-03-25", "0000060667-24-000033"),
    _e("2022-01-29", "2023-02-03", 97_059 * M, 2024, "2025-03-24", "0000060667-25-000049"),
    _e("2023-02-04", "2024-02-02", 86_377 * M, 2024, "2025-03-24", "0000060667-25-000049"),
    _e("2024-02-03", "2025-01-31", 83_674 * M, 2024, "2025-03-24", "0000060667-25-000049"),
    _e("2023-02-04", "2024-02-02", 86_377 * M, 2025, "2026-03-23", "0000060667-26-000029"),
    _e("2024-02-03", "2025-01-31", 83_674 * M, 2025, "2026-03-23", "0000060667-26-000029"),
    _e("2025-02-01", "2026-01-30", 86_286 * M, 2025, "2026-03-23", "0000060667-26-000029"),
]
LOW_ANCHORS = {"0000060667-24-000033": "2024-02-02", "0000060667-25-000049": "2025-01-31",
               "0000060667-26-000029": "2026-01-30"}
WMT_REV = [  # Revenues, USD
    _e("2024-02-01", "2025-01-31", 680_985 * M, 2025, "2025-03-14", "0000104169-25-000021"),
    _e("2024-02-01", "2025-01-31", 680_985 * M, 2026, "2026-03-13", "0000104169-26-000055"),
    _e("2025-02-01", "2026-01-31", 713_163 * M, 2026, "2026-03-13", "0000104169-26-000055"),
]
WMT_ANCHORS = {"0000104169-25-000021": "2025-01-31", "0000104169-26-000055": "2026-01-31"}


def _gaap(concept, entries):
    return {concept: {"units": {"USD": entries}}}


def test_desfase_dei_por_filing_propio():
    low = _gaap("RevenueFromContractWithCustomerExcludingAssessedTax", LOW_REV)
    assert [(str(end), off) for end, off, _ in filing_offsets(low)] == [
        ("2026-01-30", 1), ("2025-01-31", 1), ("2024-02-02", 1)]
    assert dei_label_offset(low) == 1
    assert dei_label_offset(_gaap("Revenues", WMT_REV)) == 0


def test_cierre_primera_semana_de_enero_y_sin_mayoria_quedan_en_cero():
    # EXEL: el 10-K que cierra el 2-ene-2026 es su FY2025 (año nominal = diciembre de 2025) → 0.
    exel = _gaap("Revenues", [_e("2025-01-04", "2026-01-02", 1, 2025, "2026-02-10", "a1"),
                              _e("2024-01-01", "2025-01-03", 1, 2024, "2025-02-10", "a2")])
    assert dei_label_offset(exel) == 0
    # CrowdStrike (companyfacts real): 10-K de 2023–2025 con fy = año − 1, el de 2026 corregido (FY2026
    # para el cierre 31-ene-2026). Manda el vigente: 0.
    crwd = _gaap("Revenues", [_e("2025-02-01", "2026-01-31", 1, 2026, "2026-03-10", "e1"),
                              _e("2024-02-01", "2025-01-31", 1, 2024, "2025-03-10", "e2"),
                              _e("2023-02-01", "2024-01-31", 1, 2023, "2024-03-07", "e3"),
                              _e("2022-02-01", "2023-01-31", 1, 2022, "2023-03-09", "e4")])
    assert dei_label_offset(crwd) == 0
    # Un filing mal etiquetado no cambia la convención; un desfase de −1 no se admite.
    noisy = _gaap("Revenues", [_e("2025-01-01", "2025-12-31", 1, 2024, "2026-02-10", "b1"),
                               _e("2024-01-01", "2024-12-31", 1, 2024, "2025-02-10", "b2"),
                               _e("2023-01-01", "2023-12-31", 1, 2023, "2024-02-10", "b3"),
                               _e("2022-01-01", "2022-12-31", 1, 2023, "2023-02-10", "b4")])
    assert dei_label_offset(noisy) == 0
    assert dei_label_offset({}) == 0
    # Cierre en diciembre con fy del año anterior (error de etiquetado del filer): no se admite.
    dec = _gaap("Revenues", [_e("2025-01-01", "2025-12-31", 1, 2024, "2026-02-10", "c1"),
                             _e("2024-01-01", "2024-12-31", 1, 2023, "2025-02-10", "c2")])
    assert dei_label_offset(dec) == 0
    # Hechos con fecha futura dentro del 10-K (coberturas a un año vista) no son el periodo del filing.
    fwd = _gaap("Revenues", [_e("2024-06-30", "2025-06-28", 1, 2025, "2025-08-15", "d1"),
                             _e("2025-06-29", "2026-06-27", 1, 2025, "2025-08-15", "d1"),
                             _e("2023-07-02", "2024-06-29", 1, 2024, "2024-08-15", "d2"),
                             _e("2024-06-30", "2025-06-28", 1, 2024, "2024-08-15", "d2")])
    assert [str(end) for end, _, _ in filing_offsets(fwd)] == ["2025-06-28", "2024-06-29"]
    assert dei_label_offset(fwd) == 0
    # Hechos ya guardados con la regla de siempre (año del cierre): desfase 0.
    assert label_offset_from_facts([("2026-01-30", 2026), ("2025-01-31", 2025)]) == 0
    assert label_offset_from_facts([("2026-01-30", 2025), ("2025-01-31", 2024), ("2024-02-02", 2024)]) == 1


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _ingest(db, ticker, cik, gaap, anchors, preexisting=()):
    company = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD", sector="S", industry="I",
                      company_type="quality", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    for fact in preexisting:
        fact.company_id = company.id
        fact.tenant_id = db.info["tenant_id"]
        db.add(fact)
    db.commit()

    class _FakeSEC:
        async def cik_for_ticker(self, _ticker):
            return cik

        async def company_facts(self, _cik):
            return {"cik": int(cik), "facts": {"us-gaap": gaap}}

        async def annual_report_anchors(self, _cik):
            return anchors

        async def index_accessions(self, _cik):
            return None

    original = ingestion.SECClient
    ingestion.SECClient = lambda *a, **k: _FakeSEC()
    try:
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    finally:
        ingestion.SECClient = original
    db.commit()
    rows = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                  FinancialFact.metric == "revenue",
                                                  FinancialFact.fiscal_quarter == "FY")).all()
    return {r.period: r.fiscal_year for r in rows}


def test_ingesta_lowes_etiqueta_el_ejercicio_como_su_10k(db):
    years = _ingest(db, "LOW", "0000060667",
                    _gaap("RevenueFromContractWithCustomerExcludingAssessedTax", LOW_REV), LOW_ANCHORS)
    # Antes: 2026, 2025, 2024 (año del cierre). Ahora el «fiscal 2025» de Lowe's es FY2025.
    assert years["2026-01-30:FY"] == 2025
    assert years["2025-01-31:FY"] == 2024
    assert years["2024-02-02:FY"] == 2023


def test_ejercicio_conservado_de_un_import_anterior_toma_la_misma_etiqueta(db):
    # Fila de un import antiguo (regla de siempre: año del cierre) que el nuevo import no re-autoriza.
    old = FinancialFact(metric="revenue", value=65_017 * M, unit="USD", period="2018-02-02:FY", fiscal_year=2018,
                        fiscal_quarter="FY", source_type="SEC", is_reported=True, is_adjusted=False,
                        confidence=0.95)
    years = _ingest(db, "LOW", "0000060667",
                    _gaap("RevenueFromContractWithCustomerExcludingAssessedTax", LOW_REV), LOW_ANCHORS, [old])
    assert years["2018-02-02:FY"] == 2017
    assert years["2026-01-30:FY"] == 2025


def test_ingesta_walmart_sigue_con_el_año_del_cierre(db):
    years = _ingest(db, "WMT", "0000104169", _gaap("Revenues", WMT_REV), WMT_ANCHORS)
    assert years["2026-01-31:FY"] == 2026
    assert years["2025-01-31:FY"] == 2025


def test_consenso_propio_usa_la_etiqueta_y_la_guia_cae_en_su_ejercicio():
    rows = [("2026-01-30:FY", 86_286.0, date(2026, 3, 23), None, 2025),
            ("2025-01-31:FY", 83_674.0, date(2025, 3, 24), None, 2024),
            ("2024-02-02:FY", 86_377.0, date(2025, 3, 24), None, 2023)]
    acts = actuals_from_facts(rows, metric="revenue")
    assert sorted(acts) == ["fy2023", "fy2024", "fy2025"]
    assert period_end("fy2026", 1, 1) == date(2027, 1, 31)
    # Sin fiscal_year (filas antiguas): claves por el año nominal del cierre, como siempre.
    legacy = actuals_from_facts([r[:4] for r in rows], metric="revenue")
    assert sorted(legacy) == ["fy2024", "fy2025", "fy2026"]
    # Guía «fiscal 2026» publicada en feb-2026: es el ejercicio que cierra en ene-2027, aún sin presentar.
    guide = GuidanceRow("revenue", "fy2026", 92_000.0, 93_000.0, 94_000.0, date(2026, 2, 25), None, "fiscal 2026")
    cells = build_cells("revenue", acts, today=date(2026, 11, 9), guidance=[guide])
    assert "fy2026" in cells
    assert cells["fy2026"].end == date(2027, 1, 31)
    assert cells["fy2026"].published is not None and cells["fy2026"].published.source == "guia"
