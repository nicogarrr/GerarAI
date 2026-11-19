"""run_daily_research, refresh_portfolio_moves y sync_paper_dividends:
dispatch diario por tenant con errores por job sin frenar el resto,
digest de la ultima sesion (emitido / ya emitido / parcial si el aviso
falla: nunca verde falso) y dividendos paper con transitorio que relanza."""

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.daily_digest_alerts as dda
import app.services.dividend_ingestion_service as dis
import app.services.portfolio_moves_service as pms
from app.models.entities import Base, Tenant
from app.models.paper_trading import PaperTrade
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return SimpleNamespace(db=db)


# --- run_daily_research -------------------------------------------------

def test_daily_research_encola_los_7_jobs_por_tenant_y_cuenta_errores(env, monkeypatch):
    sends = []

    def fake_send(name):
        def _send(tenant, user):
            if name == "rss_refresh" and tenant == 2:
                raise RuntimeError("broker lleno")
            sends.append((name, tenant))
            return SimpleNamespace(message_id=f"m-{name}-{tenant}")
        return _send

    for attr, name in [("refresh_market_pipeline", "market_refresh"),
                       ("refresh_sec_filings", "sec_refresh"),
                       ("refresh_ir_pages", "ir_refresh"),
                       ("refresh_rss_feeds", "rss_refresh"),
                       ("refresh_news", "news_refresh"),
                       ("consolidate_memory", "memory_consolidation"),
                       ("scan_contradictions", "contradiction_scan")]:
        monkeypatch.setattr(worker, attr, SimpleNamespace(send=fake_send(name)))
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u"), (2, "u")])
    out = worker.run_daily_research.fn()
    assert out["status"] == "partial"  # un fallo de broker no frena el resto
    assert out["workflow"] == "DailyResearchWorkflow"
    assert len(out["queued"]) == 13 and len(out["errors"]) == 1
    assert out["errors"][0]["job"] == "rss_refresh"
    assert out["queued"][0]["message_id"] == "m-market_refresh-1"


def test_daily_research_todo_ok(env, monkeypatch):
    for attr in ("refresh_market_pipeline", "refresh_sec_filings", "refresh_ir_pages",
                 "refresh_rss_feeds", "refresh_news", "consolidate_memory",
                 "scan_contradictions"):
        monkeypatch.setattr(worker, attr, SimpleNamespace(
            send=lambda t, u: SimpleNamespace(message_id="m")))
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u")])
    out = worker.run_daily_research.fn()
    assert out["status"] == "ok" and len(out["queued"]) == 7


# --- refresh_portfolio_moves --------------------------------------------

@pytest.fixture()
def moves_env(env, monkeypatch):
    env.digest = SimpleNamespace(id=7, coverage=0.9)
    env.emitted = SimpleNamespace(id=11)
    monkeypatch.setattr(pms, "build_digest", lambda db_, as_of: env.digest)
    monkeypatch.setattr(dda, "last_session_date", lambda today: dt.date(2026, 11, 18))
    monkeypatch.setattr(dda, "emit_digest_alert",
                        lambda db_, digest, as_of: env.emitted)
    return env


def test_moves_ok_aviso_emitido(moves_env):
    out = worker.refresh_portfolio_moves.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["digest_id"] == 7
    assert out["digest_alert"] == "emitted" and out["digest_alert_id"] == 11


def test_moves_ok_aviso_ya_emitido(moves_env):
    moves_env.emitted = None
    out = worker.refresh_portfolio_moves.fn(tenant_id=1, user_id="u")
    assert out["digest_alert"] == "already_emitted"
    assert out["digest_alert_id"] is None


def test_moves_aviso_fallido_es_parcial_nunca_verde_falso(moves_env, monkeypatch):
    monkeypatch.setattr(dda, "emit_digest_alert",
                        lambda db_, digest, as_of: (_ for _ in ()).throw(
                            RuntimeError("smtp caido")))
    out = worker.refresh_portfolio_moves.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and out["digest_alert"] == "error"
    assert "smtp caido" in out["alert_error"]


def test_moves_error_construyendo_digest(moves_env, monkeypatch):
    monkeypatch.setattr(pms, "build_digest",
                        lambda db_, as_of: (_ for _ in ()).throw(ValueError("sin datos")))
    out = worker.refresh_portfolio_moves.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_portfolio_moves"


# --- sync_paper_dividends ------------------------------------------------

@pytest.fixture()
def div_env(env, monkeypatch):
    env.outcomes = {}

    class FakeService:
        async def sync_company(self, db_, *, ticker):
            outcome = env.outcomes.get(ticker, {"status": "ok"})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(dis, "DividendIngestionService", FakeService)
    return env


def _paper_trade(db, ticker, status="open"):
    if db.get(Tenant, 1) is None:
        db.add(Tenant(id=1, external_id="ext-1", name="t1"))
    db.add(PaperTrade(tenant_id=1, ticker=ticker, status=status, quantity=1,
                      proposal_key=f"k-{ticker}-{status}", direction="long",
                      horizon="swing", thesis="t", conviction=0.5,
                      proposed_entry=10, stop=9, target=11, inference_basis="b",
                      entry_price=10, entry_at=dt.datetime(2026, 1, 1)))
    db.commit()


def test_dividendos_solo_tickers_con_trades_vivos(div_env):
    _paper_trade(div_env.db, "ACME")
    _paper_trade(div_env.db, "CERRADA", status="closed")
    out = worker.sync_paper_dividends.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["tickers"] == 1
    assert out["synced"] == ["ACME"]


def test_dividendos_unavailable_y_fallo_no_transitorio(div_env):
    _paper_trade(div_env.db, "ACME")
    _paper_trade(div_env.db, "BETA")
    div_env.outcomes = {"ACME": {"status": "unavailable"}, "BETA": ValueError("fila")}
    out = worker.sync_paper_dividends.fn(tenant_id=1, user_id="u")
    assert out["unavailable"] == ["ACME"] and out["failed"] == ["BETA"]


def test_dividendos_transitorio_relanza(div_env):
    _paper_trade(div_env.db, "ACME")
    div_env.outcomes = {"ACME": ConnectionError("pg caido")}
    with pytest.raises(ConnectionError):
        worker.sync_paper_dividends.fn(tenant_id=1, user_id="u")
