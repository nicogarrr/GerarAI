"""evaluate_all retiene lo cargado durante la pasada: misma salida, menos SELECT.

El mapa de identidad de la sesion es debil; sin retener, cada ``db.get`` de
Company/ThesisVersion por regla volvia a la base. Se comparan dos bases
identicas: la pasada nueva frente a la de antes (``_evaluate_all`` sin
retener), con el mismo resultado por regla, las mismas reglas y los mismos
avisos, y menos lecturas de companies y thesis_versions.
"""

import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.models.entities import AlertRule, Base, Company, MarketPrice, ResearchAlert, ThesisVersion
from app.services.alert_rule_service import AlertRuleService

DAY = date(2026, 11, 3)


def _seed(db: Session) -> None:
    for index, ticker in enumerate(["POOL", "ASML", "SAN", "TSCO", "NVDA"]):
        company = Company(
            ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
            sector="Industrials", industry="Distribution", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(company)
        db.flush()
        for offset, close in ((1, "300"), (0, str(280 + 10 * index))):
            value = Decimal(close)
            db.add(MarketPrice(
                company_id=company.id, date=date.today() - timedelta(days=offset), open=value,
                high=value, low=value, close=value, adj_close=value, source="test",
            ))
        for version in (1, 2):
            db.add(ThesisVersion(
                company_id=company.id, version=version, status="final",
                thesis_markdown="# Tesis " * 200, executive_summary="Resumen", rating="watch",
                current_price=Decimal("300"), expected_value=Decimal("400"),
                invalidation_criteria=["texto libre"],
                invalidation_rules=[
                    {"metric": "precio", "operator": "<", "threshold": 295 - version},
                    {"metric": "margen_seguridad_pct", "operator": ">", "threshold": 20},
                    {"metric": "variacion_desde_tesis_pct", "operator": "<", "threshold": -50},
                ],
            ))
        if index == 0:
            db.add(AlertRule(
                company_id=company.id, name="POOL bajo 290", rule_type="price_below",
                condition={"operator": "<", "value": 290}, target={"kind": "market_price"},
                channels=["in_app"], cooldown_seconds=3600, trigger_count=0, severity="medium",
            ))
    db.commit()


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    _seed(session)
    session.expunge_all()  # la pasada empieza sin nada cargado, como en el worker
    return session


def _selects(session: Session) -> Counter:
    counts: Counter = Counter()

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def _count(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            match = re.search(r"\bFROM\s+(\w+)", statement)
            counts[match.group(1) if match else "?"] += 1

    return counts


def _state(session: Session):
    rules = [
        (r.name, r.rule_type, r.active, r.trigger_count, r.last_value, r.last_result, r.target, r.condition)
        for r in session.scalars(select(AlertRule).order_by(AlertRule.name)).all()
    ]
    alerts = [
        (a.title, a.message, a.alert_type, a.severity, a.status)
        for a in session.scalars(select(ResearchAlert).order_by(ResearchAlert.title, ResearchAlert.message)).all()
    ]
    return rules, alerts


def test_evaluate_all_same_output_fewer_selects():
    new_db, old_db = _session(), _session()
    new_counts, old_counts = _selects(new_db), _selects(old_db)

    new = AlertRuleService().evaluate_all(new_db, market_day=DAY)
    old = AlertRuleService()._evaluate_all(old_db, skip_closed_markets=False, market_day=DAY)

    def _ids_out(results):
        return [{k: v for k, v in r.items() if k != "rule_id"} for r in results]

    assert len(new) == len(old) == 16
    assert _ids_out(new) == _ids_out(old)
    assert any(r["status"] == "triggered" for r in new)
    assert _state(new_db) == _state(old_db)
    assert new_counts["companies"] < old_counts["companies"]
    assert new_counts["thesis_versions"] < old_counts["thesis_versions"]
    # Una segunda pasada (reglas ya sincronizadas) tambien coincide.
    new_db.expunge_all()
    old_db.expunge_all()
    assert _ids_out(AlertRuleService().evaluate_all(new_db, market_day=DAY)) == _ids_out(
        AlertRuleService()._evaluate_all(old_db, skip_closed_markets=False, market_day=DAY)
    )
    assert _state(new_db) == _state(old_db)


def test_listener_removed_after_pass():
    db = _session()
    before = len(list(db.dispatch.loaded_as_persistent))
    AlertRuleService().evaluate_all(db, market_day=DAY)
    assert len(list(db.dispatch.loaded_as_persistent)) == before
