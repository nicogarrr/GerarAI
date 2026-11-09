"""ESEF shares import (_import_esef_shares): tagged IAS 33 shares win, profit/EPS
derivation covers the periods without them, and every figure lands with its
reporting flag, confidence and audit metadata.

No se prueba aqui: la fusion de periodos (_merge_esef_periods, ya cubierta en
test_esef_ingestion.py), la cuarentena de BPA (lista CONFLICTS vacia con LEI
sintetico), el reemplazo de datos previos (_replace_esef_data) ni el refresco
sin cambios. Todo sobre SQLite real en memoria, sin red: read_esef_snapshot
doblado con un snapshot sintetico.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import esef_shares
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
    engine.dispose()


def _company(db, ticker="ITX", name="Inditex"):
    company = Company(
        ticker=ticker, name=name, exchange="BME", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _dur(val, start, end, decimals=0):
    return {"start": start, "end": end, "val": str(val), "decimals": decimals, "lei": "L", "dims": []}


# Cinco ejercicios sinteticos: A con acciones etiquetadas (IAS 33), B y D con
# beneficio + BPA diluido (D con basico distinto: riesgo de ajuste en el
# numerador), C solo con BPA basico y E con BPA cero (descarte declarado).
SNAPSHOT = {
    "lei": "549300TTCXZOGZM2EY83",
    "ticker": "ITX",
    "entity_name": "INDUSTRIA DE DISENO TEXTIL, S.A.",
    "period_end": "2025-01-31",
    "fxo_id": "fxo-shares-1",
    "fetched_at": "2026-09-24",
    "facts": {
        "ifrs-full:AdjustedWeightedAverageShares": {"xbrli:shares": [
            _dur(3115000000, "2024-02-01", "2025-01-31"),
        ]},
        "ifrs-full:ProfitLossAttributableToOwnersOfParent": {"iso4217:EUR": [
            _dur(5870000000, "2024-02-01", "2025-01-31"),
            _dur(5390000000, "2023-02-01", "2024-01-31"),
            _dur(4820000000, "2022-02-01", "2023-01-31"),
            _dur(4400000000, "2021-02-01", "2022-01-31"),
            _dur(1000000000, "2020-02-01", "2021-01-31"),
        ]},
        "ifrs-full:DilutedEarningsLossPerShare": {"iso4217:EUR/xbrli:shares": [
            _dur("1.89", "2024-02-01", "2025-01-31", decimals=2),
            _dur("1.73", "2023-02-01", "2024-01-31", decimals=2),
            _dur("1.42", "2021-02-01", "2022-01-31", decimals=2),
            _dur("0.00", "2020-02-01", "2021-01-31", decimals=2),
        ]},
        "ifrs-full:BasicEarningsLossPerShare": {"iso4217:EUR/xbrli:shares": [
            _dur("1.89", "2024-02-01", "2025-01-31", decimals=2),
            _dur("1.73", "2023-02-01", "2024-01-31", decimals=2),
            _dur("1.55", "2022-02-01", "2023-01-31", decimals=2),
            _dur("1.40", "2021-02-01", "2022-01-31", decimals=2),
        ]},
    },
}


def _run_refresh(db, monkeypatch, snapshot):
    monkeypatch.setattr(
        ingestion.esef_connector, "read_esef_snapshot", lambda ticker: snapshot
    )
    company = _company(db)
    service = FinancialIngestionService()
    return company, asyncio.run(service.refresh_from_esef(db=db, company=company))


def _shares_facts(db, company_id, metric):
    rows = db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company_id,
            FinancialFact.metric == metric,
        )
    ).all()
    return {f.period: f for f in rows}


def _document(db):
    return db.scalars(select(Document)).one()


def test_acciones_etiquetadas_mandan_sobre_la_derivacion(db, monkeypatch):
    company, result = _run_refresh(db, monkeypatch, SNAPSHOT)
    assert result["status"] == "ingested"
    diluted = _shares_facts(db, company.id, "shares_diluted")
    # El cierre etiquetado se publica tal cual, una sola vez y como reportado.
    tagged = diluted["2025-01-31:FY"]
    assert tagged.value == Decimal("3115000000")
    assert tagged.is_reported is True
    assert tagged.confidence == Decimal("0.95")
    assert tagged.fiscal_year == 2025
    assert tagged.fiscal_quarter == "FY"
    assert tagged.unit == "shares"
    assert tagged.source_type == "ESEF"


def test_derivacion_diluida_sin_riesgo_y_con_riesgo(db, monkeypatch):
    company, _ = _run_refresh(db, monkeypatch, SNAPSHOT)
    diluted = _shares_facts(db, company.id, "shares_diluted")
    # B: basico == diluido -> sin riesgo, confianza plena de derivada.
    plain = diluted["2024-01-31:FY"]
    assert plain.value == Decimal("3115606936")
    assert plain.is_reported is False
    assert plain.confidence == Decimal("0.7")
    assert plain.fiscal_year == 2024
    # D: basico difiere del diluido mas alla del redondeo -> riesgo declarado.
    risky = diluted["2022-01-31:FY"]
    assert risky.value == Decimal("3098591549")
    assert risky.is_reported is False
    assert risky.confidence == Decimal("0.6")
    assert risky.fiscal_year == 2022
    # E: BPA cero -> ni etiquetada ni derivada.
    assert "2021-01-31:FY" not in diluted
    # Ningun cierre tiene dos shares_diluted (etiquetada + derivada).
    assert len(diluted) == 3


def test_fallback_basico_en_metrica_informativa(db, monkeypatch):
    company, _ = _run_refresh(db, monkeypatch, SNAPSHOT)
    basic = _shares_facts(db, company.id, "shares_basic_derived")
    assert set(basic) == {"2023-01-31:FY"}
    fact = basic["2023-01-31:FY"]
    assert fact.value == Decimal("3109677419")
    assert fact.is_reported is False
    assert fact.confidence == Decimal("0.6")
    assert fact.fiscal_year == 2023
    assert fact.unit == "shares"


def test_metadata_declara_formula_derivadas_y_descartes(db, monkeypatch):
    company, _ = _run_refresh(db, monkeypatch, SNAPSHOT)
    meta = _document(db).metadata_["esef_shares"]
    assert meta["formula"] == esef_shares.DERIVATION_FORMULA
    assert meta["diluted_metric"] == "shares_diluted"
    assert meta["basic_metric"] == "shares_basic_derived"
    assert meta["dcf_accepts"] == "shares_diluted"
    assert meta["approximate"] is True
    derived = {d["period"]: d for d in meta["derived"]}
    # El cierre con acciones etiquetadas NO aparece como derivado.
    assert set(derived) == {"2024-01-31", "2023-01-31", "2022-01-31"}
    assert derived["2024-01-31"]["lane"] == "diluted"
    assert derived["2024-01-31"]["shares"] == "3115606936"
    assert derived["2024-01-31"]["numerator_adjustment_risk"] is False
    assert derived["2022-01-31"]["lane"] == "diluted"
    assert derived["2022-01-31"]["numerator_adjustment_risk"] is True
    assert derived["2023-01-31"]["lane"] == "basic"
    assert derived["2023-01-31"]["eps"] == "1.55"
    skipped = {(s["period"], s["lane"], s["reason"]) for s in meta["skipped"]}
    assert skipped == {("2021-01-31", "diluted", "bpa_cero")}


def test_ingesta_sin_conceptos_de_acciones_no_crea_hechos(db, monkeypatch):
    snapshot = {
        **SNAPSHOT,
        "facts": {
            "ifrs-full:ProfitLossAttributableToOwnersOfParent": {
                "iso4217:EUR": [_dur(5870000000, "2024-02-01", "2025-01-31")]
            },
        },
    }
    company, result = _run_refresh(db, monkeypatch, snapshot)
    assert result["status"] == "ingested"
    assert _shares_facts(db, company.id, "shares_diluted") == {}
    assert _shares_facts(db, company.id, "shares_basic_derived") == {}
    meta = _document(db).metadata_["esef_shares"]
    assert meta["derived"] == []
    assert meta["skipped"] == []
