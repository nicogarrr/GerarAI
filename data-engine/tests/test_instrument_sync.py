"""Seed desde fixture CSV minimo: conteos, NULL honestos e idempotencia."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base
from app.services.instrument_reference import get_by_ticker, upsert_rows
from scripts.sync_instruments import normalize_csv_rows, read_csv_rows

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "instruments" / "equities_sample.csv"
AS_OF = date(2026, 10, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def test_fixture_seed_counts_and_idempotence(db):
    raw = read_csv_rows(FIXTURE)
    assert len(raw) == 6  # 5 validas + 1 sin simbolo
    valid, skipped_invalid = normalize_csv_rows(raw, as_of=AS_OF, source="financedatabase")
    assert len(valid) == 5
    assert skipped_invalid == 1
    first = upsert_rows(db, valid, commit=True)
    assert first == {"inserted": 5, "updated": 0, "skipped": 0}
    second = upsert_rows(db, valid, commit=True)
    assert second == {"inserted": 0, "updated": 0, "skipped": 0}


def test_fixture_unknown_fields_are_null_not_invented(db):
    raw = read_csv_rows(FIXTURE)
    valid, _ = normalize_csv_rows(raw, as_of=AS_OF, source="financedatabase")
    upsert_rows(db, valid, commit=True)
    myst = get_by_ticker(db, "MYST")
    assert myst is not None
    # FinanceDatabase no trae estos campos para MYST -> NULL explicito.
    assert myst.sector is None
    assert myst.industry is None
    assert myst.figi is None
    assert myst.isin is None
    san = get_by_ticker(db, "SAN.MC")
    assert san is not None
    assert san.sector == "Financials"
    assert san.figi == "BBG000BSAN01"


def test_refresh_weekly_delegates_to_sync_with_defaults(monkeypatch):
    """El wrapper del scheduler llama a sync sin red en el test (delegacion medida)."""
    import scripts.sync_instruments as mod

    calls = {}

    def _fake_sync(**kwargs):
        calls.update(kwargs)
        return {"status": "ok", "dry_run": False}

    monkeypatch.setattr(mod, "sync", _fake_sync)
    out = mod.refresh_weekly()
    assert out["status"] == "ok"
    assert calls["data_dir"] == mod.DEFAULT_DATA_DIR
    assert calls["as_of"] == date.today()
    assert "enrich_openfigi" not in calls or calls.get("enrich_openfigi") in (None, False)


def test_scheduler_wrapper_calls_refresh_weekly(monkeypatch):
    """El registro del scheduler pasa por scripts.sync_instruments.refresh_weekly."""
    import scripts.sync_instruments as mod

    called = {"n": 0}

    def _fake():
        called["n"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(mod, "refresh_weekly", _fake)
    from app.workers.scheduler import _refresh_instrument_references

    assert _refresh_instrument_references()["status"] == "ok"
    assert called["n"] == 1
