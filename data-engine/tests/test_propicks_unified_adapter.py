"""Adaptador BD -> contrato propicks-unified-v1 y ruta GET /propicks/unified."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    MarketPrice,
    Position,
    ProPickCandidate,
    ProPickRun,
    Tenant,
    WatchItem,
)
from app.services import propicks_unified_adapter as adapter
from app.services.propicks_radar_store import FORMULA_VERSION, save_snapshot
from app.services.propicks_unified_adapter import load_unified
from app.services.valuation_metrics_service import METRIC_PB, METRIC_VERSION, STATUS_DISAGREE

AS_OF = date(2026, 11, 16)
NOW = datetime(2026, 11, 15, 22, 0, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(engine)()
    s.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
    s.commit()
    s.info["tenant_id"] = 1
    return s


def _co(db, cid, ticker=None, **kw) -> Company:
    c = Company(id=cid, ticker=ticker or f"T{cid}", name=f"Co {cid}", exchange="NYSE",
                currency="USD", sector="Industrials", industry="x", company_type="large_cap",
                valuation_model="dcf", **kw)
    db.add(c)
    db.commit()
    return c


def _run(db, tenant=1, universe=500) -> ProPickRun:
    r = ProPickRun(tenant_id=tenant, as_of=NOW, status="completed", funnel_version="funnel-v9",
                   universe_size=universe)
    db.add(r)
    db.flush()
    return r


def _cand(db, run, cid, score=71.234, passed=True, tenant=1) -> None:
    db.add(ProPickCandidate(tenant_id=tenant, run_id=run.id, company_id=cid, passed=passed,
                            score=score))
    db.commit()


def _price(db, cid, day, close=10.0) -> None:
    db.add(MarketPrice(company_id=cid, date=day, open=close, high=close, low=close, close=close,
                       adj_close=close, volume=1000, quote_currency="USD", source="t"))
    db.commit()


def _pb(db, cid, value, period, status="ok") -> None:
    db.add(CalculatedMetric(tenant_id=1, company_id=cid, metric=METRIC_PB, value=value,
                            period=period, formula="t", definition_version=METRIC_VERSION,
                            status=status, unit="decimal", fiscal_year=int(period[:4])))
    db.commit()


def test_empty_when_tenant_has_no_run(db):
    res = load_unified(db, as_of=AS_OF)
    assert res.items == [] and res.coverage.universe is None
    assert res.blocks["quality"].status == "empty"


def test_score_exact_policy_and_universe_from_run(db):
    _co(db, 1)
    _cand(db, _run(db, universe=500), 1, score=71.234)
    res = load_unified(db, as_of=AS_OF)
    (it,) = res.items
    assert res.coverage.universe == 500 and res.coverage.evaluated == 1
    assert it.quality.score.value == 71.234
    assert it.quality.policyVersion == "quality-v1"
    # procedencia temporal: la política del run que produjo el score, no la constante actual
    assert it.quality.scorePolicyVersion == "funnel-v9"
    assert it.quality.score.formulaVersion == "funnel-v9"
    assert it.instrumentId == "company:1" and it.listing.identityStatus == "unverified"
    assert "funnel-v9" in it.evidenceFlags[0]


def test_quality_comes_from_quality_v1_overlay_not_funnel_flag(db):
    # embudo pasa, pero faltan apalancamiento/FCF/liquidez/cap => quality-v1 no pasa
    _co(db, 1)
    _cand(db, _run(db), 1, passed=True)
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.quality.passed is False
    assert "leverage_missing_or_high" in it.quality.reasonCodes
    assert it.eligibility.state == "excluded"


def test_price_and_pb_provenance_and_staleness(db):
    _co(db, 1)
    _cand(db, _run(db), 1)
    _price(db, 1, AS_OF - timedelta(days=30), 12.5)
    _pb(db, 1, 0.8, (AS_OF - timedelta(days=30)).isoformat())
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.valuation.price.value == 12.5 and it.valuation.price.status == "stale"
    assert it.valuation.price.asOf == (AS_OF - timedelta(days=30)).isoformat()
    assert it.valuation.priceToBook.status == "stale"
    assert it.valuation.fcfYield.status == "missing"
    assert it.valuation.marginOfSafety.status == "missing"


def test_pb_disagreement_is_disputed(db):
    _co(db, 1)
    _cand(db, _run(db), 1)
    _pb(db, 1, 0.8, AS_OF.isoformat(), status=STATUS_DISAGREE)
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.valuation.priceToBook.status == "disputed"


def test_delisted_company_excluded(db):
    _co(db, 1, ticker="ELME", delisted_at=datetime(2026, 9, 1, tzinfo=UTC))
    _cand(db, _run(db), 1)
    _pb(db, 1, 0.3, AS_OF.isoformat())
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.listing.status == "delisted" and it.eligibility.state == "excluded"


def test_dca_snapshot_forming_vs_confirmed(db):
    _co(db, 1)
    _cand(db, _run(db), 1)
    save_snapshot(db, 1, {
        "status": "ok", "formula_version": FORMULA_VERSION, "price_verified": True,
        "price_date": "2026-11-14", "source": "t",
        "current": {"level": 3, "status": "forming", "signal_date": "2026-11-14"},
        "confirmed": {"level": 4, "status": "confirmed", "signal_date": "2026-10-31"},
    }, now=NOW)
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.dca.level.value == 3 and it.dca.periodState == "forming"
    assert it.dca.confirmedLevel.value == 4 and it.dca.priceVerified is True
    assert it.dca.formulaVersion == FORMULA_VERSION


def test_no_dca_snapshot_is_missing_not_zero(db):
    _co(db, 1)
    _cand(db, _run(db), 1)
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.dca.status == "missing" and it.dca.level.value is None


def test_dca_read_failure_marks_partial_and_keeps_quality(db, monkeypatch):
    _co(db, 1)
    _cand(db, _run(db), 1, score=55.5)

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(adapter, "latest_public_signals", boom)
    res = load_unified(db, as_of=AS_OF)
    assert res.status == "partial" and res.blocks["dca"].status == "error"
    assert res.items[0].quality.score.value == 55.5


def test_tenant_isolation(db):
    _co(db, 1)
    _co(db, 2)
    _cand(db, _run(db, tenant=1), 1)
    db.info["tenant_id"] = 2
    _cand(db, _run(db, tenant=2), 2, tenant=2)
    db.info["tenant_id"] = 1
    assert [i.instrumentId for i in load_unified(db, as_of=AS_OF).items] == ["company:1"]
    db.info["tenant_id"] = 2
    assert [i.instrumentId for i in load_unified(db, as_of=AS_OF).items] == ["company:2"]


def test_tracking_watched_and_held(db):
    _co(db, 1, ticker="WAT")
    _co(db, 2, ticker="HLD")
    _co(db, 3, ticker="NON")
    run = _run(db)
    for cid in (1, 2, 3):
        _cand(db, run, cid)
    db.add(WatchItem(tenant_id=1, symbol="WAT"))
    db.add(Position(tenant_id=1, company_id=2, quantity=5))
    db.commit()
    by = {i.listing.ticker: i for i in load_unified(db, as_of=AS_OF).items}
    assert by["WAT"].tracking.watched is True and by["WAT"].tracking.held is False
    assert by["HLD"].tracking.held is True
    assert by["NON"].tracking.held is False and by["NON"].tracking.watched is False


def test_limit_applies_and_orders_by_score(db):
    run = _run(db)
    for cid, score in ((1, 10.0), (2, 90.0), (3, 50.0)):
        _co(db, cid)
        _cand(db, run, cid, score=score)
    res = load_unified(db, as_of=AS_OF, limit=2)
    assert [i.quality.score.value for i in res.items] == [90.0, 50.0]


def test_pb_persisted_status_not_ok_is_never_ok(db):
    for i, st in enumerate(("invalid", "missing", "unverified", "algo_raro"), start=1):
        _co(db, i)
    run = _run(db)
    for i, st in enumerate(("invalid", "missing", "unverified", "algo_raro"), start=1):
        _cand(db, run, i)
        _pb(db, i, 0.8, AS_OF.isoformat(), status=st)
    by = {i.instrumentId: i for i in load_unified(db, as_of=AS_OF).items}
    assert by["company:1"].valuation.priceToBook.status == "invalid"
    assert by["company:1"].valuation.priceToBook.value is None
    assert by["company:2"].valuation.priceToBook.status == "missing"
    assert by["company:3"].valuation.priceToBook.status == "unverified"
    assert by["company:4"].valuation.priceToBook.status == "unverified"
    assert all(i.eligibility.state != "investigate" for i in by.values())


def test_pb_unreadable_period_is_unverified(db):
    _co(db, 1)
    _cand(db, _run(db), 1)
    _pb(db, 1, 0.8, "2026-FY")  # periodo no es fecha
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.valuation.priceToBook.status == "unverified"
    assert it.eligibility.state != "investigate"


def test_blank_funnel_version_does_not_label_score(db):
    _co(db, 1)
    run = _run(db)
    run.funnel_version = ""
    db.commit()
    _cand(db, run, 1, score=50.0)
    (it,) = load_unified(db, as_of=AS_OF).items
    assert it.quality.score.value is None and it.quality.score.status == "missing"
