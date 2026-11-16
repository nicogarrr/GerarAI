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
    # Esperado 400; precio 480 -> margen = (400 - 480) / 400 = -20 % < -10 %.
    _thesis(db, company, rules=[{"metric": "margen_seguridad_pct", "operator": "<",
                                 "threshold": -10, "description": "Sin margen de seguridad"}])
    _price(db, company, "480")
    results = AlertRuleService().evaluate_all(db)
    thesis_results = [r for r in results if r["observation"].get("kind") == "thesis_metric"]
    assert len(thesis_results) == 1
    assert thesis_results[0]["status"] == "triggered"
    assert Decimal(thesis_results[0]["observed"]).quantize(Decimal("0.01")) == Decimal("-20.00")
    alerts = db.scalars(select(ResearchAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == RULE_TYPE
    assert "invalidación" in alerts[0].message
    assert "Sin margen de seguridad" in alerts[0].message
    assert "−20,00 %" in alerts[0].message or "-20,00 %" in alerts[0].message

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
    # Variación = 15/15 - 1 = 0 %; margen = (18 - 15) / 18 = 16,67 %.
    thesis = _thesis(db, company, price="15", expected="18")
    change, info = _observe(db, company, thesis, "variacion_desde_tesis_pct")
    assert change == Decimal("0")
    assert info["currency"] == "GBP"
    margin, _ = _observe(db, company, thesis, "margen_seguridad_pct")
    assert margin.quantize(Decimal("0.01")) == Decimal("16.67")


def test_adr_margin_uses_value_per_adr(db):
    company = _company(db, "ADRX")
    # Esperado 10 por ordinaria, ADR = 8 ordinarias -> 80 por ADR; ADR a 64.
    # Margen = (80 - 64) / 80 = 20 % (no (10 - 64) / 10 = -540 %).
    thesis = _thesis(db, company, expected="10", price="64")
    thesis.valuation_basis = {"adr_ratio": 8.0, "listed_share_values": {"expected": 80.0}}
    db.commit()
    _price(db, company, "64")
    margin, _ = _observe(db, company, thesis, "margen_seguridad_pct")
    assert margin == Decimal("20")


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


@pytest.mark.parametrize('ticker', ['ASTS', 'AAPL'])
def test_derivation_uses_the_same_base_as_text_and_syncs_alert(db, ticker):
    from app.services.thesis_invalidation_rules import derive_rules_from_valuation
    from app.services.thesis_service import ThesisService

    company = _company(db, ticker)
    valuation = {'base_value': 123.45, 'current_price': 90,
                 'reverse_dcf': {'required_revenue_growth': .12}}
    rules = derive_rules_from_valuation(valuation)
    assert len(rules) == 1  # no invented growth metric or threshold
    assert rules[0]['threshold'] == 123.45
    assert rules[0]['metric'] == 'precio'
    assert rules[0]['operator'] == '>'
    assert 'Derivada del criterio en texto' in rules[0]['description']
    assert 'No comprueba persistencia' in rules[0]['description']
    assert any('123.45' in line for line in ThesisService()._invalidation_criteria(company, valuation))
    _thesis(db, company, rules=rules)
    alerts = sync_thesis_rules(db, company)
    assert len(alerts) == 1
    _price(db, company, '124')
    assert AlertRuleService().evaluate_all(db)[0]['status'] == 'triggered'


@pytest.mark.parametrize('valuation', [
    {}, {'base_value': 100}, {'current_price': 90},
    {'base_value': 100, 'current_price': 100},
    {'base_value': 100, 'current_price': 120},
    {'base_value': 0, 'current_price': 1},
    {'base_value': -10, 'current_price': -20},
    {'base_value': 100, 'current_price': 0},
    {'base_value': 'NaN', 'current_price': 90},
    {'base_value': 100, 'current_price': 'Infinity'},
    {'base_value': 'bad', 'current_price': 90},
    {'base_value': True, 'current_price': 0.5},
    {'base_value': '1e400', 'current_price': 90},
    {'base_value': 100, 'current_price': '1e-400'},
])
def test_no_derived_rule_without_valid_observable_price_and_base(valuation):
    from app.services.thesis_invalidation_rules import derive_rules_from_valuation
    assert derive_rules_from_valuation(valuation) == []


def test_rules_recalculated_but_user_override_always_wins(db):
    from app.api.routes.thesis import InvalidationRulesRequest, set_invalidation_rules
    from app.services.thesis_invalidation_rules import RULES_ORIGIN_KEY, rules_for_valuation

    company = _company(db)
    valuation = {'base_value': 100, 'current_price': 80}
    rules, origin = rules_for_valuation(valuation, None)
    assert origin == 'derived' and rules[0]['threshold'] == 100
    thesis = _thesis(db, company, rules=rules)
    thesis.valuation_basis = {RULES_ORIGIN_KEY: origin, 'other': 'preserved'}
    db.commit()
    rules, origin = rules_for_valuation({'base_value': 200, 'current_price': 80}, thesis)
    assert origin == 'derived' and rules[0]['threshold'] == 200
    assert rules_for_valuation({}, thesis) == ([], 'derived')
    # Editing even a derived-looking description makes it user-owned.
    set_invalidation_rules('POOL', InvalidationRulesRequest.model_validate({'rules': [
        {**rules[0], 'threshold': 150},
    ]}), db)
    db.refresh(thesis)
    assert thesis.valuation_basis == {RULES_ORIGIN_KEY: 'user', 'other': 'preserved'}
    kept, origin = rules_for_valuation(valuation, thesis)
    assert origin == 'user' and kept[0]['threshold'] == 150
    # Clearing is an explicit opt-out, not permission to re-add derived rules.
    set_invalidation_rules('POOL', InvalidationRulesRequest(rules=[]), db)
    db.refresh(thesis)
    assert rules_for_valuation(valuation, thesis) == ([], 'user')
    # Legacy rules without provenance are treated as user-owned too.
    thesis.valuation_basis = None
    thesis.invalidation_rules = kept
    assert rules_for_valuation(valuation, thesis) == (kept, 'user')
    thesis.invalidation_rules = None
    assert rules_for_valuation(valuation, thesis)[1] == 'derived'


def test_generation_persists_derivation_and_manual_empty_override(db, monkeypatch):
    from types import SimpleNamespace

    from app.api.routes.thesis import InvalidationRulesRequest, set_invalidation_rules
    from app.services import thesis_service as module
    from app.services.red_team_service import RedTeamService
    from app.services.thesis_evidence_service import ThesisEvidenceService
    from app.services.thesis_graph_service import ThesisGraphService
    from app.services.thesis_invalidation_rules import RULES_ORIGIN_KEY

    _company(db)
    service = module.ThesisService()
    valuation = {'status': 'ok', 'publishable': True, 'current_price': 80,
                 'base_value': 100, 'expected_value': 110, 'margin_of_safety': .2,
                 'trace': {}}
    monkeypatch.setattr(ThesisEvidenceService, 'collect_stored', lambda *a: {})
    monkeypatch.setattr(module, '_prepare_thesis_experts', lambda *a, **k: None)
    monkeypatch.setattr(module.LongTermModelService, 'build', lambda *a, **k: {})
    monkeypatch.setattr(service.valuation_service, 'value_company', lambda *a: dict(valuation))
    monkeypatch.setattr(service.valuation_service, 'persist_output', lambda *a, **k: None)
    monkeypatch.setattr(module.FinancialSnapshotBuilder, 'build', lambda *a: SimpleNamespace(
        facts={}, excluded_present=[]))
    audit = SimpleNamespace(passed=True, source_coverage_score=100, unsupported_claims=[],
                            weak_claims=[], data_conflicts=[], required_fixes=[], as_dict=lambda: {})
    monkeypatch.setattr(service.auditor, 'audit', lambda **k: audit)
    monkeypatch.setattr(service, '_build_claims', lambda *a: [])
    monkeypatch.setattr(service, '_render_markdown', lambda *a, **k: '# Fixture')
    monkeypatch.setattr(service, '_valuation_basis', lambda *a: {'existing': 'retained'})
    monkeypatch.setattr(module, 'retrieve_thesis_context', lambda *a: [])
    monkeypatch.setattr(module, 'maybe_deep_narrative', lambda *a, **k: None)
    monkeypatch.setattr(ThesisGraphService, 'build', lambda *a, **k: None)
    monkeypatch.setattr(RedTeamService, 'run', lambda *a, **k: None)
    first = service._generate_atomic(db, 'POOL', force_new_version=True, stored_evidence_only=True)
    assert first.invalidation_rules[0]['threshold'] == 100
    assert first.valuation_basis[RULES_ORIGIN_KEY] == 'derived'
    assert first.valuation_basis['existing'] == 'retained'
    valuation['base_value'] = 120
    second = service._generate_atomic(db, 'POOL', force_new_version=True, stored_evidence_only=True)
    assert second.invalidation_rules[0]['threshold'] == 120
    set_invalidation_rules('POOL', InvalidationRulesRequest(rules=[]), db)
    third = service._generate_atomic(db, 'POOL', force_new_version=True, stored_evidence_only=True)
    assert third.invalidation_rules is None
    assert third.valuation_basis[RULES_ORIGIN_KEY] == 'user'


def test_thesis_render_diagnostics_with_and_without_optional_sources():
    from app.services.thesis_service import ThesisService

    service = ThesisService()
    assert service._md_cell(None) == ''
    assert service._md_cell('a|b\nc') == 'a\\|b c'
    for data in (None, {}, {'status': 'disabled'}):
        assert service._consensus_markdown(data) == ''
    for status in ('sin_consenso', 'no_comparable', 'error:fixture'):
        assert status in service._consensus_markdown({'status': status})
    for source in ('', 'https://example.com/fixture'):
        out = service._consensus_markdown({'status': 'revisar', 'reason': 'fixture',
            'consensus': {'mean': 10, 'high': 12, 'source_url': source},
            'steps': [{'name': 'a|b', 'ours': 1, 'theirs': 2, 'effect_per_share': 3}, {}],
            'data_rows': [None, {}, {'method': 'analyst', 'name': 'x', 'value': 1,
                                   'source_quote': 'q|q'},
                          {'method': 'analyst', 'input': 'y', 'value': 2}]})
        assert 'a\\|b' in out and 'Supuestos de analista' in out
        assert 'no bloquea' in out
    assert service._value_drivers_markdown({'status': 'no_tenant'}) == ''
    full = {'name': 'impulsor', 'source_url': 'https://example.com/fixture',
            'source_quote': 'cita|cita', 'as_of': '2026-11-16',
            'value_per_share_marginal': 0, 'model_link': 'fixture',
            'reason_if_not_valued': 'sin tratamiento'}
    out = service._value_drivers_markdown({'publishable': False,
        'blocking': [{'driver_key': 'x', 'why': 'pendiente'}], 'drivers': [full, {}]})
    assert 'Valor marginal' in out and 'cita\\|cita' in out
    assert 'No valorado' in out and 'Recogido en el modelo' in out
    for data in (None, {}, {'status': ''}, {'status': 'disabled'}):
        assert service._expert_inputs_markdown(data) == ''
    for data in ({'status': 'ok'}, {'status': 'error',
         'recopilador': {'status': 'stored', 'stored': 2, 'firms': ['fixture']},
         'analista': {'stored': 1}, 'errors': ['fixture']}):
        assert 'Pipeline de expertos' in service._expert_inputs_markdown(data)


def test_thesis_route_history_and_memo_variants(db, monkeypatch):
    from fastapi import HTTPException

    from app.api.routes import thesis as route
    from app.models import ThesisDiff

    company = _company(db)
    first = _thesis(db, company)
    second = _thesis(db, company, version=2)
    assert route.thesis_history('POOL', db)['count'] == 2
    db.add(ThesisDiff(company_id=company.id, from_version_id=first.id,
                     to_version_id=second.id, change_summary='fixture',
                     affected_assumptions=[], rating_changed=False))
    db.commit()
    assert route.thesis_history('POOL', db)['history'][0]['diff']['change_summary'] == 'fixture'
    monkeypatch.setattr(route, 'build_memo_markdown', lambda *a, **k: '# Fixture')
    assert route.thesis_memo('POOL', published=False, draft=True, db=db).body == b'# Fixture'
    with pytest.raises(HTTPException) as exc:
        route.thesis_memo('POOL', published=True, draft=False, db=db)
    assert exc.value.status_code == 404
    first.status = 'published'
    db.commit()
    assert route.thesis_memo('POOL', published=True, draft=False, db=db).body == b'# Fixture'
    for call in (lambda: route.thesis_history('UNKNOWN', db),
                 lambda: route.thesis_memo('UNKNOWN', published=False, draft=False, db=db),
                 lambda: route.latest_thesis('UNKNOWN', db),
                 lambda: route.thesis_versions('UNKNOWN', db=db)):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404


@pytest.mark.parametrize('endpoint,method', [('thesis_graph', 'read'), ('refresh_thesis_graph', 'build')])
def test_graph_route_success_unknown_and_safe_errors(db, monkeypatch, endpoint, method):
    from fastapi import HTTPException

    from app.api.routes import thesis as route

    company = _company(db)
    thesis = _thesis(db, company)
    call = getattr(route, endpoint)
    with pytest.raises(HTTPException) as exc:
        call('UNKNOWN', db)
    assert exc.value.status_code == 404
    monkeypatch.setattr(route.ThesisGraphService, method, lambda *a: (thesis, [], []))
    assert call('POOL', db)['thesis_version_id'] == thesis.id
    for message, status in [('unknown ticker fixture', 404), ('fixture error', 400)]:
        def fail(*a):
            raise ValueError(message)
        monkeypatch.setattr(route.ThesisGraphService, method, fail)
        with pytest.raises(HTTPException) as exc:
            call('POOL', db)
        assert exc.value.status_code == status


@pytest.mark.parametrize('state,expected', [('ready', 'ready'), ('unavailable', 503)])
def test_audio_generation_started_or_unavailable(db, monkeypatch, state, expected):
    from fastapi import HTTPException

    from app.api.routes import thesis as route

    monkeypatch.setattr(route, '_audio_context', lambda *a: ('fixture', 'text'))
    monkeypatch.setattr(route.thesis_audio_service, 'status', lambda *a: 'missing')
    monkeypatch.setattr(route.thesis_audio_service, 'start', lambda *a: state)
    if isinstance(expected, int):
        with pytest.raises(HTTPException) as exc:
            route.thesis_audio_generate('POOL', version=None, db=db)
        assert exc.value.status_code == expected
    else:
        assert route.thesis_audio_generate('POOL', version=None, db=db)['state'] == expected


def test_rule_route_unknown_company_and_missing_thesis(db):
    from fastapi import HTTPException

    from app.api.routes.thesis import InvalidationRulesRequest, set_invalidation_rules

    for ticker in ('UNKNOWN', 'POOL'):
        if ticker == 'POOL':
            _company(db)
        with pytest.raises(HTTPException) as exc:
            set_invalidation_rules(ticker, InvalidationRulesRequest(rules=[]), db)
        assert exc.value.status_code == 404
