"""Taxonomia de colas Dramatiq por tipo de trabajo.

Cuatro clases (orden de Nico, 31 oct 2026):

- ``interactiva``: el usuario espera el resultado (subir documento, DCA
  manual, sync IBKR dedicada, generar tesis). Fallo rapido y visible antes
  que reintentos largos.
- ``ingesta``: traer datos de fuentes externas (SEC, Yahoo, GDELT, RSS,
  IBKR). Idempotentes por diseño (el scheduler los reencola): reintentan
  con backoff y, agotados, el mensaje cae a la dead-letter (XQ) del broker
  Redis, no se pierde en silencio. Politica: 3 intentos totales
  (``max_retries=2``) con ``min_backoff`` declarado -> DL tras 3 fallos.
- ``calculo``: trabajo pesado sobre datos ya ingeridos (KPIs, propicks,
  tesis, DCA). Mismo esquema de reintento transitorio via
  ``_handle_actor_error``.
- ``mantenimiento``: alertas, recordatorios, watchdogs y reconciliaciones.

La clasificacion es LOGICA: no reencola actores ni crea colas nuevas. Las
colas fisicas y los workers del compose existentes se mantienen tal cual;
la tabla de docs/workers-colas.md mapea clase -> colas ya desplegadas.

La dead-letter la hace el broker: ``RedisBroker`` mueve a
``<namespace>:<cola>.XQ`` (zset por instante de dead-letter, con el payload
en ``.XQ.msgs``) todo mensaje que agota sus reintentos y lo conserva
``dead_message_ttl`` (7 dias por defecto). Ojo: ``<cola>.DQ`` NO es la
dead-letter, es la cola DELAYED (reintentos con backoff y envios con
delay). Inspeccion de la DL: ``ZCARD <namespace>:<cola>.XQ``.

Los limites de tiempo protegen importaciones aceptadas: un Flex de IBKR o
una ingesta de knowledge NO pueden morir por el default implicito de 10 min
(``MIN_IMPORT_TIME_LIMIT_MS``). Ningun actor usa ``max_age``: un mensaje
encolado no expira esperando worker.
"""

from __future__ import annotations

INTERACTIVA = "interactiva"
INGESTA = "ingesta"
CALCULO = "calculo"
MANTENIMIENTO = "mantenimiento"

# 3 intentos totales (1 inicial + 2 reintentos) -> dead-letter tras 3 fallos.
INGESTA_MAX_RETRIES = 2

# Suelo de time_limit para importaciones aceptadas (IBKR, knowledge, cierres
# oficiales): el default implicito de Dramatiq (10 min) las mataba a mitad.
MIN_IMPORT_TIME_LIMIT_MS = 1_800_000
GLOBAL_IMPORT_TIME_LIMIT_MS = 3_600_000

ACTOR_CLASS: dict[str, str] = {
    # interactiva: el usuario espera el resultado
    "evaluate_manual_dca": INTERACTIVA,
    "generate_thesis_job": INTERACTIVA,
    "ingest_knowledge_source": INTERACTIVA,
    "process_document": INTERACTIVA,
    "process_document_structured": INTERACTIVA,
    "extract_knowledge_principles": INTERACTIVA,
    "sync_tenant_ibkr_connections_dedicated": INTERACTIVA,
    "sync_one_tenant_ibkr_dedicated": INTERACTIVA,
    # ingesta: fuentes externas, idempotente, DL tras 3 fallos
    "backfill_company_price_history": INGESTA,
    "backfill_document_kpis": INGESTA,
    "backfill_finnhub_profiles": INGESTA,
    "backfill_sec_fundamentals": INGESTA,
    "discover_bottlenecks": INGESTA,
    "ingest_ca_insider_yahoo": INGESTA,
    "ingest_class_shares_outstanding": INGESTA,
    "ingest_corporate_splits": INGESTA,
    "ingest_letters_corpus": INGESTA,
    "ingest_sec_bottleneck_filings": INGESTA,
    "ingest_spy_daily": INGESTA,
    "ingest_uk_pdmr_filings": INGESTA,
    "refresh_asts_catalog": INGESTA,
    "refresh_bottlenecks": INGESTA,
    "refresh_earnings_calendar": INGESTA,
    "refresh_esef_fundamentals": INGESTA,
    "refresh_ir_pages": INGESTA,
    "refresh_macro_context": INGESTA,
    "refresh_macro_news": INGESTA,
    "refresh_market_pipeline": INGESTA,
    "refresh_news": INGESTA,
    "refresh_portfolio_prices_intraday": INGESTA,
    "refresh_rss_feeds": INGESTA,
    "refresh_sec_filings": INGESTA,
    "refresh_ticker_news": INGESTA,
    "scan_insider_watchlist": INGESTA,
    "scan_schedule13dg_watchlist": INGESTA,
    "seed_company_fundamentals": INGESTA,
    "sync_ibkr_flex": INGESTA,
    "sync_investor_holdings": INGESTA,
    "sync_official_closes": INGESTA,
    "sync_one_tenant_ibkr": INGESTA,
    "sync_paper_dividends": INGESTA,
    "sync_portfolio_dividends": INGESTA,
    "sync_tenant_ibkr_connections": INGESTA,
    # calculo: pesado sobre datos ya ingeridos
    "consolidate_memory": CALCULO,
    "evaluate_dca_signals": CALCULO,
    "evaluate_dca_on_add": CALCULO,  # DCA al añadir a watchlist/cartera (cola dca-manual)
    "extract_document_kpis": CALCULO,
    "freeze_propicks_snapshot": CALCULO,
    "propicks_radar_scan": CALCULO,
    "propose_paper_trades": CALCULO,
    "recompute_fundamental_metrics": CALCULO,
    "refresh_paper_trades": CALCULO,
    "refresh_portfolio_moves": CALCULO,
    "refresh_propicks_prices": CALCULO,
    "refresh_valuation_metrics": CALCULO,
    "review_theses": CALCULO,
    "run_daily_research": CALCULO,
    "run_propicks_funnel": CALCULO,
    "scan_contradictions": CALCULO,
    # mantenimiento: alertas, recordatorios, watchdogs
    "analyze_tracked_news_alert": MANTENIMIENTO,
    "dispatch_earnings_reminders": MANTENIMIENTO,
    "dispatch_insider_alerts": MANTENIMIENTO,
    "dispatch_macro_reminders": MANTENIMIENTO,
    "dispatch_source_health_watchdog": MANTENIMIENTO,
    "dispatch_queue_watchdog": MANTENIMIENTO,
    "dispatch_tracked_news_alerts": MANTENIMIENTO,
    "evaluate_alert_rules": MANTENIMIENTO,
    "reconcile_alert_analyses": MANTENIMIENTO,
    "reconcile_alert_deliveries": MANTENIMIENTO,
}

# Importaciones aceptadas: no pueden morir por un time_limit implicito.
IMPORT_ACTORS: dict[str, int] = {
    "sync_ibkr_flex": GLOBAL_IMPORT_TIME_LIMIT_MS,
    "sync_one_tenant_ibkr": MIN_IMPORT_TIME_LIMIT_MS,
    "sync_one_tenant_ibkr_dedicated": MIN_IMPORT_TIME_LIMIT_MS,
    "ingest_knowledge_source": GLOBAL_IMPORT_TIME_LIMIT_MS,
    "sync_official_closes": GLOBAL_IMPORT_TIME_LIMIT_MS,
}
