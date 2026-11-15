"""Contrato uniforme: un fallo de _session es error estructurado, nunca raise crudo.

Antes del fix estos actores abrian la sesion FUERA del try: un ValueError
permanente de _session (tenant ausente/inactivo entre el encolado y la
ejecucion) reventaba crudo, dramatiq gastaba los reintentos y el mensaje
acababa en dead-letter sin registro estructurado. _handle_actor_error
clasifica: transitorio relanza (reintenta), permanente devuelve payload.

Run from data-engine/:
    pytest tests/test_worker_session_error_structured.py -v
"""

from types import SimpleNamespace

import pytest

from app.core import config as config_module
from app.workers import dramatiq_app as worker

BOOM = ValueError("tenant_id and user_id are required for background jobs")

# (actor, args, kwargs) con los argumentos minimos para llegar a _session.
ACTORS = [
    (worker.extract_document_kpis, (1,), {}),
    (worker.evaluate_alert_rules, (), {}),
    (worker.refresh_bottlenecks, (), {}),
    (worker.ingest_sec_bottleneck_filings, (), {}),
    (worker.ingest_uk_pdmr_filings, (), {}),
    (worker.ingest_ca_insider_yahoo, (), {}),
    (worker.discover_bottlenecks, (), {}),
    (worker.refresh_portfolio_moves, (), {}),
    (worker.backfill_finnhub_profiles, (), {}),
    (worker.backfill_sec_fundamentals, (), {}),
    (worker.seed_company_fundamentals, (), {}),
    (worker.refresh_esef_fundamentals, (), {}),
    (worker.ingest_corporate_splits, (), {}),
    (worker.sync_portfolio_dividends, (), {}),
    (worker.propicks_radar_scan, (), {}),
    (worker.refresh_valuation_metrics, (), {}),
    (worker.run_propicks_funnel, (), {}),
    (worker.freeze_propicks_snapshot, (), {}),
    (worker.ingest_spy_daily, (), {}),
    (worker.evaluate_dca_signals, (), {}),
    (worker.evaluate_dca_signals_live, (), {}),
    (worker.refresh_earnings_calendar, (), {}),
    (worker.backfill_company_price_history, (1,), {}),
    (worker.dispatch_tracked_news_alerts, (), {}),
    (worker.reconcile_alert_analyses, (), {}),
    (worker.refresh_paper_trades, (), {}),
    (worker.propose_paper_trades, (), {}),
    (worker.sync_paper_dividends, (), {}),
    (worker.evaluate_manual_dca, (1, "token"), {}),
    (worker.recompute_management_alignment, (), {}),
]

IDS = [actor.actor_name for actor, _, _ in ACTORS]


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(worker, "_session", _raise)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(dca_evaluation_enabled=True),
    )
    return worker


def _raise(tenant, user):
    raise BOOM


@pytest.mark.parametrize(("actor", "args", "kwargs"), ACTORS, ids=IDS)
def test_fallo_de_sesion_es_error_estructurado(env, actor, args, kwargs):
    out = actor.fn(*args, tenant_id=1, user_id="u", **kwargs)

    assert isinstance(out, dict), f"{actor.actor_name}: raise crudo en vez de payload"
    assert out["status"] == "error"
    assert out["actor"] == actor.actor_name or actor.actor_name.startswith(str(out.get("actor")))
    assert out["error"]["type"] == "ValueError"
