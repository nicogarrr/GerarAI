"""Bordes de ``app.services.alert_rule_service``: guardas puras y reglas de precio.

Lo que demuestra:
- ``_numeric_threshold``: booleanos y «Infinity» no son umbral (48, 54).
- ``create``: operador desconocido -> ValueError con el mensaje exacto
  (92); con Telegram configurado se añade el canal "telegram" (124).
- ``_price_in_threshold_unit`` con la empresa borrada devuelve el valor
  tal cual (634).
- ``evaluate`` en regla de precio con posición en otra divisa y sin tipo
  FX: observación ``mixed_units``, sin disparar y sin emitir alerta (439).
- ``_event_cursor``: fecha imposible -> None (689-690).
- ``_advance_event_cursor`` sin instantes conocidos no toca metadata (709).
- ``_json_value``: datetime/date -> isoformat exacto (723).

Fuera de alcance a propósito: el camino que emite vía
ReviewAlertService.emit_alert (279-280, 291->296, 308-310), las ramas de
reglas de noticias/earnings (565->571, 593->595) y la línea 528
(previous_value==0 tras conversión de unidades: solo alcanzable con un
cierre 0 que ya filtra 505).

SQLite real en memoria; sin red; nada del camino ResearchReview.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AlertRule, Position, ResearchAlert
from app.models.entities import Base, Company
from app.services import alert_rule_service as svc
from app.services.alert_rule_service import AlertRuleService


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


def _company(db, currency="USD"):
    company = Company(
        ticker="GUAR",
        name="Guard Co",
        exchange="NASDAQ",
        currency=currency,
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_numeric_threshold_rechaza_booleanos():
    assert svc._numeric_threshold(True) is None
    assert svc._numeric_threshold(False) is None


def test_numeric_threshold_rechaza_infinito():
    assert svc._numeric_threshold("Infinity") is None
    assert svc._numeric_threshold(float("inf")) is None


def test_create_rechaza_operador_desconocido(db):
    company = _company(db)
    with pytest.raises(ValueError) as excinfo:
        AlertRuleService().create(db, company, rule_type="price_below", operator="between", value=13)
    assert str(excinfo.value) == (
        f"Unsupported alert operator: 'between'. Expected one of {sorted(svc._OPERATORS)}."
    )


def test_create_con_telegram_configurado(db, monkeypatch):
    monkeypatch.setattr(
        svc,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_enabled=True,
            telegram_bot_token="token-falso",
            telegram_chat_id="chat-falso",
        ),
    )
    company = _company(db)
    rule = AlertRuleService().create(db, company, rule_type="price_below", operator="<", value=13)
    assert rule.channels == ["in_app", "telegram"]


def test_price_in_threshold_unit_sin_empresa_devuelve_valor(db):
    rule = SimpleNamespace(company_id=999999)
    result = AlertRuleService._price_in_threshold_unit(
        db, rule, Decimal("5"), unit="USD", on=date(2025, 6, 2)
    )
    assert result == Decimal("5")


def test_evaluate_posicion_en_otra_divisa_sin_fx(db):
    company = _company(db, currency="EUR")
    db.add(
        Position(
            company_id=company.id,
            quantity=Decimal("10"),
            average_cost=Decimal("150"),
            market_price=Decimal("180"),
            market_value=Decimal("1800"),
            currency="USD",
            base_currency="EUR",
            source="ibkr_flex",
        )
    )
    db.commit()
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_below", operator="<", value=3)
    result = service.evaluate(db, rule)
    assert result["status"] == "evaluated"
    assert result["matched"] is False
    assert result["observation"] == {
        "kind": "market_price",
        "status": "mixed_units",
        "position_id": db.query(Position).one().id,
    }
    assert db.query(ResearchAlert).count() == 0


def test_event_cursor_mal_formado_devuelve_none():
    rule = AlertRule(company_id=1, name="x")
    rule.metadata_ = {"event_cursor": "no-fecha"}
    assert AlertRuleService._event_cursor(rule) is None


def test_advance_event_cursor_sin_instantes_no_toca_metadata():
    rule = AlertRule(company_id=1, name="x")
    rule.last_evaluated_at = None
    rule.created_at = None
    rule.metadata_ = {}
    AlertRuleService()._advance_event_cursor(rule, datetime(2025, 6, 2, tzinfo=UTC), {}, pending=True)
    assert rule.metadata_ == {}


def test_json_value_serializa_fechas():
    assert AlertRuleService._json_value(datetime(2025, 1, 1, tzinfo=UTC)) == "2025-01-01T00:00:00+00:00"
    assert AlertRuleService._json_value(date(2025, 1, 2)) == "2025-01-02"
    assert AlertRuleService._json_value(Decimal("1.5")) == "1.5"
