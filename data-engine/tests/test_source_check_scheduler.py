from app.core.config import get_settings


def test_job_not_registered_by_default():
    from app.workers.scheduler import build_scheduler

    assert get_settings().source_check_job_enabled is False
    assert build_scheduler().get_job("source_check_job") is None


def test_job_registered_only_when_flag_on(monkeypatch):
    from app.workers.scheduler import build_scheduler

    monkeypatch.setattr(get_settings(), "source_check_job_enabled", True)
    job = build_scheduler().get_job("source_check_job")
    assert job is not None and job.max_instances == 1


def test_run_source_check_job_uses_store_and_reports(monkeypatch, tmp_path):
    from app.services import commitment_source_check_job as mod
    from app.workers import scheduler as sch

    monkeypatch.setattr(get_settings(), "source_check_store_dir", tmp_path / "s")
    monkeypatch.setattr(mod, "check_financial_assets", lambda **k: [])
    monkeypatch.setattr(mod, "check_transcripts", lambda **k: [])
    out = sch.run_source_check_job()
    assert out == {"checked": 0, "outcomes": {}, "store_quarantined": None}


def test_failed_scheduled_run_is_persisted_and_exposed(monkeypatch, tmp_path):
    import pytest

    from app.services import commitment_source_check_job as mod
    from app.workers import scheduler as sch

    monkeypatch.setattr(get_settings(), "source_check_store_dir", tmp_path / "s")

    def boom(*a, **k):
        raise mod.StoreCorruptError("x")

    monkeypatch.setattr(mod, "run_job", boom)
    with pytest.raises(mod.StoreCorruptError):
        sch.run_source_check_job()
    run = mod.read_job_run(mod.JsonSourceCheckStore(tmp_path / "s"))
    assert run["finished"] is False and run["error"] == "StoreCorruptError"
    monkeypatch.undo()


def test_e2e_dev_scheduler_to_store_to_api(monkeypatch, tmp_path):
    """Ciclo DEV sin red: run_source_check_job -> store en disco -> funcion de la ruta GET.
    Fixtures SINTETICAS (registros falsos con URL .invalid); no prueba HTTP/auth reales."""
    from decimal import Decimal

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.routes.portfolio import source_coverage
    from app.models.entities import Base, Company, Position
    from app.services import commitment_source_check_job as mod
    from app.workers import scheduler as sch

    monkeypatch.setattr(get_settings(), "source_check_store_dir", tmp_path / "s")
    fake = [mod.SourceCheckRecord(ticker="UBER", url="https://x.invalid/u", kind="transcript",
                                  period="Q2 2026", checked_on="2026-10-22", outcome="error",
                                  reason="TimeoutError")]
    monkeypatch.setattr(mod, "check_financial_assets", lambda **k: fake)
    monkeypatch.setattr(mod, "check_transcripts", lambda **k: [])
    out = sch.run_source_check_job()
    assert out["outcomes"] == {"error": 1}
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t"
        c = Company(ticker="UBER", name="U", exchange="NYSE", currency="USD", sector="S",
                    industry="I", company_type="holding", valuation_model="unassigned",
                    special_sources=[], special_risks=[], factor_tags=[])
        db.add(c)
        db.commit()
        db.add(Position(company_id=c.id, quantity=Decimal("1"), as_of=__import__("datetime").date(2030, 1, 1)))
        db.commit()
        rep = source_coverage(db)
    row = rep["companies"][0]
    assert row["ticker"] == "UBER" and row["state"] == "ultimo_chequeo_con_error"
    assert rep["job_last_run"]["finished"] is True and rep["job_last_run"]["had_errors"] is True
    assert rep["store"]["latest"] == "ok"


def test_real_apscheduler_executes_job_function_and_persists_state(monkeypatch, tmp_path):
    """APScheduler REAL (BackgroundScheduler, disparo inmediato) -> run_source_check_job -> store.
    Sin red: los chequeos estan sustituidos por fixtures sinteticos. No es el cron 07:35 real."""
    import time
    from datetime import UTC, datetime, timedelta

    from apscheduler.schedulers.background import BackgroundScheduler

    from app.services import commitment_source_check_job as mod
    from app.workers import scheduler as sch

    monkeypatch.setattr(get_settings(), "source_check_store_dir", tmp_path / "s")
    monkeypatch.setattr(mod, "check_financial_assets", lambda **k: [])
    monkeypatch.setattr(mod, "check_transcripts", lambda **k: [])
    s = BackgroundScheduler(timezone="UTC")
    s.add_job(sch.run_source_check_job, "date", run_date=datetime.now(UTC) + timedelta(seconds=1),
              id="e2e", max_instances=1)
    s.start()
    try:
        store = mod.JsonSourceCheckStore(tmp_path / "s")
        for _ in range(60):
            if mod.read_job_run(store):
                break
            time.sleep(0.2)
    finally:
        s.shutdown(wait=True)
    run = mod.read_job_run(store)
    assert run and run["finished"] is True and run["had_errors"] is False
