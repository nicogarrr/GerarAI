"""Market cap derivado (QA AENA/ASML): precio x acciones con fuente, como
respaldo cuando el proveedor no cubre; nunca pisa un market_cap de
proveedor fresco ni inventa acciones."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    CorporateAction,
    FinancialFact,
    MarketPrice,
    Tenant,
)
from app.services.derived_market_cap_service import refresh_derived_market_cap

TODAY = date(2026, 10, 19)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        session.add(Tenant(id=1, external_id="one"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _company(db, ticker="AENA", currency="EUR"):
    company = Company(
        ticker=ticker, name=ticker, exchange="BME", currency=currency,
        sector="S", industry="I", company_type="standard",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _price(db, company, close, day):
    db.add(MarketPrice(company_id=company.id, date=day, open=close, high=close,
                       low=close, close=close))


def _fact(db, company, metric, value, *, year=None, source="ESEF", reported=True):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="EUR", period=f"{year}-12-31:FY" if year else "2026-10-16",
        fiscal_year=year, fiscal_quarter="FY" if year else None,
        source_type=source, is_reported=reported, tenant_id=1,
    ))


def test_derived_from_reported_shares(db):
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=3))
    _fact(db, company, "shares_outstanding", 150_000_000, year=None, source="SEC")
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "ok"
    assert result["market_cap"] == pytest.approx(25.70 * 150_000_000)
    fact = db.scalar(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap"))
    assert fact.is_reported is False and fact.source_type == "derived"
    assert fact.unit == "EUR" and fact.period == (TODAY - timedelta(days=3)).isoformat()


def test_aena_case_shares_derived_from_net_income_over_eps(db):
    """AENA: sin conteo de acciones en ESEF; acciones = net_income/EPS del
    mismo ejercicio (10,87 EUR FY2023 real)."""
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=1))
    _fact(db, company, "net_income", 1_934_000_000, year=2024)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2024)
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "ok"
    assert "derived_net_income_over_eps FY2024" in result["shares_basis"]
    assert result["market_cap"] == pytest.approx(
        25.70 * (1_934_000_000 / 12.89), rel=1e-6)


def test_vendor_market_cap_never_overwritten(db):
    company = _company(db)
    day = TODAY - timedelta(days=1)
    _price(db, company, Decimal("25.70"), day)
    _fact(db, company, "shares_outstanding", 150_000_000, year=None, source="SEC")
    db.add(FinancialFact(
        company_id=company.id, metric="market_cap",
        value=Decimal("3900000000"), unit="EUR", period=day.isoformat(),
        source_type="FMP_profile", is_reported=True, tenant_id=1))
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "skipped"
    caps = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap")).all()
    assert len(caps) == 1 and caps[0].source_type == "FMP_profile"


def test_no_shares_no_cap_honest(db):
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=1))
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "unavailable" and result["reason"] == "no_shares"


def test_stale_price_no_cap(db):
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=30))
    _fact(db, company, "shares_outstanding", 150_000_000, year=None, source="SEC")
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "unavailable" and result["reason"] == "no_fresh_price"


def test_idempotent_rewrite(db):
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=1))
    _fact(db, company, "shares_outstanding", 150_000_000, year=None, source="SEC")
    db.commit()
    refresh_derived_market_cap(db, company, today=TODAY)
    refresh_derived_market_cap(db, company, today=TODAY)
    caps = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap")).all()
    assert len(caps) == 1


def test_watchlist_metrics_endpoint_reports_derived_cap_and_per(db):
    from datetime import timedelta as _td

    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - _td(days=1))
    _fact(db, company, "net_income", 1_934_000_000, year=2024)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2024)
    db.commit()
    refresh_derived_market_cap(db, company, today=TODAY)

    payload = watchlist_metrics("aena", db)
    assert payload["market_cap"] == pytest.approx(
        25.70 * (1_934_000_000 / 12.89), rel=1e-6)
    assert payload["per"] == pytest.approx(25.70 / 12.89, rel=1e-6)
    assert payload["currency"] == "EUR"
    assert any("derivada" in src for src in payload["sources"])


def test_watchlist_metrics_endpoint_derives_on_demand(db):
    # QA Tester 6 (19-oct-2026): el endpoint deriva el cap si el barrido
    # aún no lo escribió, sin llamada previa a refresh_derived_market_cap.
    from datetime import timedelta as _td

    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - _td(days=1))
    _fact(db, company, "net_income", 1_934_000_000, year=2024)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2024)
    db.commit()

    payload = watchlist_metrics("aena", db)
    assert payload["market_cap"] == pytest.approx(
        25.70 * (1_934_000_000 / 12.89), rel=1e-6)
    assert any("derivada" in src for src in payload["sources"])


def test_watchlist_metrics_endpoint_honest_nulls(db):
    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db, ticker="NODATA")
    db.commit()
    payload = watchlist_metrics("NODATA", db)
    assert payload == {"market_cap": None, "per": None,
                       "currency": "EUR", "sources": []}
    assert watchlist_metrics("UNKNOWN", db)["market_cap"] is None
def _split(db, company, effective, ratio):
    db.add(CorporateAction(
        company_id=company.id, action_type="split", ratio=Decimal(str(ratio)),
        effective_date=effective, description="test split",
    ))


def test_derived_cap_adjusted_for_split_after_period(db):
    """Caso real AENA (medido en prod 19-oct-2026): split 10:1 tras el
    FY2025; precio post-split x acciones derivadas pre-split daba el cap
    10x bajo (3,93B en vez de ~39,3B). El recuento se expresa en acciones
    actuales multiplicando por el factor acumulado, como el PER."""
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=3))
    _fact(db, company, "net_income", 1_972_000_000, year=2025)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2025)
    _split(db, company, TODAY - timedelta(days=2), 10)
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "ok"
    assert result["split_factor"] == 10
    assert "ajustadas por split x10" in result["shares_basis"]
    assert result["market_cap"] == pytest.approx(
        25.70 * (1_972_000_000 / 12.89) * 10, rel=1e-6)
    fact = db.scalar(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap"))
    assert fact.is_adjusted is True


def test_reported_shares_adjusted_for_split_after_dei(db):
    """Conteo reportado (SEC dei) con split posterior: tambien se expresa
    en acciones actuales, como la serie de long_term_model_service."""
    company = _company(db)
    _price(db, company, Decimal("60"), TODAY - timedelta(days=1))
    db.add(FinancialFact(
        company_id=company.id, metric="shares_outstanding",
        value=Decimal("150000000"), unit="shares", period="2026-06-30:DEI",
        source_type="SEC", is_reported=True, tenant_id=1,
    ))
    _split(db, company, date(2026, 8, 1), 4)
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "ok"
    assert result["market_cap"] == pytest.approx(60 * 600_000_000)
    assert "reported_shares_outstanding" in result["shares_basis"]
    assert "ajustadas por split x4" in result["shares_basis"]


def test_split_before_period_not_applied(db):
    """Split anterior al cierre del ejercicio del hecho: el recuento ya es
    post-split, factor 1 y nada que declarar."""
    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=1))
    _fact(db, company, "net_income", 1_972_000_000, year=2025)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2025)
    _split(db, company, date(2024, 1, 15), 10)
    db.commit()
    result = refresh_derived_market_cap(db, company, today=TODAY)
    assert result["status"] == "ok"
    assert result["split_factor"] == 1.0
    assert "ajustadas por split" not in result["shares_basis"]
    assert result["market_cap"] == pytest.approx(
        25.70 * (1_972_000_000 / 12.89), rel=1e-6)
    fact = db.scalar(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap"))
    assert fact.is_adjusted is False


def test_endpoint_declares_split_adjusted_derived_cap(db):
    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=3))
    _fact(db, company, "net_income", 1_972_000_000, year=2025)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2025)
    _split(db, company, TODAY - timedelta(days=2), 10)
    db.commit()
    payload = watchlist_metrics("aena", db)
    assert payload["market_cap"] == pytest.approx(
        25.70 * (1_972_000_000 / 12.89) * 10, rel=1e-6)
    assert any("acciones ajustadas por split" in src for src in payload["sources"])


def test_endpoint_refreshes_existing_derived_row(db):
    """Revisión auditor 19-oct-2026: un derivado antiguo erróneo no se sirve
    indefinidamente: la fila derivada se recalcula (con el ajuste de split
    ya aplicado) en cada lectura."""
    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=3))
    _fact(db, company, "net_income", 1_972_000_000, year=2025)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2025)
    _split(db, company, TODAY - timedelta(days=2), 10)
    # Derivado antiguo erróneo (valor imposible: debe ser reemplazado):
    db.add(FinancialFact(
        company_id=company.id, metric="market_cap",
        value=Decimal("999"), unit="EUR",
        period=(TODAY - timedelta(days=3)).isoformat(),
        source_type="derived", is_reported=False, tenant_id=1,
    ))
    db.commit()
    payload = watchlist_metrics("aena", db)
    assert payload["market_cap"] == pytest.approx(
        25.70 * (1_972_000_000 / 12.89) * 10, rel=1e-6)
    caps = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap")).all()
    assert len(caps) == 1  # idempotente: el derivado viejo se reemplaza


def test_endpoint_refresh_persists_committed(db):
    """Revisión auditor 19-oct-2026: get_db cierra cada request con
    rollback; sin commit explícito el derivado del GET no se persistía
    nunca. Tras la lectura, una sesión NUEVA ve el hecho."""
    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db)
    _price(db, company, Decimal("25.70"), TODAY - timedelta(days=3))
    _fact(db, company, "net_income", 1_972_000_000, year=2025)
    _fact(db, company, "eps_diluted", Decimal("12.89"), year=2025)
    db.commit()
    payload = watchlist_metrics("aena", db)
    assert payload["market_cap"] is not None
    engine = db.bind
    from sqlalchemy.orm import sessionmaker
    with sessionmaker(engine)() as fresh:
        caps = fresh.scalars(select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap")).all()
    assert len(caps) == 1 and caps[0].source_type == "derived"


def test_endpoint_never_rewrites_vendor_cap(db):
    """Un market_cap de proveedor NO se refresca ni se toca."""
    from app.api.routes.watchlist import watchlist_metrics

    company = _company(db)
    day = TODAY - timedelta(days=1)
    _price(db, company, Decimal("25.70"), day)
    _fact(db, company, "shares_outstanding", 150_000_000, year=None, source="SEC")
    db.add(FinancialFact(
        company_id=company.id, metric="market_cap",
        value=Decimal("3900000000"), unit="EUR", period=day.isoformat(),
        source_type="FMP_profile", is_reported=True, tenant_id=1))
    db.commit()
    payload = watchlist_metrics("aena", db)
    assert payload["market_cap"] == pytest.approx(3_900_000_000)
    caps = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "market_cap")).all()
    assert len(caps) == 1 and caps[0].source_type == "FMP_profile"
