"""Presupuesto de consultas de evaluate_all para reglas de precio (regresion N+1).

El scheduler encola evaluate_alert_rules cada 5 min por tenant. Cada regla
de precio repetia el SELECT de los ultimos 2 cierres de su compania (600
reglas = 600 SELECTs por pasada); los cierres de TODAS las companias con
regla llegan ahora en UNA consulta (funcion ventana, mismo orden date desc
y tope 2 por compania).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import AlertRule, Base, Company, MarketPrice

N_COMPANIES = 8
N_RULES = 30


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def _seed(db, *, with_prices: bool = True):
    db.info.update(tenant_id=1, user_id="owner")
    companies = []
    for c in range(N_COMPANIES):
        company = Company(
            ticker=f"CO{c}", name=f"Company {c}", exchange="NASDAQ", currency="USD",
            sector="S", industry="I", company_type="research_candidate",
            valuation_model="unassigned", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        companies.append(company)
        if with_prices:
            for d in range(5):
                db.add(MarketPrice(
                    company_id=company.id,
                    date=date.today() - timedelta(days=d + 1),
                    open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
                    close=Decimal("100") + Decimal(d), adj_close=None, volume=1000,
                    quote_currency="USD", source="yahoo",
                ))
    for r in range(N_RULES):
        company = companies[r % N_COMPANIES]
        kind = "market_price" if r % 2 == 0 else "price_change_percent"
        db.add(AlertRule(
            tenant_id=1, company_id=company.id, name=f"Regla {r}",
            rule_type="price", target={"kind": kind},
            condition={"operator": ">", "value": 99999999},  # nunca dispara
            severity="low", channels=["in_app"], active=True,
        ))
    db.commit()
    return companies


def test_evaluate_all_statement_budget(db):
    from app.services.alert_rule_service import AlertRuleService

    _seed(db)
    statements = 0

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        nonlocal statements
        statements += 1

    results = AlertRuleService().evaluate_all(db, skip_closed_markets=False)
    assert len(results) == N_RULES
    assert all(r["status"] == "evaluated" for r in results)
    # ANTES: 34 (un SELECT de cierres por regla). DESPUES: ~5 (precarga en
    # una consulta + lecturas fijas de la pasada).
    assert statements <= 20, f"N+1 por regla: {statements} sentencias"


def test_prefetch_matches_per_rule_results(db):
    """Misma observacion con precarga que con la consulta por regla."""
    from app.services.alert_rule_service import AlertRuleService

    _seed(db)
    results = AlertRuleService().evaluate_all(db, skip_closed_markets=False)
    by_id = {r["rule_id"]: r for r in results}
    rules = db.query(AlertRule).order_by(AlertRule.id).all()
    for rule in rules[:6]:  # mezcla de market_price y price_change_percent
        fresh = AlertRuleService().evaluate(db, rule, commit=False)  # sin precarga
        assert by_id[rule.id]["status"] == fresh["status"]
        assert by_id[rule.id]["matched"] == fresh["matched"]


def test_company_without_prices_stays_missing(db):
    """Compania sin cierres: la precarga devuelve [] y el estado es missing."""
    from app.services.alert_rule_service import AlertRuleService

    _seed(db, with_prices=False)
    results = AlertRuleService().evaluate_all(db, skip_closed_markets=False)
    observations = {r["observation"]["status"] for r in results}
    assert observations <= {"missing", "missing_two_prices"}, observations
