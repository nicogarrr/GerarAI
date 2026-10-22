"""Job de candidatos desde el registro. Texto SINTETICO; fetch simulado (sin red)."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, ManagementPromise, Position, WatchItem
from app.models.entities import CommitmentExtractionAttempt as Attempt
from app.services import commitment_candidate_job as job
from app.services.transcript_source_registry import get_entry

SYN = "Jane Roe \nChief Executive Officer, Acme Corp. \nWe're on track to be live in 15 sites by year-end. \n"
NOQ = "Intro text without any recognised management speaker header.\n"
TODAY = date(2026, 10, 22)


def _co(t):
    return Company(ticker=t, name=t, exchange="NYSE", currency="USD", sector="S", industry="I",
                   company_type="holding", valuation_model="unassigned",
                   special_sources=[], special_risks=[], factor_tags=[])


def _db(tickers=("UBER",), watch=("NOSUCH",)):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    db = Session(eng)
    db.info["tenant_id"] = None
    for t in tickers:
        c = _co(t)
        db.add(c)
        db.commit()
        db.add(Position(company_id=c.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)))
    for w in watch:
        db.add(WatchItem(symbol=w))
    db.commit()
    return db


def _fetch(calls, text=SYN, sha="t1"):
    def f(ticker, url, today):
        calls.append((ticker, url))
        a = next(x for x in get_entry(ticker).assets if x.url == url)
        return SimpleNamespace(text=text, url=url, bytes_sha256="b" * 64, text_sha256=sha.ljust(64, "0"),
                               asset=SimpleNamespace(published_on=date.fromisoformat(a.call_date))), {}
    return f


def test_creates_unreviewed_candidates_and_registers_attempt_with_hash_and_explicit_per_company():
    db = _db()
    calls: list = []
    r = job.extract_registry_candidates(db, today=TODAY, fetch=_fetch(calls))
    assert r["NOSUCH"][0]["outcome"] == "sin_transcripcion_registrada"
    assert r["UBER"][0]["outcome"] == "candidatos_creados"
    rows = list(db.scalars(select(ManagementPromise)))
    assert rows and all(x.status == "candidate" and x.fulfillment_criteria is None for x in rows)
    a = db.scalar(select(Attempt))
    assert a.status == "done" and a.text_sha256.startswith("t1") and a.last_attempt_on == TODAY
    assert a.next_attempt_on == TODAY + timedelta(days=7) and a.candidates_created == len(rows)


def test_zero_candidates_and_unchanged_hash_are_not_redownloaded_daily_then_refreshed_by_hash():
    db = _db()
    calls: list = []
    job.extract_registry_candidates(db, today=TODAY, fetch=_fetch(calls, text=NOQ))
    a = db.scalar(select(Attempt))
    assert a.outcome == "formato_sin_hablantes_reconocidos" and a.management_turns == 0
    assert a.next_attempt_on == TODAY + timedelta(days=30)
    n = len(calls)
    r = job.extract_registry_candidates(db, today=TODAY + timedelta(days=1), fetch=_fetch(calls, text=NOQ))
    assert r["UBER"][0]["outcome"] == "no_toca_aun" and len(calls) == n
    db2 = _db()
    c2: list = []
    job.extract_registry_candidates(db2, today=TODAY, fetch=_fetch(c2))
    job.extract_registry_candidates(db2, today=TODAY + timedelta(days=8), fetch=_fetch(c2))
    assert db2.scalar(select(Attempt)).outcome == "sin_cambios_hash"
    assert len(list(db2.scalars(select(ManagementPromise)))) >= 1


def test_unexpected_error_is_isolated_persisted_and_batch_continues_with_backoff():
    db = _db(tickers=("UBER", "BN"))
    calls: list = []
    ok = _fetch(calls)

    def f(ticker, url, today):
        if ticker == "BN":
            raise RuntimeError("boom")
        return ok(ticker, url, today)

    r = job.extract_registry_candidates(db, today=TODAY, fetch=f)
    assert r["BN"][0]["outcome"] == "error_inesperado:RuntimeError"
    assert r["UBER"][0]["outcome"] == "candidatos_creados"  # el lote siguio y lo previo se conserva
    bn = db.scalar(select(Attempt).join(Company, Company.id == Attempt.company_id).where(Company.ticker == "BN"))
    assert bn.status == "failed" and bn.consecutive_failures == 1 and bn.next_attempt_on == TODAY + timedelta(days=2)
    assert db.scalar(select(ManagementPromise).limit(1)) is not None


def test_fairness_never_attempted_first_and_failures_do_not_starve_rest():
    tickers = ("UBER", "BN", "KKR", "CB")
    db = _db(tickers=tickers, watch=())
    seen: list[str] = []
    ok = _fetch([])

    def f(ticker, url, today):
        seen.append(ticker)
        return ok(ticker, url, today)

    r1 = job.extract_registry_candidates(db, today=TODAY, fetch=f, max_new_assets=2)
    first = list(seen)
    assert len(first) == 2
    pend = [t for t in tickers if any(i["outcome"] == "pendiente_por_limite_de_ejecucion" for i in r1[t])]
    assert len(pend) == 2
    seen.clear()
    job.extract_registry_candidates(db, today=TODAY, fetch=f, max_new_assets=2)
    assert set(seen) == set(pend)  # lo no intentado va antes que lo ya hecho


def test_claim_is_exclusive_and_stale_claim_is_recoverable():
    db = _db()
    co = db.scalar(select(Company))
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    a = job.claim(db, co.id, "https://u/x", None, now)
    assert a is not None
    assert job.claim(db, co.id, "https://u/x", None, now + timedelta(minutes=5)) is None  # en curso
    assert job.claim(db, co.id, "https://u/x", None, now + timedelta(minutes=45)) is not None  # caducado


def test_scheduler_registration_flag_off_by_default_and_on():
    import pytest

    from app.workers.scheduler import build_scheduler

    assert get_settings().candidate_extraction_job_enabled is False
    assert build_scheduler().get_job("commitment_candidates") is None
    mp = pytest.MonkeyPatch()
    mp.setattr(get_settings(), "candidate_extraction_job_enabled", True)
    try:
        assert build_scheduler().get_job("commitment_candidates") is not None
    finally:
        mp.undo()
