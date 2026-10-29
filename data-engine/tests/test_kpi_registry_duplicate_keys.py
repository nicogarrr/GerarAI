"""El registro de KPIs no puede crear dos filas con la misma metric_key.

Dos etiquetas del marco que normalizan a la misma clave (p. ej. «ARR» en los
drivers de ingresos y «arr» en los KPIs del marco software_ai) creaban dos
CompanyKPI pendientes: la sesión no hace autoflush, así que la segunda búsqueda
no veía la primera y el flush rompía la restricción UNIQUE → 500 en
POST /api/companies/{ticker}/kpi-registry/sync la primera vez para NVDA.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, CompanyKPI, Tenant
from app.services import kpi_extraction_service
from app.services.kpi_extraction_service import CompanyKPIRegistryService


def _tenant_session():
    init_db()
    db = SessionLocal()
    tenant = Tenant(external_id=f"kpi-dup-{uuid4().hex[:8]}")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    return db


def _company(db) -> Company:
    ticker = f"KD{uuid4().hex[:5].upper()}"
    company = Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD", sector="Technology",
                      industry="Semiconductors", company_type="standard", valuation_model="standard_dcf")
    db.add(company)
    db.commit()
    return company


def test_labels_sharing_a_metric_key_create_one_row(monkeypatch):
    framework = SimpleNamespace(key="software_ai", revenue_drivers=["ARR"], kpis=["arr", "Net revenue retention"],
                                required_fact_metrics=["net-revenue-retention"])
    monkeypatch.setattr(kpi_extraction_service, "resolve_company_framework", lambda _company: framework)
    db = _tenant_session()
    try:
        company = _company(db)
        rows = CompanyKPIRegistryService().sync(db, company)
        keys = [row.metric_key for row in rows]
        assert sorted(keys) == ["arr", "net_revenue_retention"]
        stored = db.scalars(select(CompanyKPI.metric_key).where(CompanyKPI.company_id == company.id)).all()
        assert sorted(stored) == ["arr", "net_revenue_retention"]
        by_key = {row.metric_key: row for row in rows}
        # La primera etiqueta manda en el nombre; el rol y el «required» se conservan.
        assert by_key["arr"].driver_type == "revenue_driver"
        assert by_key["net_revenue_retention"].required is True
        # Idempotente: una segunda sincronización no duplica nada.
        again = CompanyKPIRegistryService().sync(db, company)
        assert sorted(row.metric_key for row in again) == ["arr", "net_revenue_retention"]
    finally:
        db.close()


def test_real_frameworks_have_no_colliding_rows():
    """Con el marco real de cada empresa del maestro, la sincronización no rompe."""
    from app.data.company_master import COMPANY_MASTER
    from app.seed import ensure_company_master

    db = _tenant_session()
    try:
        ensure_company_master()
        tickers = [payload["ticker"] for payload in COMPANY_MASTER]
        for company in db.scalars(select(Company).where(Company.ticker.in_(tickers))):
            rows = CompanyKPIRegistryService().sync(db, company)
            keys = [row.metric_key for row in rows]
            assert len(keys) == len(set(keys)), (company.ticker, keys)
    finally:
        db.close()
