"""El ultimo run de una metrica manda: un run viejo con status ok NO resucita
una metrica que el run mas reciente declaro no creible.

CHTR (prod, 4-nov-2026): el run 92011 del WACC salio unavailable
(capital_amounts_scale_mismatch: market_cap legado con unit="decimal") y el
lector del modelo de largo plazo servia el run 49549 (ok, WACC 1,72 % < g)
porque filtraba ``value IS NOT NULL`` y ordenaba por fecha. El rescue
silencioso deshace los gates de honestidad del motor: ausencia honesta (N/D)
antes que cifra stale.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, CalculatedMetric, Company
from app.services.long_term_model_service import _servable_latest_metric


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="CABLERA"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NMS", currency="USD",
        sector="Communication Services", industry="Telecom Services",
        company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _run(company, *, year, status, value):
    return CalculatedMetric(
        company_id=company.id,
        metric="wacc",
        value=None if value is None else Decimal(value),
        unit="decimal",
        period=f"{year}-12-31",
        fiscal_year=year,
        status=status,
        definition_version="wacc-v1",
        formula="wacc_test",
        source_fact_ids=[],
        calculation_trace={},
    )


def test_run_viejo_ok_no_rescata_un_run_nuevo_unavailable(db):
    company = _company(db)
    db.add_all([
        _run(company, year=2024, status="ok", value="0.09"),
        _run(company, year=2025, status="unavailable", value=None),
    ])
    db.commit()

    assert _servable_latest_metric(db, company.id, "wacc") is None


def test_run_viejo_ok_tampoco_rescata_un_run_nuevo_error_sin_valor(db):
    company = _company(db)
    db.add_all([
        _run(company, year=2024, status="ok", value="0.09"),
        _run(company, year=2025, status="ok", value=None),
    ])
    db.commit()

    assert _servable_latest_metric(db, company.id, "wacc") is None


def test_ultimo_run_ok_se_sirve(db):
    company = _company(db)
    db.add_all([
        _run(company, year=2024, status="ok", value="0.09"),
        _run(company, year=2025, status="ok", value="0.11"),
    ])
    db.commit()

    served = _servable_latest_metric(db, company.id, "wacc")
    assert served is not None
    assert served.value == Decimal("0.11")
    assert served.fiscal_year == 2025


def test_sin_runs_no_hay_dato(db):
    company = _company(db)
    assert _servable_latest_metric(db, company.id, "wacc") is None
