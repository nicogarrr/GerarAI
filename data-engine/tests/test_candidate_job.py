"""Job de candidatos desde el registro. Texto SINTETICO; fetch simulado (sin red)."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, ManagementPromise, Position, WatchItem
from app.services.commitment_candidate_job import extract_registry_candidates
from app.services.transcript_source_registry import get_entry

SYN = ("Jane Roe \nChief Executive Officer, Acme Corp. \nWe're on track to be live in 15 sites by year-end. \n")


def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    db = Session(eng)
    db.info["tenant_id"] = None
    uber = Company(ticker="UBER", name="Uber", exchange="NYSE", currency="USD", sector="S", industry="I",
                   company_type="holding", valuation_model="unassigned",
                   special_sources=[], special_risks=[], factor_tags=[])
    db.add(uber)
    db.commit()
    db.add(Position(company_id=uber.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)))
    db.add(WatchItem(symbol="NOSUCH"))
    db.commit()
    return db


def _fetch(calls):
    def f(ticker, url, today):
        calls.append(url)
        a = next(x for x in get_entry(ticker).assets if x.url == url)
        return SimpleNamespace(text=SYN, url=url,
                               asset=SimpleNamespace(published_on=date.fromisoformat(a.call_date))), {}
    return f


def test_job_creates_unreviewed_candidates_is_idempotent_and_explicit_per_company():
    db = _db()
    calls: list[str] = []
    r1 = extract_registry_candidates(db, today=date(2026, 10, 22), fetch=_fetch(calls))
    assert r1["NOSUCH"][0]["outcome"] == "sin_transcripcion_registrada"
    uber = r1["UBER"]
    assert uber[0]["outcome"] == "candidatos_creados" and uber[0]["created"] >= 1
    rows = list(db.scalars(select(ManagementPromise)))
    assert rows and all(r.status == "candidate" and r.fulfillment_criteria is None for r in rows)
    n = len(rows)
    r2 = extract_registry_candidates(db, today=date(2026, 10, 22), fetch=_fetch(calls))
    assert r2["UBER"][0]["outcome"] == "ya_extraido" and len(calls) == len(get_entry("UBER").assets)
    assert db.scalar(select(ManagementPromise.id).limit(1)) and len(list(db.scalars(select(ManagementPromise)))) == n


def test_job_budget_and_source_error_are_visible():
    db = _db()

    def boom(ticker, url, today):
        raise ValueError("fuente rechazada")

    r = extract_registry_candidates(db, today=date(2026, 10, 22), fetch=boom)
    assert r["UBER"][0]["outcome"] == "fallo_fuente_o_limite"
    r0 = extract_registry_candidates(db, today=date(2026, 10, 22), fetch=boom, max_new_assets=0)
    assert r0["UBER"][0]["outcome"] == "pendiente_por_limite_de_ejecucion"


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
