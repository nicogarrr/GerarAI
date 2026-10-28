"""Planificador DRY-RUN de splits duplicados: invariantes, tenant y solo lectura."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, CorporateAction, Tenant
from app.services.split_reconciliation import plan_split_reconciliation


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker):
    c = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD", sector="Tech",
        industry="Tech", company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


def _tenant(db, ext):
    t = Tenant(external_id=ext, name=ext, metadata_={})
    db.add(t)
    db.commit()
    return t


def _split(db, company, day, ratio, *, tenant=None, applied=False, source="yahoo_finance",
           fetched=True, action_type="split"):
    row = CorporateAction(
        company_id=company.id, action_type=action_type, effective_date=day,
        ratio=Decimal(ratio), applied=applied, source=source,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC) if fetched else None,
        tenant_id=tenant.id if tenant else None,
    )
    db.add(row)
    db.commit()
    return row


def _plan(db, **kw):
    return plan_split_reconciliation(db, all_tenants=True, **kw)


def test_exact_duplicate_proposes_removing_the_extra_unapplied_row(db):
    c = _company(db, "AAPL")
    a = _split(db, c, date(2020, 8, 31), "4")
    b = _split(db, c, date(2020, 8, 31), "4")
    plan = _plan(db)
    assert len(plan.duplicate_groups) == 1
    g = plan.duplicate_groups[0]
    assert g.kind == "exact_duplicate" and g.status == "proposed"
    assert g.keep.id == a.id and [r.id for r in g.remove] == [b.id]


def test_provider_date_skew_within_three_days_is_a_duplicate(db):
    c = _company(db, "NVDA")
    _split(db, c, date(2024, 6, 10), "10")
    _split(db, c, date(2024, 6, 13), "10", source="fmp")
    g = _plan(db).duplicate_groups[0]
    assert g.kind == "provider_date_skew"


def test_same_ratio_far_apart_is_a_legitimate_second_event(db):
    c = _company(db, "XYZ")
    _split(db, c, date(2015, 3, 1), "2")
    _split(db, c, date(2019, 3, 1), "2")
    plan = _plan(db)
    assert plan.duplicate_groups == [] and plan.proposed_removals == []


def test_four_days_apart_is_not_a_duplicate(db):
    c = _company(db, "XYZ")
    _split(db, c, date(2024, 1, 1), "2")
    _split(db, c, date(2024, 1, 5), "2")
    assert _plan(db).duplicate_groups == []


def test_window_is_anchored_not_chained(db):
    c = _company(db, "XYZ")
    for d in (1, 4, 7):
        _split(db, c, date(2024, 1, d), "2")
    groups = _plan(db).duplicate_groups
    # 1 y 4 forman grupo (<=3 dias); el 7 queda solo (3 dias desde el 4, 6 desde el 1).
    assert len(groups) == 1 and len(groups[0].members) == 2


def test_same_day_different_ratio_is_reported_but_never_removed(db):
    c = _company(db, "ABC")
    _split(db, c, date(2022, 5, 5), "2")
    _split(db, c, date(2022, 5, 5), "0.5", action_type="reverse_split")
    plan = _plan(db)
    assert plan.duplicate_groups == [] and plan.proposed_removals == []
    assert plan.same_day_different_ratio[0]["ratios"] == ["0.5", "2"]


def test_applied_row_is_never_proposed_for_removal_and_wins_as_keeper(db):
    c = _company(db, "AAPL")
    _split(db, c, date(2020, 8, 31), "4")
    applied = _split(db, c, date(2020, 8, 31), "4", applied=True)
    g = _plan(db).duplicate_groups[0]
    assert g.keep.id == applied.id
    assert applied.id not in [r.id for r in g.remove]


def test_two_applied_rows_flag_double_applied_and_propose_nothing(db):
    c = _company(db, "AAPL")
    _split(db, c, date(2020, 8, 31), "4", applied=True)
    _split(db, c, date(2020, 8, 31), "4", applied=True)
    _split(db, c, date(2020, 8, 31), "4")
    plan = _plan(db)
    g = plan.duplicate_groups[0]
    assert g.status == "double_applied" and g.keep is None and g.remove == []
    assert plan.proposed_removals == []
    assert plan.as_dict()["double_applied_group_count"] == 1


def test_provider_row_with_fetched_at_is_preferred_over_bare_manual_row(db):
    c = _company(db, "AAPL")
    _split(db, c, date(2020, 8, 31), "4", source="manual", fetched=False)
    provider = _split(db, c, date(2020, 8, 31), "4")
    assert _plan(db).duplicate_groups[0].keep.id == provider.id


def test_other_company_or_other_action_type_never_groups(db):
    a, b = _company(db, "AAA"), _company(db, "BBB")
    _split(db, a, date(2020, 1, 1), "2")
    _split(db, b, date(2020, 1, 1), "2")
    db.add(CorporateAction(company_id=a.id, action_type="merger", effective_date=date(2020, 1, 1),
                           ratio=Decimal("2"), source="manual"))
    db.commit()
    assert _plan(db).duplicate_groups == []


def test_tenants_never_mix_and_scoped_plan_only_sees_its_tenant(db):
    t1, t2 = _tenant(db, "t1"), _tenant(db, "t2")
    c = _company(db, "AAPL")
    _split(db, c, date(2020, 8, 31), "4", tenant=t1)
    _split(db, c, date(2020, 8, 31), "4", tenant=t2)
    assert _plan(db).duplicate_groups == []  # una fila por tenant: no es duplicado
    _split(db, c, date(2020, 8, 31), "4", tenant=t2)
    scoped1 = plan_split_reconciliation(db, tenant_id=t1.id)
    scoped2 = plan_split_reconciliation(db, tenant_id=t2.id)
    assert scoped1.duplicate_groups == [] and scoped1.rows_examined == 1
    assert len(scoped2.duplicate_groups) == 1 and scoped2.rows_examined == 2
    assert scoped2.duplicate_groups[0].tenant_id == t2.id


def test_fails_closed_without_tenant_context_when_auth_required(db, monkeypatch):
    from app.core import tenancy

    class S:
        research_auth_required = True
        is_production = False

    monkeypatch.setattr(tenancy, "get_settings", lambda: S())
    with pytest.raises(RuntimeError):
        plan_split_reconciliation(db)


def test_epoch_dated_splits_are_flagged(db):
    c = _company(db, "AAPL")
    _split(db, c, date(1970, 1, 1), "2")
    plan = _plan(db)
    assert [r.effective_date for r in plan.epoch_suspects] == [date(1970, 1, 1)]


def test_plan_is_idempotent_and_writes_nothing(db):
    c = _company(db, "AAPL")
    for _ in range(3):
        _split(db, c, date(2020, 8, 31), "4")
    before = db.execute(select(func.count(CorporateAction.id))).scalar_one()
    statements: list[str] = []

    def spy(conn, cursor, statement, *a):  # noqa: ARG001
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(db.get_bind(), "before_cursor_execute", spy)
    try:
        first = _plan(db).as_dict()
        second = _plan(db).as_dict()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", spy)
    assert first == second and first["fingerprint"] == second["fingerprint"]
    assert not {s for s in statements if s in {"INSERT", "UPDATE", "DELETE"}}
    assert db.execute(select(func.count(CorporateAction.id))).scalar_one() == before
    assert not db.new and not db.dirty and not db.deleted


def test_after_removing_proposed_rows_a_new_plan_is_empty(db):
    c = _company(db, "AAPL")
    for _ in range(3):
        _split(db, c, date(2020, 8, 31), "4")
    plan = _plan(db)
    for rid in plan.proposed_removals:  # simula el saneamiento SOLO en la BD de prueba
        db.delete(db.get(CorporateAction, rid))
    db.commit()
    again = _plan(db)
    assert again.duplicate_groups == [] and again.proposed_removals == []


def test_six_groups_mix_reproduces_counts_and_separates_legit_events(db):
    """Fixture sintético con 6 grupos duplicados + eventos legítimos que no cuentan."""
    tickers = [_company(db, f"T{i}") for i in range(6)]
    for i, c in enumerate(tickers):
        _split(db, c, date(2021, 1, 10), "2")
        _split(db, c, date(2021, 1, 10 + (i % 4)), "2", source="fmp")  # skew 0..3 dias
    legit = _company(db, "LEGIT")
    _split(db, legit, date(2010, 1, 1), "2")
    _split(db, legit, date(2018, 1, 1), "2")
    plan = _plan(db)
    assert len(plan.duplicate_groups) == 6
    assert len(plan.proposed_removals) == 6
    assert all(g.company_id != legit.id for g in plan.duplicate_groups)


def _load_cli():
    path = Path(__file__).resolve().parent.parent / "scripts" / "plan_split_reconciliation.py"
    spec = importlib.util.spec_from_file_location("plan_split_reconciliation_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_run_needs_an_explicit_scope_and_rolls_back(db):
    cli = _load_cli()
    c = _company(db, "AAPL")
    _split(db, c, date(2020, 8, 31), "4")
    _split(db, c, date(2020, 8, 31), "4")
    with pytest.raises(SystemExit):
        cli.run(db, tenant_external_id=None, all_tenants=False)
    out = cli.run(db, tenant_external_id=None, all_tenants=True)
    assert out["dry_run"] is True and out["duplicate_group_count"] == 1
    assert db.execute(select(func.count(CorporateAction.id))).scalar_one() == 2
    t = _tenant(db, "ext-1")
    with pytest.raises(SystemExit):
        cli.run(db, tenant_external_id="no-existe", all_tenants=False)
    assert cli.run(db, tenant_external_id=t.external_id, all_tenants=False)["rows_examined"] == 0
