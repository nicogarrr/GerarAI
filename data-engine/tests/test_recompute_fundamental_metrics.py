"""Barrido bulk de CalculatedMetric: cobertura, cursor y errores por empresa.

Hermetico (SQLite fichero de tests, sin red): el actor corre en proceso con
SessionLocal apuntando a la BD de tests, igual que test_calculated_metrics.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select

import app.workers.dramatiq_app as workers
from app.core.database import SessionLocal, init_db
from app.models import CalculatedMetric, Company, FinancialFact, Tenant

TICKERS = ["TRF1", "TRF2", "TRF3"]
TENANT_EXT = "test-recompute-metrics"


def _cleanup() -> None:
    init_db()
    db = SessionLocal()
    try:
        companies = db.scalars(select(Company).where(Company.ticker.in_(TICKERS))).all()
        for company in companies:
            db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == company.id))
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.delete(company)
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == TENANT_EXT))
        if tenant is not None:
            db.delete(tenant)
        db.commit()
    finally:
        db.close()


def _tenant() -> tuple[int, str]:
    db = SessionLocal()
    try:
        tenant = Tenant(
            external_id=TENANT_EXT,
            name="Recompute test",
            status="active",
            metadata_={"created_by": "tester"},
        )
        db.add(tenant)
        db.commit()
        return tenant.id, "tester"
    finally:
        db.close()


def _company(db, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Software",
        industry="Application Software",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _fact(db, company, tenant_id: int, metric: str, value: str) -> None:
    db.add(
        FinancialFact(
            company_id=company.id,
            tenant_id=tenant_id,
            metric=metric,
            value=Decimal(value),
            unit="USD",
            period="2025-12-31:FY",
            fiscal_year=2025,
            fiscal_quarter="FY",
            source_type="SEC",
            is_reported=True,
            confidence=Decimal("0.95"),
        )
    )


def _seed() -> tuple[int, str]:
    tenant_id, user_id = _tenant()
    db = SessionLocal()
    try:
        db.info["tenant_id"] = tenant_id
        # TRF1: roe calculable (net_income + equity).
        c1 = _company(db, "TRF1")
        _fact(db, c1, tenant_id, "net_income", "100")
        _fact(db, c1, tenant_id, "total_equity", "800")
        # TRF2: solo revenue -> nada calculable, pero entra en el barrido.
        c2 = _company(db, "TRF2")
        _fact(db, c2, tenant_id, "revenue", "1000")
        # TRF3: sin hechos -> nunca debe entrar en el barrido.
        _company(db, "TRF3")
        db.commit()
    finally:
        db.close()
    return tenant_id, user_id


def test_sweep_computes_only_companies_with_facts() -> None:
    _cleanup()
    tenant_id, user_id = _seed()
    try:
        result = workers.recompute_fundamental_metrics(tenant_id, user_id, limit=10)
        assert result["companies_processed"] == 2  # TRF3 sin hechos queda fuera
        assert result["metric_statuses"].get("ok", 0) > 0
        assert result["errors"] == []
        db = SessionLocal()
        try:
            db.info["tenant_id"] = tenant_id
            c1 = db.scalar(select(Company).where(Company.ticker == "TRF1"))
            roe = db.scalar(
                select(CalculatedMetric).where(
                    CalculatedMetric.company_id == c1.id,
                    CalculatedMetric.metric == "roe",
                    CalculatedMetric.status == "ok",
                )
            )
            assert roe is not None
            assert roe.value == Decimal("0.12500000")  # 100/800, trazable
        finally:
            db.close()
    finally:
        _cleanup()


def test_cursor_pages_the_universe(monkeypatch) -> None:
    _cleanup()
    tenant_id, user_id = _seed()
    chained: list[dict] = []
    monkeypatch.setattr(
        workers.recompute_fundamental_metrics,
        "send",
        lambda *args, **kwargs: chained.append({"args": args, "kwargs": kwargs}),
    )
    try:
        first = workers.recompute_fundamental_metrics(tenant_id, user_id, limit=1)
        assert first["companies_processed"] == 1
        assert first["next_start_from"] == "TRF1"
        # El chunk lleno se auto-encola con el cursor (sin Redis en tests).
        assert chained and chained[0]["kwargs"]["start_from"] == "TRF1"
        second = workers.recompute_fundamental_metrics(
            tenant_id, user_id, start_from=first["next_start_from"], limit=10
        )
        assert second["companies_processed"] == 1  # solo queda TRF2
        assert second["next_start_from"] is None
        assert len(chained) == 1  # barrido agotado: no se encola nada mas
    finally:
        _cleanup()


def test_broken_company_does_not_stop_the_sweep(monkeypatch) -> None:
    _cleanup()
    tenant_id, user_id = _seed()
    from app.services.metric_calculation_service import MetricCalculationService as service_cls
    real_calculate_all = service_cls.calculate_all

    def explode_for_trf1(self, db, company, persist=True):
        if company.ticker == "TRF1":
            raise RuntimeError("boom")
        return real_calculate_all(self, db, company, persist=persist)

    monkeypatch.setattr(service_cls, "calculate_all", explode_for_trf1)
    try:
        result = workers.recompute_fundamental_metrics(tenant_id, user_id, limit=10)
        assert result["companies_processed"] == 1  # TRF2 se proceso
        assert [e["ticker"] for e in result["errors"]] == ["TRF1"]
        assert result["status"] == "partial"
    finally:
        _cleanup()
