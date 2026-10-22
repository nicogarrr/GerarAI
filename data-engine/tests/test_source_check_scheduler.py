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
    assert run["ok"] is False and run["error"] == "StoreCorruptError"
    monkeypatch.undo()
