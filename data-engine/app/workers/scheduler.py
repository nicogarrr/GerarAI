from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from functools import partial

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings
from app.services.etf_holdings import refresh_etf_holdings
from app.services.retention_service import run_retention
from app.services.thesis_job_service import reconcile_thesis_dispatches
from app.workers.dramatiq_app import (
    backfill_document_kpis,
    backfill_finnhub_profiles,
    backfill_sec_fundamentals,
    consolidate_memory,
    dispatch_earnings_reminders,
    dispatch_insider_alerts,
    dispatch_macro_reminders,
    dispatch_tracked_news_alerts,
    evaluate_alert_rules,
    evaluate_dca_signals,
    freeze_propicks_snapshot,
    ingest_ca_insider_yahoo,
    ingest_class_shares_outstanding,
    ingest_corporate_splits,
    ingest_sec_bottleneck_filings,
    ingest_spy_daily,
    ingest_uk_pdmr_filings,
    propose_paper_trades,
    propicks_radar_scan,
    recompute_fundamental_metrics,
    reconcile_alert_analyses,
    reconcile_alert_deliveries,
    refresh_asts_catalog,
    refresh_bottlenecks,
    refresh_earnings_calendar,
    refresh_esef_fundamentals,
    refresh_ir_pages,
    refresh_macro_context,
    refresh_macro_news,
    refresh_market_pipeline,
    refresh_news,
    refresh_paper_trades,
    refresh_portfolio_moves,
    refresh_portfolio_prices_intraday,
    refresh_propicks_prices,
    refresh_rss_feeds,
    refresh_sec_filings,
    refresh_ticker_news,
    refresh_valuation_metrics,
    review_theses,
    run_daily_research,
    run_propicks_funnel,
    scan_contradictions,
    scan_insider_watchlist,
    scan_schedule13dg_watchlist,
    sync_ibkr_flex,
    sync_investor_holdings,
    sync_official_closes,
    sync_paper_dividends,
    sync_portfolio_dividends,
    sync_tenant_ibkr_connections,
    sync_tenant_ibkr_connections_dedicated,
    tenant_contexts,
)

JOB_DEFAULTS = {
    "replace_existing": True,
    "max_instances": 1,
    "coalesce": True,
    "misfire_grace_time": 900,
}


# Un job por intervalo corto (<= 1 h) dispara una vez poco despues de arrancar el
# scheduler. APScheduler guarda el siguiente disparo en memoria y los intervalos
# no disparan al arrancar: con deploys seguidos (cada reinicio reinicia el
# contador) el rss de 15 min llego a pasar mas de una hora sin correr. Los de
# 2 h o mas (CelesTrak, universo completo, noticias del universo) no se tocan:
# son pesados o limitados por la fuente. El escalonado evita una rafaga y nunca
# supera el propio intervalo del job (el de 1 min no se retrasa). Es un adelanto
# best-effort, no una garantia de ejecucion unica: un reinicio posterior vuelve a
# disparar y un job con max_instances=1 puede saltarse el disparo.
STARTUP_FIRE_MAX_INTERVAL_SECONDS = 3600
STARTUP_FIRE_JITTER_SECONDS = (30, 300)  # tope; se recorta al intervalo del job


def _interval_seconds(trigger_args: dict) -> float:
    return (
        trigger_args.get("weeks", 0) * 604800
        + trigger_args.get("days", 0) * 86400
        + trigger_args.get("hours", 0) * 3600
        + trigger_args.get("minutes", 0) * 60
        + trigger_args.get("seconds", 0)
    )


def _startup_fire_time(trigger_args: dict, now: datetime | None = None) -> datetime | None:
    seconds = _interval_seconds(trigger_args)
    if seconds <= 0 or seconds > STARTUP_FIRE_MAX_INTERVAL_SECONDS:
        return None
    base = now or datetime.now(UTC)
    low, high = STARTUP_FIRE_JITTER_SECONDS
    high = min(high, seconds)
    low = min(low, high / 2)
    return base + timedelta(seconds=random.uniform(low, high))


def _register(scheduler: BlockingScheduler, func, trigger: str, *, job_id: str, **trigger_args) -> None:
    if trigger == "interval" and "next_run_time" not in trigger_args:
        first = _startup_fire_time(trigger_args)
        if first is not None:
            trigger_args["next_run_time"] = first
    scheduler.add_job(
        func,
        trigger,
        id=job_id,
        **JOB_DEFAULTS,
        **trigger_args,
    )


def enqueue_insider_scan(*, lookback: int, max_new_fetches: int) -> dict:
    """Fan-out del monitor insider con el alcance propio de cada cadencia."""
    queued = []
    for tenant_id, user_id in tenant_contexts():
        message = scan_insider_watchlist.send(
            tenant_id, user_id, lookback, max_new_fetches
        )
        queued.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "message_id": str(message.message_id),
            }
        )
    return {
        "actor": scan_insider_watchlist.actor_name,
        "lookback": lookback,
        "max_new_fetches": max_new_fetches,
        "queued": queued,
    }


def enqueue_for_all_tenants(actor, **kwargs) -> dict:
    queued = []
    for tenant_id, user_id in tenant_contexts():
        message = actor.send(tenant_id, user_id, **kwargs)
        queued.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "message_id": str(message.message_id),
            }
        )
    return {"actor": actor.actor_name, "queued": queued}


def enqueue_official_closes_once() -> dict:
    """Prices are global, unlike tenant portfolios: enqueue only one context."""
    contexts = list(tenant_contexts())
    if not contexts:
        return {"actor": "sync_official_closes", "queued": []}
    tenant_id, user_id = contexts[0]
    message = sync_official_closes.send(tenant_id, user_id)
    return {"actor": "sync_official_closes", "queued": [str(message.message_id)]}


def build_scheduler(*, background: bool = False) -> BlockingScheduler | BackgroundScheduler:
    scheduler_cls = BackgroundScheduler if background else BlockingScheduler
    scheduler = scheduler_cls(timezone="UTC")
    # Direct, short outbox check: must not wait behind ingestion on default.
    _register(scheduler, reconcile_thesis_dispatches, "interval",
              job_id="thesis_dispatch_recovery", minutes=1)

    # Precios a dos velocidades, mismo criterio que news (decision
    # 2026-09-25): cartera+watchlist cada hora; universo completo cada 6 h en
    # background. El screener sirve quotes en vivo por su propia via de
    # vendors (screeners.py), asi que su frescura no depende del barrido de
    # universo; lo que lee market_prices local (movers, alertas fuera de
    # cartera+watchlist) pasa a cadencia de 6 h.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_market_pipeline, scope="tracked"),
        "interval",
        job_id="market_refresh",
        hours=1,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_market_pipeline, scope="universe"),
        "interval",
        job_id="market_refresh_universe",
        hours=6,
    )
    # Local-only reconciliation covers pre-existing ingested letters/chunks/news.
    _register(scheduler, partial(enqueue_for_all_tenants, refresh_bottlenecks),
              "interval", job_id="bottleneck_refresh", hours=1)
    # Texto de filings SEC (8-K/10-K/10-Q) -> documentos: cada 6 h; el refresh
    # horario de cuellos reconcilia lo nuevo como cualquier otro documento.
    _register(scheduler, partial(enqueue_for_all_tenants, ingest_sec_bottleneck_filings),
              "interval", job_id="sec_bottleneck_filings", hours=6)
    # Insiders Canada (Yahoo quoteSummary, no oficial): 2 GET por corrida cada 6 h.
    _register(scheduler, partial(enqueue_for_all_tenants, ingest_ca_insider_yahoo),
              "interval", job_id="ca_insider_yahoo", hours=6)
    _register(scheduler, refresh_macro_context.send, "cron", job_id="macro_context_refresh", hour=23, minute=10)
    # Holdings oficiales de ETFs tematicos (UFO, NASA): 1 descarga por ETF y semana.
    _register(scheduler, refresh_etf_holdings, "cron", job_id="etf_holdings_refresh", day_of_week="mon", hour=7, minute=20)
    # Cartera real desde IBKR Flex (solo lectura). El actor no hace nada si
    # faltan token, query id o IBKR_FLEX_TENANT_ID; corre una vez al dia, con el
    # extracto del ultimo dia habil ya generado por IBKR.
    _register(scheduler, sync_ibkr_flex.send, "cron", job_id="ibkr_flex_sync", hour=6, minute=40)
    # Default behavior stays unchanged until the dedicated consumer is installed.
    ibkr_actor = sync_tenant_ibkr_connections
    if get_settings().ibkr_dedicated_sync_enabled:
        ibkr_actor = sync_tenant_ibkr_connections_dedicated
        _register(scheduler, ibkr_actor.send, "cron", job_id="tenant_ibkr_post_close",
                  day_of_week="mon-fri", hour=18, minute=0, timezone="America/New_York")
    _register(scheduler, ibkr_actor.send, "cron", job_id="tenant_ibkr_flex_sync", hour=6, minute=50)
    # One global GP + SupGP fetch every 2 h, never per tenant or more often.
    _register(scheduler, refresh_asts_catalog.send, "interval", job_id="asts_celestrak_refresh", hours=2)
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_rss_feeds),
        "interval",
        job_id="rss_refresh",
        minutes=15,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_news, scope="tracked"),
        "interval",
        job_id="news_refresh",
        minutes=30,
    )
    # Universo completo en background, al ritmo que permite GDELT con
    # pacing (~3 h/tenant): dos velocidades, decisión 2026-09-25.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_news, scope="all"),
        "interval",
        job_id="news_refresh_universe",
        hours=6,
    )
    # Carril de noticias por ticker sin GDELT (Yahoo Finance RSS + Google News
    # RSS): GDELT devuelve 429 en la mayoria de las consultas y dejaba a ASTS
    # y SPCX sin titulares. Tracked cada 30 min; universo US cada 6 h.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_ticker_news, scope="tracked"),
        "interval",
        job_id="ticker_news_refresh",
        minutes=30,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_ticker_news, scope="all"),
        "interval",
        job_id="ticker_news_refresh_universe",
        hours=6,
    )
    # Carril macro (temas sin ticker: oro/bancos centrales, tipos, etc.);
    # 13 consultas GDELT por tenant dentro del pacing global.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_macro_news),
        "interval",
        job_id="macro_news_refresh",
        hours=1,
    )
    # Durabilidad AlertAnalysis: recupera filas perdidas aunque el evento
    # ya no pase el filtro de elegibilidad de evaluate().
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, reconcile_alert_analyses),
        "interval",
        job_id="alert_analysis_reconcile",
        hours=1,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_ir_pages),
        "interval",
        job_id="ir_refresh",
        hours=1,
    )
    # Backpressure KPI: recupera extracciones diferidas cuando la cola
    # kpis vuelve a tener capacidad (ver backfill_document_kpis).
    _register(
        scheduler,
        backfill_document_kpis.send,
        "interval",
        job_id="kpi_backfill",
        minutes=5,
    )
    # Cobertura de ratios derivados (roe/margenes/roic/wacc) para todo el
    # universo con hechos: sin este barrido los CalculatedMetric solo se
    # escribian on-demand y los screeners fundamentales no tenian datos.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, recompute_fundamental_metrics),
        "cron",
        job_id="fundamental_metrics_recompute",
        hour=3,
        minute=40,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_sec_filings),
        "cron",
        job_id="sec_refresh",
        hour="*/4",
        minute=5,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, scan_contradictions),
        "cron",
        job_id="contradiction_scan",
        hour="*",
        minute=20,
    )
    # Outbox de alertas: reconcilia claims expirados (sending/unknown/
    # throttled) que nadie volvio a despachar.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, reconcile_alert_deliveries),
        "interval",
        job_id="alert_delivery_reconcile",
        minutes=10,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, consolidate_memory),
        "cron",
        job_id="memory_consolidation",
        hour=3,
        minute=15,
    )
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, review_theses),
        "cron",
        job_id="thesis_review",
        hour=7,
        minute=0,
    )
    _register(
        scheduler,
        run_daily_research.send,
        "cron",
        job_id="daily_research",
        hour=6,
        minute=30,
    )
    # PR-3 insider monitor: 15 min durante el dia (jittered), catch-up diario
    # mas profundo tras el cierre de EDGAR, reconciliacion semanal completa.
    _register(
        scheduler,
        partial(enqueue_insider_scan, lookback=20, max_new_fetches=25),
        "interval",
        job_id="insider_watchlist_scan",
        minutes=15,
        jitter=120,
    )
    _register(
        scheduler,
        partial(enqueue_insider_scan, lookback=100, max_new_fetches=60),
        "cron",
        job_id="insider_watchlist_daily",
        hour=22,
        minute=30,
        jitter=300,
    )
    _register(
        scheduler,
        partial(enqueue_insider_scan, lookback=500, max_new_fetches=200),
        "cron",
        job_id="insider_watchlist_weekly",
        day_of_week="sun",
        hour=3,
        minute=45,
    )
    # SC 13D/13G (titulares >5%): evento raro, una corrida diaria acotada
    # tras el cierre de EDGAR basta; coste 0 (submissions JSON + presupuesto
    # de descargas por corrida).
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, scan_schedule13dg_watchlist),
        "cron",
        job_id="schedule13dg_watchlist_daily",
        hour=22,
        minute=50,
        jitter=300,
    )
    # Carteras de inversores (13F + Form 4): el 13F es trimestral (plazo de 45
    # dias) y los Form 4 de Trump/Bezos son poco frecuentes; semanal sobra y son
    # ~10-15 peticiones a SEC por tenant.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, sync_investor_holdings),
        "cron",
        job_id="investor_holdings_weekly",
        day_of_week="mon",
        hour=4,
        minute=20,
        jitter=600,
    )
    # Evaluacion de reglas de alerta del usuario: barata (una lectura por
    # regla + emision solo al disparar) y con cooldown por regla, asi que
    # cada 5 minutos es seguro. El estado de cada evaluacion queda en
    # AlertRule.last_result y es visible en /alerts.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, evaluate_alert_rules),
        "interval",
        job_id="alert_rule_evaluation",
        minutes=5,
        jitter=60,
    )
    # PR-4 insider alert outbox: re-evaluacion frecuente es barata porque
    # la dedupe es por fingerprint (rule_version + tx), nunca por ticker.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, dispatch_insider_alerts),
        "interval",
        job_id="insider_alert_outbox",
        minutes=20,
        jitter=180,
    )
    # Recordatorios macro T-24 h / T-1 h: idempotentes por evento y ventana.
    _register(scheduler, partial(enqueue_for_all_tenants, dispatch_macro_reminders),
              "interval", job_id="macro_event_reminders", minutes=10)
    _register(scheduler, partial(enqueue_for_all_tenants, dispatch_tracked_news_alerts),
              "interval", job_id="tracked_news_in_app", minutes=15)
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_paper_trades),
        "interval", job_id="paper_trading_quotes", minutes=30, jitter=60,
    )
    # F17: precios intradia de la cartera (Yahoo, retardo ~15 min declarado
    # en la UI) durante la sesion US. Ventana 13-21 UTC cubre EDT y EST.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_portfolio_prices_intraday),
        "cron",
        job_id="portfolio_prices_intraday",
        day_of_week="mon-fri",
        hour="13-21",
        minute="*/15",
        jitter=60,
    )
    _register(scheduler, partial(enqueue_for_all_tenants, refresh_portfolio_moves),
              "cron", job_id="portfolio_moves_daily", hour=5, minute=15)
    # Dividendos declarados de las posiciones abiertas (ex-date, pago, fuente):
    # alimentan /corporate-actions y las respuestas de Cerebro. Una vez al dia.
    _register(scheduler, partial(enqueue_for_all_tenants, sync_portfolio_dividends),
              "cron", job_id="portfolio_dividends_daily", hour=6, minute=20, jitter=300)
    # Dividendos de los tickers con paper trades vivos: el devengo del track
    # record neto se computa sobre DividendRecord. Misma fuente gratuita.
    _register(scheduler, partial(enqueue_for_all_tenants, sync_paper_dividends),
              "cron", job_id="paper_dividends_daily", hour=6, minute=50, jitter=300)
    # Propuestas LLM automaticas del paper book: UNA pasada diaria con la misma
    # cuota compartida (5/dia) y el mismo guard de modelos EUR0 del endpoint
    # manual: coste LLM nuevo = 0. Tras el refresco de noticias de la manana EU
    # y con el pre-market US ya publicado.
    _register(scheduler, partial(enqueue_for_all_tenants, propose_paper_trades),
              "cron", job_id="paper_proposals_daily", hour=15, minute=30, jitter=600)
    # Splits declarados (Yahoo, FMP de respaldo): sin ellos el modelo no puede
    # ajustar los recuentos historicos de acciones y degrada el CAGR a N/D.
    # Semanal: cartera+watchlist completo; universo en chunks auto-encolados.
    # ESEF semanal: rebuild de snapshots (filings.xbrl.org, gratis) +
    # re-ingesta de emisores reviewed. Sin esto los fundamentales IFRS se
    # quedaban congelados en el snapshot one-off del 25-sep.
    _register(scheduler, partial(enqueue_for_all_tenants, refresh_esef_fundamentals),
              "cron", job_id="esef_weekly_reingest", day_of_week="sat", hour=6, minute=30, jitter=600)
    _register(scheduler, partial(enqueue_for_all_tenants, ingest_class_shares_outstanding),
              "cron", job_id="class_shares_weekly", day_of_week="sun", hour=6, minute=10, jitter=600)
    # PR-D resto: backfill diario presupuestado de perfiles Finnhub
    # (300 companias/run; universo completo en ~1 semana sin pasar el rate
    # limit gratuito). Retoma donde lo dejo via Document finnhub_profile.
    _register(scheduler, partial(enqueue_for_all_tenants, backfill_finnhub_profiles),
              "cron", job_id="finnhub_profile_backfill_daily", hour=4, minute=50, jitter=300)
    # Backfill diario presupuestado de fundamentales SEC (100 companias/run;
    # universo US completo en dias-semanas segun su tamano real, luego
    # refresco rodante con frescura 7d). Anti-atasco: pre-filtro de identidad
    # SEC y rotacion por ultimo intento persistido.
    _register(scheduler, partial(enqueue_for_all_tenants, backfill_sec_fundamentals),
              "cron", job_id="sec_fundamentals_backfill_daily", hour=3, minute=40, jitter=300)
    _register(scheduler, partial(enqueue_for_all_tenants, ingest_corporate_splits, scope="tracked"),
              "cron", job_id="splits_tracked_weekly", day_of_week="sun", hour=5, minute=10, jitter=600)
    _register(scheduler, partial(enqueue_for_all_tenants, ingest_corporate_splits, scope="universe"),
              "cron", job_id="splits_universe_weekly", day_of_week="sun", hour=5, minute=50, jitter=600)
    # F1 ProPicks: run diario del embudo completo tras el cierre US. Sin el,
    # la Seleccion IA dependia de un POST manual y quedaba congelada semanas.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, run_propicks_funnel),
        "cron",
        job_id="propicks_funnel_daily",
        hour=21,
        minute=30,
    )
    # F2 ProPicks: precios diarios + momentum de TODAS las aprobadas del
    # ultimo run (tras el run de las 21:30). Tras el cierre de mercado US.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_propicks_prices),
        "cron",
        job_id="propicks_prices_daily",
        hour=22,
        minute=0,
    )
    # Snapshot mensual congelado del embudo (dia 1, tras los precios del cierre).
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, freeze_propicks_snapshot),
        "cron",
        job_id="propicks_snapshot_monthly",
        day=1,
        hour=22,
        minute=30,
    )
    # Radar ProPicks+DCA (universo 1.000): barrido nocturno acotado y
    # resumible. Persiste snapshots SOLO con sesiones asentadas: la sesion
    # del dia en curso nunca entra, asi que esta corrida NO usa el cierre
    # de hoy aunque se encole despues de el. El cursor por dia reanuda lo
    # que el presupuesto deje sin completar; el lease global evita solapes.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, propicks_radar_scan),
        "cron",
        job_id="propicks_radar_scan_daily",
        hour=23,
        minute=0,
    )
    # Serie diaria SPY para el "vs SPY" del track record ProPicks.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, ingest_spy_daily),
        "cron",
        job_id="spy_benchmark_daily",
        day_of_week="mon-fri",
        hour=22,
        minute=40,
    )
    # Metricas de valoracion (P/B, yield TTM) de todo el universo, tras los
    # cierres oficiales de las 22:30 UTC para usar el close del dia asentado.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_valuation_metrics),
        "cron",
        job_id="valuation_metrics_daily",
        hour=22,
        minute=50,
        jitter=300,
    )
    # PDMR UK (tracefour, 60 req/h/IP): 1 GET por corrida cada 6 h basta y sobra.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, ingest_uk_pdmr_filings),
        "interval",
        job_id="uk_pdmr_filings",
        hours=6,
    )
    # Cierres oficiales de todo el universo (base de Movers/Mercado/watchlist).
    # 22:30 UTC: tras el cierre US tanto en EDT como en EST.
    _register(
        scheduler,
        enqueue_official_closes_once,
        "cron",
        job_id="official_closes_daily",
        day_of_week="mon-fri",
        hour=22,
        minute=30,
    )
    # Automatic recovery after backlog/deploy, not a manual bulk download.
    # Actor's completed-session marker makes successful sessions a cheap skip.
    _register(scheduler, enqueue_official_closes_once, "interval",
              job_id="official_closes_recovery", hours=1)
    # Senales DCA por niveles (watchlist + cartera): tras los cierres oficiales
    # de las 22:30 UTC, para evaluar con el cierre del dia ya asentado.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, evaluate_dca_signals),
        "cron",
        job_id="dca_signals_daily",
        day_of_week="mon-fri",
        hour=23,
        minute=15,
    )
    # Fechas de resultados (cartera + watchlist): dos veces al dia, las fechas
    # cambian poco. Misma cadencia para todos los tenants.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, refresh_earnings_calendar),
        "cron",
        job_id="earnings_dates_refresh",
        hour="4,16",
        minute=20,
    )
    # Avisos de proximos resultados (7 / 1 / 0 dias antes): una vez al dia por
    # la manana, tras el refresco de fechas de las 4:20. Lee solo la BD.
    _register(
        scheduler,
        partial(enqueue_for_all_tenants, dispatch_earnings_reminders),
        "cron",
        job_id="earnings_reminders_daily",
        hour=7,
        minute=5,
        jitter=600,
    )
    # Retencion de datos personales: opt-in explicito. Encendido por defecto
    # seria un borrado silencioso en el primer deploy; el operador activa
    # RETENTION_JOB_ENABLED y decide cuando salir de RETENTION_DRY_RUN.
    if get_settings().retention_job_enabled:
        _register(
            scheduler,
            run_retention,
            "cron",
            job_id="privacy_retention",
            hour=4,
            minute=35,
            jitter=600,
        )
    return scheduler


def main() -> None:
    scheduler = build_scheduler(background=False)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
