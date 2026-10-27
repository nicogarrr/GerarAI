"""Un desbordamiento decimal no puede escapar de SafeFormula ni tumbar el run.

`SafeFormula.evaluate` solo re-lanzaba DivisionByZero / InvalidOperation como
ValueError. Una expresion con exponentes anidados dentro del limite (cada `**`
usa exponente 10, permitido) como `((((1e308 ** 10) ** 10) ** 10) ** 10)`
desborda el Emax del contexto decimal y soltaba `decimal.Overflow`: los
bucles de criterios y ranking y el aislamiento por empresa solo capturan
ValueError, asi que una sola pantalla con esa formula tumbaba la ejecucion
completa del screener (y el refresh de mercado que la dispara).

Ahora TODA senal decimal se normaliza a ValueError: el dato malo queda aislado
en UN outcome por criterio/compania y el resto del universo se evalua.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact, Tenant
from app.services.screener_service import SafeFormula, ScreenerService

# Cada `**` usa exponente 10 (bajo el limite), pero el valor encadenado supera
# el Emax del contexto decimal: desborda en la cuarta potencia.
OVERFLOW_EXPR = "((((1e308 ** 10) ** 10) ** 10) ** 10)"


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
        tenant = Tenant(external_id="formula-overflow", name="Formula overflow")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        ok = _company("OKCO")
        session.add(ok)
        session.flush()
        _fact(session, ok, "revenue", "100")
        session.commit()
        yield session


def test_evaluate_normalizes_decimal_overflow_to_value_error():
    """Antes: soltaba decimal.Overflow, que ningun llamador captura."""
    with pytest.raises(ValueError):
        SafeFormula(OVERFLOW_EXPR).evaluate({})


def test_overflow_in_criterion_is_per_item_unevaluable_and_does_not_raise(db: Session):
    # Antes de la correccion esto era un decimal.Overflow saliendo de run().
    response = ScreenerService().run(
        db, criteria=[{"left": OVERFLOW_EXPR, "operator": ">", "right": "0"}]
    )

    assert response["company_count"] == 1
    row = response["results"][0]
    assert row["criteria"][0]["status"] == "unevaluable"
    assert row["criteria"][0]["passed"] is False
    assert row["unevaluable_criteria"] == [OVERFLOW_EXPR]
    assert row["matched"] is False
    # La formula no usa variables: no hay campos ausentes que reportar.
    assert row["missing_fields"] == []


def test_overflow_in_ranking_keeps_the_company_matched(db: Session):
    """Mismo aislamiento en el RANKING: sin rank_value, pero sigue siendo match."""
    response = ScreenerService().run(
        db,
        criteria=[{"left": "revenue", "operator": ">=", "right": "0"}],
        ranking_formula=OVERFLOW_EXPR,
        ranking_direction="desc",
    )

    row = response["results"][0]
    assert row["rank_value"] is None
    assert row["ranking_status"] == "unevaluable"
    assert row["matched"] is True, "el ranking no puede quitarle la pertenencia"
    assert response["match_count"] == 1
