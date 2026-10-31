"""Cuarentena ESEF / elegibilidad en las lecturas directas de los motores.

El snapshot del DCF (``financial_snapshot._facts_for_metric``) filtra los
hechos en cuarentena ESEF y los no elegibles (``eligible_fact``), igual que
watchlist, TTM, screener y market cap derivado. Las rutas directas de
``fact_reference.latest_facts`` (múltiplos relativos, DDM/FCFE) y de los
motores sectoriales/SOTP leían la fila cruda: para EBRO el ``eps_diluted``
1351 en cuarentena (escala x1000 frente al informe anual) alimentaba un PER
por múltiplos aunque la cuarentena declara «no se calcula el PER», y unas
acciones derivadas en cuarentena alimentaban el P/B bancario.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, FinancialFact
from app.services.esef_fact_quarantine import EBRO_LEI
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.relative_multiples import _fundamentals
from app.valuation.engines.sector_specific import BankValuationEngine
from app.valuation.fact_reference import latest_facts


class _Snap:
    coherent = False
    as_of_period = None
    income_statement = None
    balance_sheet = None
    shares_period = None
    warnings: list = []
    facts: dict = {}
    missing_inputs: list = []
    excluded_present: list = []

    def __init__(self, values=None):
        self._v = values or {}

    def value(self, metric):
        return self._v.get(metric)

    def fact_ids(self):
        return {}

    def periods(self):
        return {}


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    company = Company(ticker="EBRO", name="Ebro", exchange="BME", currency="EUR",
                      company_type="bank", valuation_model="bank_residual_income",
                      special_sources=[], special_risks=[], factor_tags=[])
    s.add(company)
    s.flush()
    return s, company


def _esef_source(db, company, **metadata):
    meta = {"lei": EBRO_LEI}
    meta.update(metadata)
    source = Document(company_id=company.id, title="ESEF EBRO", source_type="ESEF", metadata_=meta)
    db.add(source)
    db.flush()
    return source


def _fact(db, company, metric, value, *, year, source=None, source_type="SEC",
          period=None, is_reported=True, quarter="FY"):
    row = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="EUR/share" if "eps" in metric else "EUR",
        period=period or f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter=quarter,
        source_id=source.id if source else None, source_type=source_type,
        is_reported=is_reported, confidence=Decimal("0.9"))
    db.add(row)
    return row


def _quarantined_eps(db, company, *, year=2025):
    """eps_diluted ESEF 1351 (x1000) = conflicto revisado EBRO FY2024."""
    source = _esef_source(db, company)
    return _fact(db, company, "eps_diluted", "1351", year=year, source=source,
                 source_type="ESEF", period="2025-01-01:FY")


def test_latest_facts_salta_cuarentena_y_usa_el_limpio_anterior():
    db, company = _db()
    _quarantined_eps(db, company)                                    # FY2025, envenenado
    _fact(db, company, "eps_diluted", "1.215", year=2024)            # FY2024, limpio
    db.commit()
    found = latest_facts(db, company.id, ["eps_diluted"])
    assert found["eps_diluted"].value == pytest.approx(1.215)
    assert found["eps_diluted"].period == "2024-12-31:FY"


def test_latest_facts_solo_cuarentena_es_ausente_no_envenenado():
    db, company = _db()
    _quarantined_eps(db, company)
    db.commit()
    assert latest_facts(db, company.id, ["eps_diluted"]) == {}


def test_latest_facts_ajuste_pdf_no_revisado_no_es_elegible():
    db, company = _db()
    _fact(db, company, "eps_diluted", "1.40", year=2025,
          source_type="REVIEWED_PDF_ADJUSTMENT", is_reported=False)  # sin revisar
    _fact(db, company, "eps_diluted", "1.215", year=2024)
    db.commit()
    found = latest_facts(db, company.id, ["eps_diluted"])
    assert found["eps_diluted"].value == pytest.approx(1.215)


def test_fundamentos_multiplos_no_construyen_eps_desde_cuarentena():
    db, company = _db()
    _quarantined_eps(db, company)
    db.commit()
    fundamentals = _fundamentals(db, company.id)
    assert "eps" not in fundamentals  # sin eps limpio: PER N/D, nunca 1351


def test_banco_rechaza_acciones_derivadas_en_cuarentena():
    """P/B con shares_diluted derivadas del BPA envenenado: N/D, no valoración."""
    db, company = _db()
    source = _esef_source(
        db, company,
        esef_shares={"derived": [{"period": "2025-01-01", "eps": "1351", "shares": "153865"}]},
    )
    _fact(db, company, "tangible_book_value", "1000000", year=2025)
    _fact(db, company, "roe", "0.14", year=2025)
    _fact(db, company, "cost_of_equity", "0.10", year=2025)
    _fact(db, company, "book_value_growth", "0.04", year=2025)
    _fact(db, company, "shares_diluted", "153865", year=2025, source=source,
          source_type="ESEF", period="2025-01-01:FY", is_reported=False)
    db.commit()
    result = BankValuationEngine().value(ValuationContext(
        db=db, company=company, snapshot=_Snap(), current_price=10.0, engine_key="bank"))
    assert result["status"] == "insufficient_data"
    assert "shares_diluted" in result["missing_inputs"]


def test_banco_con_acciones_limpias_valora_normal():
    db, company = _db()
    _fact(db, company, "tangible_book_value", "1000000", year=2025)
    _fact(db, company, "roe", "0.14", year=2025)
    _fact(db, company, "cost_of_equity", "0.10", year=2025)
    _fact(db, company, "book_value_growth", "0.04", year=2025)
    _fact(db, company, "shares_diluted", "100000", year=2025)
    db.commit()
    result = BankValuationEngine().value(ValuationContext(
        db=db, company=company, snapshot=_Snap(), current_price=10.0, engine_key="bank"))
    assert result["status"] == "ok"
    # libro/acción = 10; P/B base = (0,14-0,04)/(0,10-0,04) = 1,6667
    assert result["base_value"] == pytest.approx(10 * 0.10 / 0.06)
