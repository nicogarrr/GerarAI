"""Cache/cursor del universo con SQL SQLite real y cálculos inyectados sin red."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, CalculatedMetric, Company, MarketPrice, Tenant
from app.services import valuation_metrics_service as svc
from app.services.connectors.base import UpstreamRateLimited

AS_OF = date(2026, 11, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all([Tenant(id=1, external_id="universe1"), Tenant(id=2, external_id="universe2")])
            db.flush()
            db.info["tenant_id"] = 1
            for ticker in ["AAA", "BBB"]:
                company = Company(
                    ticker=ticker,
                    name=ticker,
                    currency="USD",
                    exchange="NASDAQ",
                    company_type="operating",
                    valuation_model="unassigned",
                )
                db.add(company)
            db.commit()
            yield db
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "kind,skipped",
    [
        ("complete", 1),
        ("partial", 0),
        ("old", 0),
        ("other_period", 0),
        ("other_version", 0),
        ("other_tenant", 0),
    ],
)
def test_refresh_solo_salta_conjunto_completo_fresco_del_tenant(db, monkeypatch, kind, skipped):
    company = db.scalar(select(Company).where(Company.ticker == "AAA"))
    if kind == "other_tenant":
        db.info["tenant_id"] = 2
    for metric in [svc.METRIC_PB, svc.METRIC_YIELD]:
        if kind == "partial" and metric == svc.METRIC_YIELD:
            continue
        db.add(
            CalculatedMetric(
                tenant_id=2 if kind == "other_tenant" else 1,
                company_id=company.id,
                metric=metric,
                value=1,
                formula="test",
                period="2026-11-08" if kind == "other_period" else AS_OF.isoformat(),
                definition_version="old" if kind == "other_version" else svc.METRIC_VERSION,
                updated_at=datetime.now(UTC) - timedelta(hours=25 if kind == "old" else 1),
            )
        )
    db.commit()
    db.info["tenant_id"] = 1
    seen = []

    def compute(db_arg, companies, **kwargs):
        assert db_arg is db and kwargs["commit_per_company"] is True
        seen.extend(c.ticker for c in companies)
        return {"test_count": len(companies)}

    monkeypatch.setattr(svc, "compute_valuation_metrics", compute)
    result = svc.refresh_valuation_metrics(db, as_of=AS_OF)
    assert result["companies"] == 2 and result["companies_skipped_fresh_24h"] == skipped
    assert seen == (["BBB"] if skipped else ["AAA", "BBB"])
    seen.clear()
    result = svc.refresh_valuation_metrics(db, as_of=AS_OF, start_after_ticker="AAA")
    assert seen == ["BBB"] and result["companies"] == 1


def test_cuota_suspende_con_cursor_y_primera_empresa_confirmada(db):
    companies = list(db.scalars(select(Company).order_by(Company.ticker)))
    for company in companies:
        db.add(MarketPrice(company_id=company.id, date=AS_OF, close=Decimal(10), quote_currency="USD"))
    db.commit()
    called = []

    def finnhub(ticker):
        called.append(ticker)
        if ticker == "BBB":
            raise UpstreamRateLimited("local429", retry_after=123)
        return None

    with pytest.raises(svc.ValuationUniverseRateSuspended) as error:
        svc.compute_valuation_metrics(
            db,
            companies,
            as_of=AS_OF,
            commit_per_company=True,
            dividend_fetcher=lambda symbol: [],
            finnhub_yield_fetcher=finnhub,
        )
    assert error.value.last_completed_ticker == "AAA" and error.value.retry_after == 123
    assert isinstance(error.value.__cause__, UpstreamRateLimited)
    db.rollback()
    rows = db.scalars(select(CalculatedMetric)).all()
    assert len(rows) == 1 and rows[0].company_id == companies[0].id
    assert rows[0].metric == svc.METRIC_YIELD and rows[0].value == 0
    assert called == ["AAA", "BBB"]


def test_plazo_expirado_entre_empresas_usa_cursor_ultimo_visto(db):
    companies = list(db.scalars(select(Company).order_by(Company.ticker)))
    with pytest.raises(svc.ValuationTimeBudgetExhausted) as error:
        svc.compute_valuation_metrics(
            db,
            companies,
            as_of=AS_OF,
            commit_per_company=True,
            dividend_fetcher=lambda symbol: [],
            finnhub_yield_fetcher=lambda ticker: None,
            deadline=SimpleNamespace(expired=lambda: True),
        )
    assert error.value.last_completed_ticker == "AAA"  # sin precio se saltó, pero fue vista
