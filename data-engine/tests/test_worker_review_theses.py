"""Actor review_theses: solo marca como resueltos los cambios que la nueva
versión de la tesis realmente cubre, y un fallo en una empresa no contamina
a las demás.

Run from data-engine/:
    pytest tests/test_worker_review_theses.py -v
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, Tenant, ThesisChange
from app.services import thesis_service
from app.workers import dramatiq_app as worker

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="rev", name="t", metadata_={})
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    companies = {}
    for t in ("AAA", "BBB", "CCC"):
        c = Company(ticker=t, name=t, exchange="NYSE", currency="USD", company_type="generic", valuation_model="dcf",
                    special_sources=[], special_risks=[], factor_tags=[])
        db.add(c)
        db.flush()
        companies[t] = c
    db.commit()
    state = SimpleNamespace(db=db, companies=companies, generated=[], fail_for=set(), thesis_created=NOW)
    monkeypatch.setattr(worker, "_session", lambda tenant_id, user_id: db)
    monkeypatch.setattr(db, "close", lambda: None)

    class Svc:
        def generate(self, session, ticker, force_new_version=False):
            state.generated.append((ticker, force_new_version))
            if ticker in state.fail_for:
                raise RuntimeError(f"sin datos {ticker}")
            return SimpleNamespace(id=100 + len(state.generated), version=2, status="published", created_at=state.thesis_created)

    monkeypatch.setattr(thesis_service, "ThesisService", Svc)
    return state


def _change(env, ticker, created, from_version=None, review=True):
    ch = ThesisChange(company_id=env.companies[ticker].id, from_version_id=from_version, summary="cambio",
                      requires_review=review)
    env.db.add(ch)
    env.db.flush()
    ch.created_at = created
    env.db.commit()
    return ch


def test_nothing_pending_does_no_work(env):
    out = worker.review_theses.fn(tenant_id=1, user_id="u")
    assert out == {"status": "ok", "actor": "review_theses", "companies_reviewed": 0, "pending_changes": 0, "reviews": []}
    assert env.generated == []


def test_only_companies_with_pending_changes_are_regenerated_without_forcing_new_version(env):
    _change(env, "BBB", NOW - timedelta(hours=1))
    _change(env, "AAA", NOW - timedelta(hours=1), review=False)  # ya revisado: no cuenta
    out = worker.review_theses.fn(tenant_id=1, user_id="u")
    assert env.generated == [("BBB", False)]
    assert out["status"] == "ok" and out["companies_reviewed"] == 1 and out["pending_changes"] == 1
    assert out["reviews"][0]["changes_resolved"] == 1


def test_change_is_resolved_only_if_thesis_is_not_older_than_the_change(env):
    older_thesis = _change(env, "AAA", NOW + timedelta(hours=1))   # cambio POSTERIOR a la tesis
    newer = _change(env, "AAA", NOW - timedelta(hours=1))
    out = worker.review_theses.fn(tenant_id=1, user_id="u")
    env.db.expire_all()
    assert out["reviews"][0]["changes_resolved"] == 1
    assert env.db.get(ThesisChange, newer.id).requires_review is False
    assert env.db.get(ThesisChange, newer.id).to_version_id is not None
    assert env.db.get(ThesisChange, older_thesis.id).requires_review is True  # sigue pendiente


def test_change_that_started_from_the_regenerated_version_is_not_marked_resolved(env):
    # from_version_id == thesis.id (101 en la 1ª llamada): la tesis no cambió, no se resuelve.
    ch = _change(env, "AAA", NOW - timedelta(hours=1), from_version=101)
    out = worker.review_theses.fn(tenant_id=1, user_id="u")
    env.db.expire_all()
    assert out["reviews"][0]["changes_resolved"] == 0
    assert env.db.get(ThesisChange, ch.id).requires_review is True


def test_explicit_ticker_is_uppercased_and_reviews_that_company_only(env):
    _change(env, "AAA", NOW - timedelta(hours=1))
    out = worker.review_theses.fn(tenant_id=1, user_id="u", ticker="ccc")
    assert env.generated == [("CCC", False)]
    assert out["pending_changes"] == 1 and out["reviews"][0]["changes_resolved"] == 0


def test_one_company_failing_gives_partial_and_keeps_the_rest(env):
    _change(env, "AAA", NOW - timedelta(hours=1))
    _change(env, "BBB", NOW - timedelta(hours=1))
    env.fail_for = {"AAA"}
    out = worker.review_theses.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial"
    assert out["errors"] == [{"ticker": "AAA", "type": "RuntimeError", "message": "sin datos AAA"}]
    assert [r["ticker"] for r in out["reviews"]] == ["BBB"]
    env.db.expire_all()
    pend = {c.company_id: c.requires_review for c in env.db.query(ThesisChange).all()}
    assert pend[env.companies["AAA"].id] is True and pend[env.companies["BBB"].id] is False


def test_all_failing_is_error_status(env):
    _change(env, "AAA", NOW - timedelta(hours=1))
    env.fail_for = {"AAA"}
    assert worker.review_theses.fn(tenant_id=1, user_id="u")["status"] == "error"


def test_session_failure_is_a_structured_error_with_context(env, monkeypatch):
    def boom(t, u):
        raise ValueError("Active tenant 1 was not found")

    monkeypatch.setattr(worker, "_session", boom)
    out = worker.review_theses.fn(tenant_id=1, user_id="u", ticker="AAA")
    assert out["status"] == "error"
    assert out["error"]["context"] == {"tenant_id": 1, "user_id": "u", "ticker": "AAA"}


# ---------- presupuesto de tiempo (dead-letter de prod, 1-nov-2026) ----------
# 5 review_theses murieron por TimeLimitExceeded (10 min por defecto): una
# tesis por empresa con LLM, todas en la misma corrida.


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_presupuesto_agotado_corta_entre_empresas_y_encola_la_continuacion(env, monkeypatch):
    from app.services import ticker_news_lane

    clock = _FakeClock()
    real_deadline = ticker_news_lane.Deadline
    monkeypatch.setattr(ticker_news_lane, "Deadline", lambda seconds: real_deadline(seconds, clock=clock))
    sent = []
    monkeypatch.setattr(worker.review_theses, "send", lambda *a, **k: sent.append(k))

    class SlowSvc:
        def generate(self, session, ticker, force_new_version=False):
            env.generated.append((ticker, force_new_version))
            clock.now += worker.REVIEW_THESES_BUDGET_SECONDS + 1  # una tesis gasta todo el presupuesto
            return SimpleNamespace(id=100 + len(env.generated), version=2, status="published", created_at=NOW)

    monkeypatch.setattr(thesis_service, "ThesisService", SlowSvc)
    for t in ("AAA", "BBB", "CCC"):
        _change(env, t, NOW - timedelta(hours=1))
    out = worker.review_theses.fn(tenant_id=1, user_id="u")
    assert [g[0] for g in env.generated] == ["AAA"]
    assert out["status"] == "partial"
    assert out["truncated"] is True
    assert sent == [{"tenant_id": 1, "user_id": "u", "ticker": None, "start_after": "AAA"}]


def test_continuacion_empieza_despues_del_cursor(env):
    for t in ("AAA", "BBB", "CCC"):
        _change(env, t, NOW - timedelta(hours=1))
    out = worker.review_theses.fn(tenant_id=1, user_id="u", start_after="AAA")
    assert [g[0] for g in env.generated] == ["BBB", "CCC"]
    assert out["status"] == "ok"
    assert out["truncated"] is False
