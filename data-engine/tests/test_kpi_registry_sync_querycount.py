"""Regresion de rendimiento: sync del registro KPI lee UNA vez por compania.

El sync hacia un SELECT por etiqueta del marco (~12-20 por empresa y
documento) y justo despues cargaba TODAS las filas para desactivar las
obsoletas. La precarga unica sirve a ambos pasos (medido con harness:
28 -> 14 sentencias para 14 etiquetas). Este test fija el contrato: los
SELECT del sync no crecen con el numero de etiquetas.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.core.database import SessionLocal, init_db
from app.models import Company, CompanyKPI, Tenant
from app.services import kpi_extraction_service
from app.services.kpi_extraction_service import CompanyKPIRegistryService


def _tenant_session():
    init_db()
    db = SessionLocal()
    tenant = Tenant(external_id=f"kpi-qc-{uuid4().hex[:8]}")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    return db


def _company(db) -> Company:
    ticker = f"QC{uuid4().hex[:5].upper()}"
    company = Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                      sector="Technology", industry="Semiconductors",
                      company_type="standard", valuation_model="standard_dcf")
    db.add(company)
    db.commit()
    return company


def test_sync_selects_do_not_grow_with_label_count(monkeypatch):
    labels = [f"metric_{i}" for i in range(14)]
    framework = SimpleNamespace(key="qc_framework", revenue_drivers=labels[:4],
                                kpis=labels[4:], required_fact_metrics=[])
    monkeypatch.setattr(kpi_extraction_service, "resolve_company_framework",
                        lambda _company: framework)
    db = _tenant_session()
    selects = 0

    def count_selects(conn, cursor, statement, parameters, context, executemany):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    try:
        company = _company(db)
        # Una metrica obsoleta ya registrada: el sync debe desactivarla.
        db.add(CompanyKPI(company_id=company.id, metric_key="obsolete_metric",
                          display_name="Obsolete", aliases=[], canonical_unit="count",
                          driver_type="kpi", required=False, active=True,
                          registry_version="qc_framework-v1", metadata_={}))
        db.commit()
        event.listen(db.get_bind(), "before_cursor_execute", count_selects)
        try:
            rows = CompanyKPIRegistryService().sync(db, company, commit=False)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", count_selects)
        assert len(rows) == len(labels)
        assert selects <= 2, f"el sync hizo {selects} SELECT para {len(labels)} etiquetas (N+1)"
    finally:
        db.close()
