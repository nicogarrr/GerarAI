"""Interactive DCA has a real consumer isolated from ingestion backpressure."""
from app.workers import dramatiq_app


def test_manual_actor_has_isolated_queue_and_no_retry():
    actor = dramatiq_app.evaluate_manual_dca
    assert actor.queue_name == "dca-manual"
    assert actor.options["max_retries"] == 0
    assert actor.options["time_limit"] == 1_800_000
    assert dramatiq_app.evaluate_dca_signals.queue_name != actor.queue_name
    assert dramatiq_app.refresh_rss_feeds.queue_name != actor.queue_name


def test_manual_queue_has_a_dedicated_single_consumer_and_bounded_resources():
    # Reuse the repository loader: Compose tags must retain their meaning.
    from tests.test_prod_compose import _load_compose, _service_env
    services = _load_compose()["services"]
    worker = services["worker-dca-manual"]
    assert worker["command"] == ["dramatiq", "app.workers.dramatiq_app", "--processes", "1", "--threads", "1", "-Q", "dca-manual"]
    assert worker["deploy"]["resources"]["limits"]["memory"] == "384M"
    assert services["worker-official-closes"]["deploy"]["resources"]["limits"]["memory"] == "384M"
    assert worker["depends_on"]["backend"]["condition"] == "service_healthy"
    assert worker["healthcheck"]["test"]
    assert _service_env(_load_compose(), "worker-dca-manual")["RESEARCH_AUTH_REQUIRED"] == "true"
    assert "dca-manual" not in services["worker"]["command"]
