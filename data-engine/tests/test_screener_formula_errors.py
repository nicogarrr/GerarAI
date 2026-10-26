"""Una fórmula que no se puede evaluar no puede tumbar el universo entero.

`SafeFormula.evaluate` re-lanza la división por cero como
`ValueError("Formula cannot be evaluated for these values")`. El bucle de
criterios sólo capturaba `MissingVariables`, así que una sola compañía con
`revenue == 0` bajo un criterio como `free_cash_flow / revenue > 0.1` sacaba el
`ValueError` fuera de `run()`.

Consecuencias: la ruta ad-hoc respondía 400, `POST /api/screeners/{id}/run`
respondía 500 y —peor— `market_refresh_service` llamaba a `run_saved` sin
guarda, de modo que `POST /api/portfolio/refresh-market` devolvía 500 en esa
etapa DESPUÉS de haber confirmado precios, FX, revaloración y snapshot.

Aquí el dato malo se aísla en UN outcome por criterio/compañía (`unevaluable`),
el resto del universo se evalúa con normalidad, y un refresh no se cae por una
pantalla rota.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Company, FinancialFact, MarketPrice, Portfolio, Position, SavedScreen, Tenant
from app.services.connectors.ecb import ECBRates
from app.services.market_refresh_service import MarketRefreshService, PriceObservation
from app.services.screener_service import SafeFormula, ScreenerService

# `free_cash_flow / revenue` con revenue == 0 es DivisionByZero dentro de
# SafeFormula: exactamente el caso que antes escapaba como ValueError.
CRITERION = {"left": "free_cash_flow / revenue", "operator": ">", "right": "0.1"}


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _fact(db: Session, company: Company, metric: str, value: str, year: int = 2025) -> None:
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(value),
            unit="USD",
            period=f"FY{year}",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type="sec_filing",
            confidence=Decimal("0.9"),
        )
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="formula-errors", name="Formula errors")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _seed(db: Session) -> tuple[Company, Company]:
    """ZERO: revenue == 0 (fórmula inejecutable). OK: revenue == 100 (fcf_margin 0.2)."""
    zero = _company("ZERO")
    ok = _company("OKCO")
    db.add_all([zero, ok])
    db.flush()
    _fact(db, zero, "free_cash_flow", "10")
    _fact(db, zero, "revenue", "0")
    _fact(db, ok, "free_cash_flow", "20")
    _fact(db, ok, "revenue", "100")
    db.commit()
    return zero, ok


def test_zero_denominator_yields_per_item_unevaluable_and_does_not_raise(db: Session):
    zero, ok = _seed(db)

    # Antes de la corrección esto era una ValueError sin capturar saliendo de run().
    response = ScreenerService().run(db, criteria=[CRITERION])

    assert response["company_count"] == 2, "una compañía mala no puede borrar el universo"
    zero_row = next(r for r in response["results"] if r["ticker"] == "ZERO")
    ok_row = next(r for r in response["results"] if r["ticker"] == "OKCO")

    # Outcome por criterio para ESE item, no excepción para toda la corrida.
    assert zero_row["criteria"][0]["status"] == "unevaluable"
    assert zero_row["criteria"][0]["passed"] is False
    assert zero_row["unevaluable_criteria"] == ["free_cash_flow / revenue"]
    assert zero_row["matched"] is False
    # Los campos EXISTEN: no faltan, no se pueden calcular. Cobertura honesta.
    assert zero_row["missing_fields"] == []
    assert zero_row["coverage_percent"] == 100.0

    # El resto del universo se evalúa con normalidad.
    assert "unevaluable_criteria" not in ok_row
    assert ok_row["criteria"][0]["passed"] is True
    assert ok_row["matched"] is True
    assert response["match_count"] == 1
    assert zero.id != ok.id


def test_unevaluable_ranking_keeps_the_company_matched(db: Session):
    """Mismo aislamiento en el RANKING: sin rank_value, pero sigue siendo match."""
    _seed(db)

    response = ScreenerService().run(
        db,
        criteria=[{"left": "revenue", "operator": ">=", "right": "0"}],
        ranking_formula="free_cash_flow / revenue",
        ranking_direction="desc",
    )

    zero_row = next(r for r in response["results"] if r["ticker"] == "ZERO")
    ok_row = next(r for r in response["results"] if r["ticker"] == "OKCO")

    assert zero_row["rank_value"] is None
    assert zero_row["ranking_status"] == "unevaluable"
    assert zero_row["matched"] is True, "el ranking no puede quitarle la pertenencia"
    # Sus campos de ranking existen, así que no se reportan como ausentes.
    assert zero_row["missing_fields"] == []
    assert ok_row["rank_value"] is not None
    assert response["match_count"] == 2


# --- El llamador: una pantalla rota no puede tumbar el refresh ya confirmado ---


class _FakePriceProvider:
    async def fetch(self, companies, *, as_of):
        return {
            company.ticker: PriceObservation(
                ticker=company.ticker,
                price=Decimal("100"),
                price_date=as_of,
                source="fake",
            )
            for company in companies
        }, []


class _FakeFXProvider:
    async def fetch(self, *, base_currency, quote_currencies):
        return ECBRates(
            rate_date=date(2026, 9, 22),
            rates={currency: Decimal("1.1") for currency in quote_currencies},
        )


def test_a_failing_saved_screen_does_not_500_the_refresh(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        company = Company(
            ticker="AAA", name="AAA", exchange="NASDAQ", currency="USD", sector="S",
            industry="I", company_type="holding", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(company)
        db.flush()
        db.add(
            Position(
                company_id=company.id, quantity=Decimal("10"), currency="USD",
                market_price=Decimal("90"), market_value=Decimal("900"),
            )
        )
        db.add(
            MarketPrice(
                company_id=company.id, date=date(2026, 9, 20),
                close=Decimal("95"), adj_close=Decimal("95"), source="seed",
            )
        )
        screen = SavedScreen(
            tenant_id="tenant-test",
            name="Broken",
            description="screen that explodes",
            criteria=[CRITERION],
            ranking_formula=None,
            ranking_direction="desc",
            alerts_enabled=False,
            active=True,
        )
        db.add(screen)
        db.commit()

        def _boom(self, db, screen):  # noqa: ARG001
            raise ValueError("Formula cannot be evaluated for these values")

        monkeypatch.setattr(ScreenerService, "run_saved", _boom)

        service = MarketRefreshService(
            price_provider=_FakePriceProvider(), fx_provider=_FakeFXProvider()
        )
        result = asyncio.run(service.refresh(db, as_of=date(2026, 9, 22)))

    # No 500: el refresh devuelve su informe.
    assert [stage["name"] for stage in result["stages"]] == [
        "update_prices",
        "update_fx",
        "revalue_positions",
        "update_risk",
        "evaluate_alerts",
    ]
    alerts_stage = result["stages"][4]
    assert alerts_stage["status"] == "partial"
    assert alerts_stage["saved_screens"] == 0
    assert alerts_stage["errors"][0]["saved_screen_id"] == screen.id
    assert "ValueError" in alerts_stage["errors"][0]["reason"]
    # Y no se esconde: el estado global tampoco puede salir "ok".
    assert result["status"] == "partial"
    assert result["screen_results"] == []


def test_a_failing_screen_does_not_discard_the_already_committed_prices(monkeypatch):
    """La pantalla es la ultima etapa: lo confirmado antes debe sobrevivir."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        db = session
        db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        company = Company(
            ticker="AAA", name="AAA", exchange="NASDAQ", currency="USD", sector="S",
            industry="I", company_type="holding", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(company)
        db.flush()
        db.add(
            Position(
                company_id=company.id, quantity=Decimal("10"), currency="USD",
                market_price=Decimal("90"), market_value=Decimal("900"),
            )
        )
        db.add(
            MarketPrice(
                company_id=company.id, date=date(2026, 9, 20),
                close=Decimal("95"), adj_close=Decimal("95"), source="seed",
            )
        )
        db.add(
            SavedScreen(
                tenant_id="tenant-test", name="Broken", description="",
                criteria=[CRITERION], ranking_formula=None,
                ranking_direction="desc", alerts_enabled=False, active=True,
            )
        )
        db.commit()

        def _boom(self, db, screen):  # noqa: ARG001
            raise RuntimeError("boom")

        monkeypatch.setattr(ScreenerService, "run_saved", _boom)
        service = MarketRefreshService(
            price_provider=_FakePriceProvider(), fx_provider=_FakeFXProvider()
        )
        result = asyncio.run(service.refresh(db, as_of=date(2026, 9, 22)))

        # La revaloracion ya estaba confirmada y sigue ahi.
        position = db.scalar(select(Position))
        assert position.market_price == Decimal("100")
        assert result["stages"][2]["portfolio_snapshot_id"] is not None
        assert db.scalars(
            select(MarketPrice).where(MarketPrice.date == date(2026, 9, 22))
        ).one().close == Decimal("100")


@pytest.mark.parametrize("expr", ["min()", "max()", "abs()", "abs(1, 2)", "min(1)", "max(xx)", "abs(xxx, yy)"])
def test_safe_formula_rejects_bad_arity_as_value_error_before_evaluating(expr):
    with pytest.raises(ValueError):
        SafeFormula(expr)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [("min(xx, 3)", "2"), ("max(xx, 3, 1)", "3"), ("abs(0 - xx)", "2"), ("min(abs(0 - xx), max(1, xx))", "2")],
)
def test_safe_formula_valid_arity_still_evaluates(expr, expected):
    assert SafeFormula(expr).evaluate({"xx": Decimal("2")}) == Decimal(expected)
