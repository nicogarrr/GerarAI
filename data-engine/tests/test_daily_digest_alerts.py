
"""Daily-digest outbound alert: routing, idempotency and honest copy."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.alerts import (
    TelegramSubscriptionIn,
    list_telegram_subscriptions,
    set_telegram_subscription,
)
from app.models import PortfolioMoveDigest, ResearchAlert, Tenant
from app.models.entities import Base
from app.services.daily_digest_alerts import VERSION, emit_digest_alert, last_session_date
from app.services.outbound_alerts import EVENT_TYPES, dispatch_pending, event_type, subscription_for

AS_OF = date(2026, 10, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="owner"))
        db.commit()
        db.info.update(tenant_id=1, user_id="owner")
        yield db
    engine.dispose()


def make_digest(db, items=None, coverage="complete"):
    row = PortfolioMoveDigest(
        tenant_id=1, digest_date=AS_OF, version="test-v1", input_hash="abc123",
        items=items if items is not None else [
            {"ticker": "ASTS", "status": "disponible", "price_change_pct": 2.5},
            {"ticker": "NBIS", "status": "sin datos"},
        ],
        coverage=coverage, generated_at=datetime(2026, 10, 10, 5, 15, tzinfo=UTC),
    )
    db.add(row)
    db.commit()
    return row


def opt_in(db):
    from app.models.entities import TelegramChatBinding
    if db.scalar(select(TelegramChatBinding)) is None:
        db.add(TelegramChatBinding(user_id="owner", chat_id="12345"))
        db.commit()
    return set_telegram_subscription("daily_digest", TelegramSubscriptionIn(enabled=True, chat_id="12345"), db)


def test_event_type_routes_daily_digest(db):
    digest = make_digest(db)
    alert = emit_digest_alert(db, digest, AS_OF)
    assert alert is not None
    assert event_type(db, alert) == "daily_digest"
    assert "daily_digest" in EVENT_TYPES


def test_subscription_api_accepts_daily_digest(db):
    kinds = [r["event_type"] for r in list_telegram_subscriptions(db)]
    assert "daily_digest" in kinds
    out = opt_in(db)
    assert out["enabled"] is True
    assert out["event_type"] == "daily_digest"


def test_emit_is_idempotent_per_tenant_day(db):
    digest = make_digest(db)
    first = emit_digest_alert(db, digest, AS_OF)
    second = emit_digest_alert(db, digest, AS_OF)
    assert first is not None and second is None
    rows = db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == "daily_digest")).all()
    assert len(rows) == 1


def test_emit_requires_tenant(db):
    digest = make_digest(db)
    db.info.pop("tenant_id")
    with pytest.raises(ValueError):
        emit_digest_alert(db, digest, AS_OF)


def test_copy_carries_source_date_basis_and_variations(db):
    digest = make_digest(db)
    alert = emit_digest_alert(db, digest, AS_OF)
    assert AS_OF.isoformat() in alert.message
    assert "yfinance" in alert.message
    assert "ASTS +2.50%" in alert.message  # la variacion viaja en el resumen
    assert "Sin datos: NBIS" in alert.message  # lo no cubierto se nombra, nunca 0
    assert "no el P&L" in alert.message
    assert alert.metadata_["price_source"] == "yfinance"
    assert alert.metadata_["rule_version"] == VERSION


def test_copy_seals_universe_sampling_time(db):
    digest = make_digest(db)
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "2026-10-10 07:15 (hora de Madrid)" in alert.message  # cartera medida al generar
    assert alert.metadata_["positions_sampled_at"] == "2026-10-10T05:15:00+00:00"


def test_foreign_tenant_digest_is_rejected(db):
    from types import SimpleNamespace
    digest = make_digest(db)
    # nosemgrep: gerarai-orm-fake-simplenamespace -- falso digest a proposito: prueba el rechazo de un objeto de otro tenant / un build_digest parcheado
    foreign = SimpleNamespace(tenant_id=2, digest_date=AS_OF, items=[], coverage="complete",
                              generated_at=digest.generated_at, id=digest.id)
    with pytest.raises(ValueError):
        emit_digest_alert(db, foreign, AS_OF)
    assert db.scalars(select(ResearchAlert)).all() == []


def test_stale_date_digest_is_rejected(db):
    from datetime import timedelta
    digest = make_digest(db)
    with pytest.raises(ValueError):
        emit_digest_alert(db, digest, AS_OF - timedelta(days=1))
    assert db.scalars(select(ResearchAlert)).all() == []


def test_zero_positions_still_emits_honest_copy(db):
    digest = make_digest(db, items=[], coverage="sin_posiciones")
    alert = emit_digest_alert(db, digest, AS_OF)
    assert alert is not None
    assert "No habia posiciones" in alert.message


def test_all_missing_data_is_not_zero(db):
    digest = make_digest(db, items=[{"ticker": "X", "status": "sin datos"}], coverage="partial")
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "sin datos" in alert.message
    assert "0 posiciones con cierre" not in alert.message


def test_all_invalid_pct_names_every_ticker_and_marks_partial(db):
    digest = make_digest(db, items=[
        {"ticker": "NAN1", "status": "disponible", "price_change_pct": float("nan")},
        {"ticker": "NOPCT", "status": "disponible", "price_change_pct": None},
    ], coverage="complete")
    alert = emit_digest_alert(db, digest, AS_OF)
    # Sin variaciones finitas: se nombran los tickers igualmente y no se repite "complete"
    assert "Sin datos: NAN1, NOPCT" in alert.message
    assert "complete" not in alert.message
    assert "Cobertura del resumen: parcial" in alert.message
    assert alert.metadata_["coverage"] == "parcial"
    assert alert.metadata_["digest_coverage"] == "complete"


def test_coverage_stays_complete_when_nothing_filtered(db):
    digest = make_digest(db, items=[
        {"ticker": "A", "status": "disponible", "price_change_pct": 1.0},
        {"ticker": "B", "status": "disponible", "price_change_pct": -2.0},
    ], coverage="complete")
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "Cobertura del resumen: complete" in alert.message


def test_subscription_matches_alert_emitted_after_opt_in(db):
    opt_in(db)
    digest = make_digest(db)
    alert = emit_digest_alert(db, digest, AS_OF)
    sub = subscription_for(db, alert)
    assert sub is not None and sub.event_type == "daily_digest"


def test_opt_in_is_not_retroactive(db):
    digest = make_digest(db)
    alert = emit_digest_alert(db, digest, AS_OF)
    opt_in(db)
    assert subscription_for(db, alert) is None


def test_dispatch_skips_when_subscribed_to_other_type(db):
    from app.models.entities import TelegramChatBinding
    db.add(TelegramChatBinding(user_id="owner", chat_id="12345"))
    db.commit()
    set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id="12345"), db)
    digest = make_digest(db)
    emit_digest_alert(db, digest, AS_OF)
    stats = dispatch_pending(db)
    assert stats["redispatched"] == 0
    assert stats["candidates"] == 0  # no cuela por la suscripcion a insiders


def test_dispatch_no_subscriptions_is_early_return(db):
    digest = make_digest(db)
    emit_digest_alert(db, digest, AS_OF)
    stats = dispatch_pending(db)
    assert stats == {"candidates": 0, "redispatched": 0, "errors": []}


def _patch_actor(monkeypatch, db, emit):
    from types import SimpleNamespace

    import app.services.daily_digest_alerts as dda
    import app.services.portfolio_moves_service as pms
    from app.workers import dramatiq_app
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a, **kw: db)
    # nosemgrep: gerarai-orm-fake-simplenamespace -- falso digest a proposito: prueba el rechazo de un objeto de otro tenant / un build_digest parcheado
    digest = SimpleNamespace(id=1, coverage="complete", tenant_id=1, digest_date=AS_OF)
    monkeypatch.setattr(pms, "build_digest", lambda _db, _as_of: digest)
    monkeypatch.setattr(dda, "emit_digest_alert", emit)
    return dramatiq_app


def test_actor_emit_failure_is_partial_never_false_green(db, monkeypatch):
    def boom(_db, _digest, _as_of):
        raise RuntimeError("fallo de emision simulado")
    app = _patch_actor(monkeypatch, db, boom)
    out = app.refresh_portfolio_moves.fn(tenant_id=1, user_id="owner")
    assert out["status"] == "partial"
    assert out["digest_alert"] == "error"
    assert "fallo de emision" in out["alert_error"]


def test_actor_reports_emitted_and_already_emitted(db, monkeypatch):
    from types import SimpleNamespace
    app = _patch_actor(monkeypatch, db, lambda *_a: SimpleNamespace(id=42))
    out = app.refresh_portfolio_moves.fn(tenant_id=1, user_id="owner")
    assert out["status"] == "ok" and out["digest_alert"] == "emitted" and out["digest_alert_id"] == 42
    # El decorador de coalescencia retiene el claim ~20 h a proposito (drenado
    # del backlog): la segunda llamada del test necesita claim fresco, lo mismo
    # que el fixture autouse hace entre tests. Sin Redis es no-op.
    from tests.conftest import reset_shared_redis_dedup_state

    reset_shared_redis_dedup_state()

    app2 = _patch_actor(monkeypatch, db, lambda *_a: None)
    out2 = app2.refresh_portfolio_moves.fn(tenant_id=1, user_id="owner")
    assert out2["status"] == "ok" and out2["digest_alert"] == "already_emitted"


def test_nan_and_missing_pct_go_to_sin_datos(db):
    digest = make_digest(db, items=[
        {"ticker": "NAN1", "status": "disponible", "price_change_pct": float("nan")},
        {"ticker": "INF1", "status": "disponible", "price_change_pct": float("inf")},
        {"ticker": "NOPCT", "status": "disponible", "price_change_pct": None},
        {"ticker": "OK1", "status": "disponible", "price_change_pct": 1.5},
    ])
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "+nan" not in alert.message and "+inf" not in alert.message
    assert "OK1 +1.50%" in alert.message
    assert "1 de 4 posiciones con variacion" in alert.message
    for bad in ("NAN1", "INF1", "NOPCT"):
        assert bad in alert.message.split("Sin datos:")[1]


def test_aware_non_utc_generated_at_is_converted(db):
    from datetime import timedelta, timezone
    digest = make_digest(db)
    digest.generated_at = datetime(2026, 10, 10, 7, 15, tzinfo=timezone(timedelta(hours=2)))
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "2026-10-10 07:15 (hora de Madrid)" in alert.message
    assert alert.metadata_["positions_sampled_at"] == "2026-10-10T05:15:00+00:00"


def test_truncation_is_explicit(db):
    items = [{"ticker": f"T{i:02d}", "status": "disponible", "price_change_pct": float(i)}
             for i in range(20)]
    items += [{"ticker": f"S{i:02d}", "status": "sin datos"} for i in range(20)]
    digest = make_digest(db, items=items)
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "Mostradas 16 de 20 posiciones con variacion; 4 omitidas." in alert.message
    assert "20 de 40 posiciones con variacion" in alert.message
    assert "y 4 mas." in alert.message  # sin_datos tambien acotado


def test_last_session_date_skips_weekends():
    # 2026-10-19 es lunes: el ultimo cierre es el viernes 16, no el domingo 18.
    assert last_session_date(date(2026, 10, 19)) == date(2026, 10, 16)
    assert last_session_date(date(2026, 10, 18)) == date(2026, 10, 16)  # domingo
    assert last_session_date(date(2026, 10, 17)) == date(2026, 10, 16)  # sabado
    assert last_session_date(date(2026, 10, 20)) == date(2026, 10, 19)  # martes


def test_sampling_time_uses_madrid_winter_offset(db):
    digest = make_digest(db)
    digest.generated_at = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)  # CET: 3-nov 00:30
    db.commit()
    alert = emit_digest_alert(db, digest, AS_OF)
    assert "2026-11-03 00:30 (hora de Madrid)" in alert.message
    assert " UTC)" not in alert.message


def test_session_gap_is_named_with_missing_day_not_as_plain_missing_data(db):
    # Un hueco de sesion (portfolio_moves #3277) no es "sin datos" ni 0: se
    # nombra con la sesion que falta.
    items = [
        {"ticker": "ASTS", "status": "disponible", "price_change_pct": 1.0},
        {"ticker": "SAN.MC", "status": "hueco de sesión", "previous_date": "2026-10-26",
         "missing_sessions": ["2026-10-27"]},
    ]
    alert = emit_digest_alert(db, make_digest(db, items=items), AS_OF)
    assert "Sin datos" not in alert.message
    assert "SAN.MC (falta el cierre del 2026-10-27)" in alert.message
    assert "hueco de sesión, no 0" in alert.message
    assert alert.metadata_["coverage"] == "parcial"


@pytest.fixture
def english(db, monkeypatch):
    """Usuario con inglés guardado en Ajustes y generación multidioma encendida."""
    from app.core.config import get_settings

    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db.get(Tenant, 1).metadata_ = {"language": "en"}
    db.commit()
    yield
    monkeypatch.delenv("I18N_GENERATION_ENABLED")
    get_settings.cache_clear()


def test_digest_in_english_for_user_with_english_saved(db, english):
    items = [
        {"ticker": "ASTS", "status": "disponible", "price_change_pct": 2.5},
        {"ticker": "NBIS", "status": "sin datos"},
        {"ticker": "UBER", "status": "hueco de sesión", "missing_sessions": ["2026-10-08"]},
    ]
    alert = emit_digest_alert(db, make_digest(db, items=items), AS_OF)
    assert alert.title == "Daily summary of your portfolio as of 2026-10-09"
    assert alert.message == (
        "1 of 3 positions moved: ASTS +2.50%. No data: NBIS. "
        "No daily change because of a session gap, not 0: UBER (missing the close of 2026-10-08). "
        "Price changes from yfinance adjusted closes as of 2026-10-09, not your position's P&L. "
        "Portfolio measured when the summary was generated (2026-10-10 07:15 (Madrid time)); "
        "later moves are not included. Summary coverage: partial."
    )
    assert alert.metadata_["coverage"] == "parcial"


def test_digest_in_english_with_no_positions(db, english):
    alert = emit_digest_alert(db, make_digest(db, items=[]), AS_OF)
    assert alert.message.startswith("There were no open positions to summarise.")


def test_digest_stays_spanish_without_saved_language(db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    alert = emit_digest_alert(db, make_digest(db), AS_OF)
    get_settings.cache_clear()
    assert alert.title == "Resumen diario de tu cartera al 2026-10-09"
    assert "Sin datos: NBIS." in alert.message
