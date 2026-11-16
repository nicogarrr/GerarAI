"""Cierre fiscal real en la precisión de firmas (Lote 2, hallazgo 1).

La regla prerregistrada exige «estimación publicada ANTES del cierre de ese
año», pero el código aproximaba el cierre al 31-dic: para ejercicios no
naturales (MSFT cierra en junio, WMT/NVDA en enero) una firma podía estimar a
toro pasado y maquillar su precisión. Ahora el corte usa la fecha real del
hecho SEC/ESEF (``<cierre>:FY``) cuando se conoce.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact, Tenant
from app.services import analyst_consensus as ac


def _hist(firm, year, value, day):
    return ac.FirmEstimate(firm, "revenue", year, value, day, f"https://n.example/{firm}/{day}")


def test_estimacion_tras_el_cierre_real_no_es_prevision():
    """FY2025 cierra 2025-06-30: una estimación de agosto cuenta como a toro pasado."""
    actuals = {2025: 100.0}
    ends = {2025: date(2025, 6, 30)}
    history = [_hist("Tardía", 2025, 100.0, date(2025, 8, 15)),
               _hist("Puntual", 2025, 110.0, date(2025, 6, 15))]
    errors = ac.firm_errors(history, actuals, year_ends=ends)
    assert "Tardía" not in errors
    assert errors["Puntual"] == [(2025, 0.10)]
    # Sin cierres reales se conserva el corte legado a 31-dic (compat).
    legacy = ac.firm_errors(history, actuals)
    assert "Tardía" in legacy


def test_backtest_respeta_el_cierre_real():
    actuals = {2022: 100.0, 2023: 120.0, 2024: 150.0}
    ends = {year: date(year, 6, 30) for year in actuals}
    history = []
    for year, real in actuals.items():
        history += [_hist("Precisa", year, real * 1.01, date(year, 5, 1)),
                    _hist("Media", year, real * 1.20, date(year, 5, 1)),
                    _hist("Tardía", year, real, date(year, 9, 1))]  # tras el cierre de junio
    check = ac.backtest(history, actuals, year_ends=ends)
    # Tardía fuera de la muestra: el backtest solo enfrenta Precisa y Media.
    assert check["status"] in {"validated", "rejected"} and check["years"] == 3
    assert all(row["firms"] == 2 for row in check["rows"])
    # Con corte a 31-dic la tardía entraba y el backtest la contaba:
    legacy = ac.backtest(history, actuals)
    assert all(row["firms"] == 3 for row in legacy["rows"])
    legacy_errors = ac.firm_errors(history, actuals)
    assert "Tardía" in legacy_errors and "Tardía" not in ac.firm_errors(history, actuals, year_ends=ends)


@pytest.fixture()
def tenant_company():
    init_db()
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"acye-{suffix}", name="acye")
        company = Company(ticker=f"AY{suffix}", name="Acme Fiscal, Inc.", exchange="NASDAQ", currency="USD",
                          company_type="operating", valuation_model="standard_dcf")
        db.add_all([tenant, company])
        db.commit()
        ids = (company.id, tenant.id)
    yield ids
    with SessionLocal() as db:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == ids[0]))
        db.execute(delete(Company).where(Company.id == ids[0]))
        db.execute(delete(Tenant).where(Tenant.id == ids[1]))
        db.commit()


def test_revenue_year_ends_desde_el_periodo_del_hecho(tenant_company):
    company_id, tenant_id = tenant_company
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        db.add_all([
            FinancialFact(tenant_id=tenant_id, company_id=company_id, metric="revenue",
                          value=Decimal("41400000000"), period="2025-06-30:FY", fiscal_year=2025,
                          source_type="sec"),
            FinancialFact(tenant_id=tenant_id, company_id=company_id, metric="revenue",
                          value=Decimal("38000000000"), period="periodo-roto:FY", fiscal_year=2024,
                          source_type="sec"),
            FinancialFact(tenant_id=tenant_id, company_id=company_id, metric="ebitda",
                          value=Decimal("1000000000"), period="2025-06-30:FY", fiscal_year=2025,
                          source_type="sec"),
        ])
        db.commit()
        company = db.get(Company, company_id)
        ends = ac.revenue_year_ends(db, company)
        revenue = ac.reported_revenue(db, company)
    assert ends[2025] == date(2025, 6, 30)          # cierre real de junio
    assert ends[2024] == date(2024, 12, 31)         # periodo ilegible: 31-dic declarado
    assert revenue == {2025: 41400.0, 2024: 38000.0}  # millones, solo revenue
