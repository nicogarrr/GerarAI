"""Criterios de invalidacion estructurados de la tesis -> aviso automatico.

Los criterios de texto libre no se pueden evaluar. Un criterio estructurado
(metrica, operador, umbral) guardado en la tesis se sincroniza como AlertRule
`thesis_invalidation` y el evaluador de alertas existente lo comprueba en cada
pasada: si salta, crea un aviso. Sin dato (o con precio caducado) no salta.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AlertRule,
    Base,
    CalculatedMetric,
    Company,
    MarketPrice,
    ResearchAlert,
    ThesisVersion,
)
from app.services.alert_rule_service import AlertRuleService
from app.services.thesis_invalidation_rules import (
    RULE_TYPE,
    normalize_rules,
    sync_thesis_rules,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "POOL") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Industrials", industry="Distribution", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _price(db: Session, company: Company, close: str, *, day: date | None = None) -> None:
    value = Decimal(close)
    db.add(MarketPrice(
        company_id=company.id, date=day or date.today(), open=value, high=value,
        low=value, close=value, adj_close=value, source="test",
    ))
    db.commit()


def _thesis(db: Session, company: Company, *, version: int = 1, rules=None,
            expected: str = "400", price: str = "300") -> ThesisVersion:
    thesis = ThesisVersion(
        company_id=company.id, version=version, status="final",
        thesis_markdown="# Tesis", executive_summary="Resumen", rating="watch",
        current_price=Decimal(price), expected_value=Decimal(expected),
        invalidation_criteria=["texto libre"], invalidation_rules=rules,
    )
    db.add(thesis)
    db.commit()
    return thesis


# --- validacion -----------------------------------------------------------

def test_normalize_accepts_known_metrics_and_custom_metric():
    rules = normalize_rules([
        {"metric": "precio", "operator": "<", "threshold": "250", "description": "Rompe 250"},
        {"metric": "margen_seguridad_pct", "operator": "<=", "threshold": -10},
        {"metric": "metrica:roic", "operator": "<", "threshold": 0.08},
    ])
    assert rules[0] == {"metric": "precio", "operator": "<", "threshold": 250.0,
                        "description": "Rompe 250"}
    assert rules[1]["description"] is None
    assert rules[2]["metric"] == "metrica:roic"


@pytest.mark.parametrize("bad", [
    {"metric": "inventada", "operator": "<", "threshold": 1},
    {"metric": "precio", "operator": "=>", "threshold": 1},
    {"metric": "precio", "operator": "<", "threshold": "NaN"},
    {"metric": "precio", "operator": "<", "threshold": "abc"},
    {"metric": "precio", "operator": "<", "threshold": True},
    {"metric": "metrica:", "operator": "<", "threshold": 1},
    "precio < 3",
])
def test_normalize_rejects_unmeasurable_rules_in_spanish(bad):
    with pytest.raises(ValueError) as exc:
        normalize_rules([bad])
    assert "Criterio 1" in str(exc.value)


def test_normalize_drops_exact_duplicates():
    rule = {"metric": "precio", "operator": "<", "threshold": 250}
    assert len(normalize_rules([rule, dict(rule)])) == 1


# --- sincronizacion con AlertRule -----------------------------------------

def test_sync_creates_and_retires_rules_from_latest_thesis(db):
    company = _company(db)
    _thesis(db, company, version=1, rules=[
        {"metric": "precio", "operator": "<", "threshold": 250},
        {"metric": "margen_seguridad_pct", "operator": "<", "threshold": -10},
    ])
    rules = sync_thesis_rules(db, company)
    db.commit()
    assert len(rules) == 2
    assert all(r.rule_type == RULE_TYPE and r.active for r in rules)
    assert all(r.severity == "high" for r in rules)

    # Nueva version con un solo criterio: el otro deja de vigilarse.
    _thesis(db, company, version=2, rules=[
        {"metric": "precio", "operator": "<", "threshold": 250},
    ])
    sync_thesis_rules(db, company)
    db.commit()
    stored = db.scalars(select(AlertRule).where(AlertRule.rule_type == RULE_TYPE)).all()
    assert len(stored) == 2
    assert sorted(r.active for r in stored) == [False, True]
    active = next(r for r in stored if r.active)
    assert active.target["thesis_version"] == 2


def test_user_price_rules_are_not_touched_by_sync(db):
    company = _company(db)
    user_rule = AlertRuleService().create(db, company, rule_type="price_below", operator="<", value=100)
    _thesis(db, company, rules=None)
    sync_thesis_rules(db, company)
    db.commit()
    db.refresh(user_rule)
    assert user_rule.active is True


# --- evaluacion en el evaluador existente -----------------------------------

def test_margin_of_safety_rule_triggers_one_alert(db):
    company = _company(db)
    # Esperado 400; precio 480 -> margen = 400/480 - 1 = -16,67 % < -10 %.
    _thesis(db, company, rules=[{"metric": "margen_seguridad_pct", "operator": "<",
                                 "threshold": -10, "description": "Sin margen de seguridad"}])
    _price(db, company, "480")
    results = AlertRuleService().evaluate_all(db)
    thesis_results = [r for r in results if r["observation"].get("kind") == "thesis_metric"]
    assert len(thesis_results) == 1
    assert thesis_results[0]["status"] == "triggered"
    assert Decimal(thesis_results[0]["observed"]).quantize(Decimal("0.01")) == Decimal("-16.67")
    alerts = db.scalars(select(ResearchAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == RULE_TYPE
    assert "invalidación" in alerts[0].message
    assert "Sin margen de seguridad" in alerts[0].message
    assert "−16,67 %" in alerts[0].message or "-16,67 %" in alerts[0].message

    # Segunda pasada dentro del cooldown: no duplica el aviso.
    AlertRuleService().evaluate_all(db)
    assert db.query(ResearchAlert).count() == 1


def test_rule_not_met_does_not_alert(db):
    company = _company(db)
    _thesis(db, company, rules=[{"metric": "precio", "operator": "<", "threshold": 250}])
    _price(db, company, "300")
    AlertRuleService().evaluate_all(db)
    assert db.query(ResearchAlert).count() == 0


def test_stale_price_never_triggers(db):
    company = _company(db)
    _thesis(db, company, rules=[{"metric": "precio", "operator": "<", "threshold": 250}])
    _price(db, company, "100", day=date.today() - timedelta(days=60))
    results = AlertRuleService().evaluate_all(db)
    assert results[0]["status"] == "skipped_stale_observation"
    assert db.query(ResearchAlert).count() == 0


def test_change_since_thesis_rule(db):
    company = _company(db)
    # Precio en la tesis 300; ahora 210 -> -30 %.
    _thesis(db, company, price="300",
            rules=[{"metric": "variacion_desde_tesis_pct", "operator": "<=", "threshold": -25}])
    _price(db, company, "210")
    results = AlertRuleService().evaluate_all(db)
    assert results[0]["status"] == "triggered"
    assert Decimal(results[0]["observed"]) == Decimal("-30")


def test_custom_metric_reads_latest_calculated_metric(db):
    company = _company(db)
    for year, value in ((2024, "0.12"), (2025, "0.06")):
        db.add(CalculatedMetric(company_id=company.id, metric="roic", value=Decimal(value),
                                unit="decimal", period=f"FY{year}", fiscal_year=year,
                                formula="nopat / capital_invertido"))
    db.commit()
    _thesis(db, company, rules=[{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    results = AlertRuleService().evaluate_all(db)
    assert results[0]["status"] == "triggered"
    assert results[0]["observation"]["period"] == "FY2025"


def test_missing_data_evaluates_honestly_without_alert(db):
    company = _company(db)
    _thesis(db, company, rules=[{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    results = AlertRuleService().evaluate_all(db)
    assert results[0]["matched"] is False
    assert results[0]["observation"]["status"] == "missing"
    assert db.query(ResearchAlert).count() == 0


def test_corrupt_stored_rules_do_not_break_the_pass(db):
    company = _company(db)
    _thesis(db, company, rules=[{"metric": "precio", "operator": "<", "threshold": 250},
                                {"metric": "???", "operator": "<", "threshold": 1}])
    _price(db, company, "200")
    results = AlertRuleService().evaluate_all(db)
    assert [r["status"] for r in results] == ["triggered"]


# --- ruta PUT /thesis/{ticker}/invalidation-rules ---------------------------

def test_route_saves_rules_and_creates_alert_rules(db):
    from fastapi import HTTPException

    from app.api.routes.thesis import InvalidationRulesRequest, set_invalidation_rules

    company = _company(db)
    thesis = _thesis(db, company, rules=None)
    payload = InvalidationRulesRequest.model_validate({"rules": [
        {"metric": "margen_seguridad_pct", "operator": "<", "threshold": "-10",
         "description": "Pierde el margen"},
    ]})
    body = set_invalidation_rules("POOL", payload, db)
    db.refresh(thesis)
    assert thesis.invalidation_rules is not None
    assert thesis.invalidation_rules[0]["metric"] == "margen_seguridad_pct"
    assert body["invalidation_rules"][0]["label"] == "margen de seguridad < -10,00 %"
    assert len(body["alert_rule_ids"]) == 1

    bad = InvalidationRulesRequest.model_validate({"rules": [
        {"metric": "inventada", "operator": "<", "threshold": 1},
    ]})
    with pytest.raises(HTTPException) as exc:
        set_invalidation_rules("POOL", bad, db)
    assert exc.value.status_code == 422

    # Lista vacia: se borran y las reglas derivadas se desactivan.
    set_invalidation_rules("POOL", InvalidationRulesRequest(rules=[]), db)
    db.refresh(thesis)
    assert thesis.invalidation_rules is None
    assert db.query(AlertRule).filter(AlertRule.active.is_(True)).count() == 0



def test_legacy_three_day_setting_cannot_mark_yesterday_thesis_price_fresh(db, monkeypatch):
    from types import SimpleNamespace

    from app.services import thesis_invalidation_rules as module

    company = _company(db)
    # Más de 24 h desde el cierre de su sesión a cualquier hora de hoy (A8: el techo
    # #2884 se cuenta desde el cierre de la bolsa).
    _price(db, company, "210", day=date.today() - timedelta(days=2))
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(market_price_max_age_days=3))
    _, observation = module._latest_price(db, company.id)
    assert observation["status"] == "stale"


def test_max_age_zero_keeps_today_thesis_price_fresh(db, monkeypatch):
    """MARKET_PRICE_MAX_AGE_DAYS=0 significa «solo hoy», no «nunca actual»."""
    from types import SimpleNamespace

    from app.services import thesis_invalidation_rules as module

    company = _company(db)
    _price(db, company, "210", day=date.today())
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(market_price_max_age_days=0))
    _, observation = module._latest_price(db, company.id)
    assert observation["status"] == "fresh"



# --- unidades: peniques y ADR (cálculo independiente) ------------------------

def _observe(db, company, thesis, metric):
    from app.models import AlertRule
    from app.services.thesis_invalidation_rules import observe

    rule = AlertRule(company_id=company.id, name="criterio", rule_type=RULE_TYPE,
                     target={"metric": metric, "thesis_version_id": thesis.id})
    return observe(db, rule)


def _london(db: Session) -> Company:
    company = Company(
        ticker="PENX.L", name="Pence", exchange="LSE", currency="GBP",
        sector="x", industry="x", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(MarketPrice(
        company_id=company.id, date=date.today(), open=Decimal("1500"), high=Decimal("1500"),
        low=Decimal("1500"), close=Decimal("1500"), adj_close=Decimal("1500"),
        source="yfinance", quote_currency="GBp",
    ))
    db.commit()
    return company


def test_london_pence_close_is_compared_in_pounds(db):
    company = _london(db)
    # Tesis: precio 15 £, esperado 18 £. Hoy 1.500 GBp = 15 £.
    # Variación = 15/15 - 1 = 0 %; margen = 18/15 - 1 = 20 %.
    thesis = _thesis(db, company, price="15", expected="18")
    change, info = _observe(db, company, thesis, "variacion_desde_tesis_pct")
    assert change == Decimal("0")
    assert info["currency"] == "GBP"
    margin, _ = _observe(db, company, thesis, "margen_seguridad_pct")
    assert margin.quantize(Decimal("0.01")) == Decimal("20.00")


def test_adr_margin_uses_value_per_adr(db):
    company = _company(db, "ADRX")
    # Esperado 10 por ordinaria, ADR = 8 ordinarias -> 80 por ADR; ADR a 64.
    # Margen = 80/64 - 1 = 25 % (no 10/64 - 1 = -84,375 %).
    thesis = _thesis(db, company, expected="10", price="64")
    thesis.valuation_basis = {"adr_ratio": 8.0, "listed_share_values": {"expected": 80.0}}
    db.commit()
    _price(db, company, "64")
    margin, _ = _observe(db, company, thesis, "margen_seguridad_pct")
    assert margin == Decimal("25")


def test_adr_without_listed_values_has_no_margin(db):
    company = _company(db, "ADRY")
    thesis = _thesis(db, company, expected="10", price="64")
    thesis.valuation_basis = {"adr_ratio": 8.0}
    db.commit()
    _price(db, company, "64")
    margin, info = _observe(db, company, thesis, "margen_seguridad_pct")
    assert margin is None
    assert info["status"] == "missing"


def test_minor_unit_listing_without_declared_unit_does_not_compare(db):
    company = _london(db)
    db.query(MarketPrice).update({MarketPrice.quote_currency: None})
    db.commit()
    thesis = _thesis(db, company, price="15", expected="18")
    change, info = _observe(db, company, thesis, "variacion_desde_tesis_pct")
    assert change is None
    assert info["missing"] == "unidad_precio"
