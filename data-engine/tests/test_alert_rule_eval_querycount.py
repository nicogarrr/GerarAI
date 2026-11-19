"""Presupuesto de consultas de evaluate_all para reglas de precio (regresion N+1).

El scheduler encola evaluate_alert_rules cada 5 min por tenant. Cada regla
de precio repetia el SELECT de los ultimos 2 cierres de su compania (600
reglas = 600 SELECTs por pasada); los cierres de TODAS las companias con
regla llegan ahora en UNA consulta (funcion ventana, mismo orden date desc
y tope 2 por compania).

Reloj: la frescura del ultimo cierre caduca a las 24 h del cierre de su
bolsa (16:00 America/New_York en NASDAQ). Sembrar con ``date.today() - 1``
dejaba el test rojo entre esa caducidad y la medianoche local del runner
(rojo 3/3 del Piloto en 94cde2f3). La siembra toma sus fechas del reloj de
frescura congelado por la fixture ``freshness_clock``, asi el resultado no
depende de la hora ni de la zona horaria del runner.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import AlertRule, Base, Company, MarketPrice
from app.services.price_freshness import close_is_stale, session_close_at

N_COMPANIES = 8
N_RULES = 30


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def freshness_clock(monkeypatch):
    """Reloj de frescura fijo durante todo el test.

    ``close_is_stale`` consulta ``price_freshness._now``; congelarlo evita
    que el ultimo cierre sembrado caduque (o cambie la fecha de
    ``date.today()``) entre la siembra y la evaluacion.
    """
    from app.services import price_freshness

    now = datetime.now(UTC)
    monkeypatch.setattr(price_freshness, "_now", lambda: now)
    return now


def _latest_fresh_date(now: datetime) -> date:
    """Ultima sesion NASDAQ cuyo cierre es «actual» en ``now``.

    Lo decide la propia politica de frescura (techo #2884 intacto), no una
    suposicion del test sobre que dia toca.
    """
    for back in range(3):
        day = now.date() - timedelta(days=back)
        if not close_is_stale(day, "NASDAQ", 1, now=now):
            return day
    raise AssertionError(f"ningun cierre reciente es actual en {now}: reloj incoherente")


def _seed(db, *, latest: date, with_prices: bool = True):
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
                    date=latest - timedelta(days=d),
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


def test_evaluate_all_statement_budget(db, freshness_clock):
    from app.services.alert_rule_service import AlertRuleService

    _seed(db, latest=_latest_fresh_date(freshness_clock))
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


@pytest.mark.parametrize("offset_minutes", [-1, 1], ids=["antes_de_caducar", "tras_caducar"])
def test_statement_budget_around_freshness_boundary(db, monkeypatch, offset_minutes):
    """Misma pasada a ambos lados de la caducidad del cierre NASDAQ.

    La siembra sigue al reloj de frescura: un minuto antes de que el cierre
    de ``session_day`` cumpla 24 h y un minuto despues, las 30 reglas salen
    evaluated. Con la siembra anclada a un dia fijo anterior, la segunda
    mitad saldria skipped_stale_observation (el rojo de 94cde2f3).
    """
    from app.services import price_freshness
    from app.services.alert_rule_service import AlertRuleService

    session_day = date(2026, 11, 18)  # miercoles cualquiera con sesion
    boundary = session_close_at(session_day, "NASDAQ") + timedelta(hours=24)
    now = boundary + timedelta(minutes=offset_minutes)
    monkeypatch.setattr(price_freshness, "_now", lambda: now)

    _seed(db, latest=_latest_fresh_date(now))
    results = AlertRuleService().evaluate_all(db, skip_closed_markets=False)
    assert len(results) == N_RULES
    assert all(r["status"] == "evaluated" for r in results)


def test_prefetch_matches_per_rule_results(db, freshness_clock):
    """Misma observacion con precarga que con la consulta por regla."""
    from app.services.alert_rule_service import AlertRuleService

    _seed(db, latest=_latest_fresh_date(freshness_clock))
    results = AlertRuleService().evaluate_all(db, skip_closed_markets=False)
    by_id = {r["rule_id"]: r for r in results}
    rules = db.query(AlertRule).order_by(AlertRule.id).all()
    for rule in rules[:6]:  # mezcla de market_price y price_change_percent
        fresh = AlertRuleService().evaluate(db, rule, commit=False)  # sin precarga
        assert by_id[rule.id]["status"] == fresh["status"]
        assert by_id[rule.id]["matched"] == fresh["matched"]


def test_company_without_prices_stays_missing(db, freshness_clock):
    """Compania sin cierres: la precarga devuelve [] y el estado es missing."""
    from app.services.alert_rule_service import AlertRuleService

    _seed(db, latest=_latest_fresh_date(freshness_clock), with_prices=False)
    results = AlertRuleService().evaluate_all(db, skip_closed_markets=False)
    observations = {r["observation"]["status"] for r in results}
    assert observations <= {"missing", "missing_two_prices"}, observations
