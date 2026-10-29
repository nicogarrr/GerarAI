"""El carril de alertas va en cola dedicada "alerts" (aislamiento de cola
con proceso propio, patron thesis/kpis)."""

from app.workers import dramatiq_app


def test_alert_rail_actors_use_dedicated_queue():
    for actor in (
        dramatiq_app.evaluate_alert_rules,
        dramatiq_app.dispatch_tracked_news_alerts,
        dramatiq_app.analyze_tracked_news_alert,
        dramatiq_app.reconcile_alert_analyses,
        dramatiq_app.dispatch_insider_alerts,
        dramatiq_app.dispatch_macro_reminders,
        dramatiq_app.reconcile_alert_deliveries,
    ):
        assert actor.queue_name == dramatiq_app.ALERT_QUEUE_NAME == "alerts"


def test_ingestion_actors_stay_off_alert_queue():
    # Escaneo/ingesta comparten default: solo el carril de alertas se aisla.
    assert dramatiq_app.scan_insider_watchlist.queue_name != "alerts"
    assert dramatiq_app.refresh_news.queue_name != "alerts"
