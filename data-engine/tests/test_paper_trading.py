from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.paper_trading import router
from app.core.database import Base, get_db
from app.models import Tenant
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_trading_service import (
    apply_quote,
    create_proposal,
    deadline,
    pnl,
    refresh_trades,
    scoreboard,
    trade_out,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def body(**kwargs):
    return {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


def trade(**kwargs):
    return PaperTrade(**PaperProposal(**body()).model_dump(), author="LLM", inference_label="inferencia", status="pending", created_at=NOW-timedelta(seconds=1), **kwargs)


def quote(price=100, at=NOW, currency="USD"):
    return {"live_c": price, "live_t": at.timestamp(), "currency": currency}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([Tenant(id=1, external_id="paper-1"), Tenant(id=2, external_id="paper-2")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


@pytest.mark.parametrize("override", [{"conviction": "nan"}, {"target": "Infinity"}, {"quantity": 0}, {"stop": 110}, {"direction": "invalid"}, {"author": "human"}, {"ticker": "../../x"}, {"horizon": "future"}])
def test_invalid_proposals(override):
    with pytest.raises(ValidationError):
        PaperProposal(**body(**override))


def test_real_fill_not_llm_entry_and_gap_stop():
    row = trade()
    assert apply_quote(row, quote(98), NOW)
    assert row.entry_price == Decimal(98)
    assert row.entry_price != row.proposed_entry
    assert row.entry_at == NOW
    later = NOW + timedelta(minutes=30)
    assert apply_quote(row, quote(85, later), later)
    assert row.exit_price == Decimal(85)  # not the ideal stop 90
    assert row.close_reason == "stop"
    assert pnl(row, row.exit_price) == Decimal(-26)
    assert not apply_quote(row, quote(130, later + timedelta(minutes=30)), later + timedelta(minutes=30))


@pytest.mark.parametrize("bad_quote", [{}, {"c": 100, "ct": NOW.timestamp()}, quote(0), quote(float("nan")), quote(at=NOW-timedelta(days=2)), quote(at=NOW+timedelta(seconds=1)), quote(currency=""), {"live_c": 100, "live_t": True, "currency": "USD"}])
def test_missing_stale_future_quote_does_not_fill(bad_quote):
    row = trade()
    assert not apply_quote(row, bad_quote, NOW)
    assert row.entry_price is None
    assert row.status == "pending"


@pytest.mark.parametrize("price", [105, 89, 125])
def test_limit_or_invalid_gap_not_filled(price):
    row = trade()
    assert not apply_quote(row, quote(price), NOW)


def test_short_pnl_and_target():
    row = PaperTrade(**PaperProposal(**body(direction="short", stop=110, target=80)).model_dump(), status="pending", created_at=NOW-timedelta(seconds=1))
    assert apply_quote(row, quote(102), NOW)
    later = NOW + timedelta(hours=1)
    assert apply_quote(row, quote(75, later), later)
    assert row.close_reason == "target"
    assert pnl(row, row.exit_price) == 54


def test_repeated_out_of_order_and_currency_change():
    row = trade()
    apply_quote(row, quote(), NOW)
    assert not apply_quote(row, quote(110), NOW)
    assert not apply_quote(row, quote(110, NOW-timedelta(minutes=1)), NOW)
    assert not apply_quote(row, quote(110, NOW+timedelta(minutes=1), "EUR"), NOW+timedelta(minutes=1))
    assert row.mark_price == 100


def test_stale_mark_not_reported_as_current():
    row = trade()
    apply_quote(row, quote(), NOW)
    out = trade_out(row, NOW+timedelta(days=2))
    assert out["mark_price"] is None
    assert out["unrealized_pnl"] is None
    assert out["quote_status"] == "sin_datos"


def test_time_horizon_and_leap_day():
    row = trade()
    apply_quote(row, quote(), NOW)
    later = NOW + timedelta(days=30)
    apply_quote(row, quote(110, later), later)
    assert row.close_reason == "horizon"
    row.horizon = "five_years"
    row.entry_at = datetime(2024, 2, 29, tzinfo=UTC)
    assert deadline(row) == datetime(2029, 2, 28, tzinfo=UTC)


def test_idempotence_conflict_and_tenant_isolation(db):
    proposal = PaperProposal(**body())
    row = create_proposal(db, proposal)
    assert row.author == "LLM" and row.inference_label == "inferencia"
    assert create_proposal(db, proposal).id == row.id
    with pytest.raises(ValueError):
        create_proposal(db, PaperProposal(**body(target=130)))
    db.info["tenant_id"] = 2
    assert db.scalar(select(PaperTrade).where(PaperTrade.id == row.id)) is None
    other = create_proposal(db, proposal)
    assert other.id != row.id
    assert other.tenant_id == 2


def test_worker_deduplicates_and_never_fabricates(db):
    create_proposal(db, PaperProposal(**body()))
    create_proposal(db, PaperProposal(**body(proposal_key="run-2-ASTS")))
    calls = []
    def fetch(ticker):
        calls.append(ticker)
        return {}
    result = refresh_trades(db, fetch)
    assert result["updated"] == 0
    assert calls == ["ASTS"]
    assert all(r.entry_price is None for r in db.scalars(select(PaperTrade)).all())


def test_score_separates_currency_horizon_and_empty_samples():
    assert scoreboard([])["groups"] == []
    rows = []
    for direction, currency, horizon, exit_price in [("long", "USD", "short", 110), ("long", "EUR", "short", 85), ("long", "USD", "five_years", 100)]:
        row = trade()
        row.direction, row.currency, row.horizon = direction, currency, horizon
        row.status, row.entry_price, row.exit_price = "closed", Decimal(100), Decimal(exit_price)
        rows.append(row)
    result = scoreboard(rows)
    assert len(result["groups"]) == 3
    assert {g["realized_pnl"] for g in result["groups"]} == {Decimal(20), Decimal(-30), Decimal(0)}
    assert sum(g["flat"] for g in result["groups"]) == 1


def test_rest_is_scoped_and_rejects_client_prices(db):
    app = FastAPI()
    app.include_router(router, prefix="/paper-trading")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.post("/paper-trading/proposals", json=body())
        assert response.status_code == 201
        proposal_id = response.json()["id"]
        assert response.json()["entry_price"] is None
        assert "tenant_id" not in response.json()
        assert client.post("/paper-trading/proposals", json=body(entry_price=100)).status_code == 422
        assert len(client.get("/paper-trading/proposals").json()) == 1
        db.info["tenant_id"] = 2
        assert client.get("/paper-trading/proposals").json() == []
        assert client.get("/paper-trading/scoreboard").json()["groups"] == []
        # Avoid network call while testing a foreign id.
        from unittest.mock import patch

        import app.api.routes.paper_trading as routes
        with patch.object(routes, "refresh_trades"):
            assert client.post(f"/paper-trading/proposals/{proposal_id}/close").status_code == 404


def test_quote_at_proposal_time_is_not_forward():
    row = trade()
    row.created_at = NOW
    assert not apply_quote(row, quote(), NOW)


def test_conviction_bins_do_not_invent_samples():
    bins = scoreboard([])["conviction_bins"]
    assert all(b["hit_rate"] is None and b["closed"] == 0 for b in bins)


def test_decimal_idempotency_normalizes_before_persistence(db):
    payload = body(conviction="0.812345", proposed_entry="100.1234567", stop="90.1234567",
                   target="120.1234567", quantity="2.1234567")
    proposal = PaperProposal(**payload)
    row = create_proposal(db, proposal)
    db.expire_all()
    assert create_proposal(db, PaperProposal(**payload)).id == row.id
    assert row.conviction == Decimal("0.8123")
    assert row.proposed_entry == Decimal("100.123457")
    with pytest.raises(ValueError):
        create_proposal(db, PaperProposal(**{**payload, "proposed_entry": "101.1234567"}))


def test_precision_cannot_round_levels_or_quantity_to_invalid_values():
    for overrides in ({"quantity": "0.0000001"}, {"stop": "99.9999999"},
                      {"proposed_entry": "100000000000000"}):
        with pytest.raises(ValidationError):
            PaperProposal(**body(**overrides))


def test_provider_has_zero_checkout_and_concurrent_close_is_preserved(tmp_path):
    from sqlalchemy.pool import QueuePool
    engine = create_engine(f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool,
                           pool_size=1, max_overflow=0, pool_timeout=0.2)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="pool-tenant"))
        session.commit()
        session.info["tenant_id"] = 1
        row = create_proposal(session, PaperProposal(**body()))
        row_id = row.id
        def fetch(ticker):
            assert engine.pool.checkedout() == 0
            # Another session closes the position while the first is in network.
            with Session(engine) as closer:
                closer.info["tenant_id"] = 1
                current = closer.get(PaperTrade, row_id)
                current.status = "closed"
                current.entry_price = Decimal(100)
                current.exit_price = Decimal(110)
                current.close_reason = "manual"
                closer.commit()
            return quote(98, datetime.now(UTC))
        result = refresh_trades(session, fetch)
        assert result["updated"] == 0
        session.expire_all()
        stored = session.get(PaperTrade, row_id)
        assert stored.status == "closed"
        assert stored.exit_price == Decimal(110)
        assert stored.close_reason == "manual"
    engine.dispose()


def test_refresh_race_newer_mark_is_not_overwritten(tmp_path):
    from sqlalchemy.pool import QueuePool
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", poolclass=QueuePool,
                           pool_size=1, max_overflow=0, pool_timeout=0.2)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="race-tenant"))
        session.commit()
        session.info["tenant_id"] = 1
        row = create_proposal(session, PaperProposal(**body()))
        row_id = row.id
        latest = datetime.now(UTC)
        older = latest - timedelta(minutes=1)
        def fetch(ticker):
            assert engine.pool.checkedout() == 0
            with Session(engine) as other:
                other.info["tenant_id"] = 1
                current = other.get(PaperTrade, row_id)
                current.status = "open"
                current.entry_price, current.entry_at = Decimal(98), older
                current.mark_price, current.mark_at = Decimal(110), latest
                current.currency = "USD"
                other.commit()
            return quote(99, older)
        assert refresh_trades(session, fetch)["updated"] == 0
        session.expire_all()
        stored = session.get(PaperTrade, row_id)
        assert stored.mark_price == Decimal(110)
        assert stored.status == "open"
    engine.dispose()


def test_non_numeric_decimal_rejected_by_precision_normalizer():
    with pytest.raises(ValidationError, match="Número fuera de la precisión persistida"):
        PaperProposal(**body(conviction="not-a-number"))


def test_short_target_at_entry_rejected_by_level_validator():
    with pytest.raises(ValidationError, match="Short: objetivo < entrada propuesta < stop"):
        PaperProposal(**body(direction="short", target="100", stop="110"))


def test_scoreboard_endpoint_exposes_calibration_block_nd_when_empty(db):
    app = FastAPI()
    app.include_router(router, prefix="/paper-trading")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        data = client.get("/paper-trading/scoreboard").json()
    assert data["groups"] == [] and data["conviction_bins"]
    cal = data["calibracion"]
    assert cal["brier"] is None and cal["muestra_insuficiente"] is True
    assert cal["etiqueta"] == "INFERIDO"


@pytest.mark.parametrize("currency", [None, "USD"])
def test_identical_proposal_retry_after_fill_uses_immutable_requested_currency(db, currency):
    proposal = PaperProposal(**body(currency=currency))
    row = create_proposal(db, proposal)
    assert row.proposal_currency_known is True
    assert row.proposal_currency == currency
    row.created_at = NOW - timedelta(seconds=1)
    assert apply_quote(row, quote(98), NOW)
    db.commit()
    assert row.currency == "USD"
    assert create_proposal(db, proposal).id == row.id
    assert row.proposal_currency == currency
    # Omitting a requested currency, or adding one to an unrestricted proposal,
    # changes its original terms even if the observed mark is USD in both cases.
    with pytest.raises(ValueError):
        create_proposal(db, PaperProposal(**body(currency="USD" if currency is None else None)))


def test_historical_proposal_unknown_requested_currency_is_not_inferred_from_mark(db):
    row = trade()
    row.currency = "USD"
    db.add(row)
    db.commit()
    assert row.proposal_currency_known is False
    for currency in (None, "USD"):
        with pytest.raises(ValueError, match="histórica"):
            create_proposal(db, PaperProposal(**body(currency=currency)))
    db.refresh(row)
    assert row.currency == "USD"
    assert row.proposal_currency is None
    assert row.proposal_currency_known is False


def test_historical_unknown_retry_route_is_explicit_409(db):
    from fastapi import HTTPException

    from app.api.routes.paper_trading import propose

    row = trade()
    row.currency = "USD"
    db.add(row)
    db.commit()
    with pytest.raises(HTTPException) as caught:
        propose(PaperProposal(**body()), db)
    assert caught.value.status_code == 409
    assert "histórica" in caught.value.detail
    assert row.proposal_currency_known is False
