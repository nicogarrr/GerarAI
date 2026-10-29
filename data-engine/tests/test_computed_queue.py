"""El carril de computo rapido de cara al usuario (ProPicks diario, precios
ProPicks, SPY, snapshot mensual, refresco del paper book) va en cola dedicada
"computed" con worker propio (patron thesis/kpis/alerts/gdelt): el 29-oct el
run diario del embudo ProPicks llevaba sin correr desde 28-oct 03:38 UTC por
starvation en la cola default (>10k mensajes por delante), no por el filtro
del embudo."""

from app.workers import dramatiq_app


def test_computed_rail_actors_use_dedicated_queue():
    for actor in (
        dramatiq_app.run_propicks_funnel,
        dramatiq_app.freeze_propicks_snapshot,
        dramatiq_app.ingest_spy_daily,
        dramatiq_app.refresh_propicks_prices,
    ):
        assert actor.queue_name == dramatiq_app.COMPUTED_QUEUE_NAME == "computed"


def test_ingestion_and_heavy_actors_stay_off_computed_queue():
    # Ingesta masiva y trabajos largos/pesados: se quedan fuera del carril
    # para no recrear el starvation DENTRO de el.
    for actor in (
        dramatiq_app.refresh_rss_feeds,
        dramatiq_app.refresh_news,
        dramatiq_app.refresh_ticker_news,
        dramatiq_app.scan_insider_watchlist,
        dramatiq_app.refresh_valuation_metrics,
        dramatiq_app.evaluate_dca_signals,
        dramatiq_app.propose_paper_trades,
        # No acreditado como job corto (hasta 50 quotes + sync CA por fila):
        # en el worker-alerts de 2 hilos podia retrasar las alertas.
        dramatiq_app.refresh_paper_trades,
    ):
        assert actor.queue_name != "computed"
