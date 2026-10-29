from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact, Tenant
from app.models.entities import Base
from app.services.reviewed_eps_adjustments import SOURCE_TYPE, is_reviewed_eps_adjustment
from app.services.reviewed_eps_repair import PLAN, repair_reviewed_eps


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=2, external_id="eps-repair-test"))
        db.commit()
        db.info["tenant_id"] = 2
        companies = {}
        for raw_id, ticker, lei, period, value, _, _ in PLAN:
            if ticker not in companies:
                company = Company(
                    ticker=ticker,
                    name=ticker,
                    exchange="BME",
                    currency="EUR",
                    sector="S",
                    industry="I",
                    company_type="standard",
                    valuation_model="unassigned",
                    special_sources=[],
                    special_risks=[],
                    factor_tags=[],
                )
                db.add(company)
                db.flush()
                companies[ticker] = company
            company = companies[ticker]
            source = Document(
                tenant_id=2,
                company_id=company.id,
                title="raw ESEF",
                source_type="ESEF",
                metadata_={"lei": lei},
            )
            db.add(source)
            db.flush()
            db.add(
                FinancialFact(
                    id=raw_id,
                    tenant_id=2,
                    company_id=company.id,
                    metric="eps_diluted",
                    value=Decimal(value),
                    unit="EUR/share",
                    period=period,
                    fiscal_year=int(period[:4]),
                    fiscal_quarter="FY",
                    source_id=source.id,
                    source_type="ESEF",
                    is_reported=True,
                    is_adjusted=False,
                )
            )
        db.commit()
        yield db
    engine.dispose()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_dry_run_never_writes(db):
    original = (count(db, FinancialFact), count(db, Document))
    result = repair_reviewed_eps(db, tenant_id=2)
    assert result["inserted"] == 0 and result["existing"] == 0
    assert len(result["adjustments"]) == 4
    assert (count(db, FinancialFact), count(db, Document)) == original
    assert result["raw_sha256_before"] == result["raw_sha256_after"]


def test_apply_exact_four_adjusted_raw_preserved_idempotent(db):
    result = repair_reviewed_eps(db, tenant_id=2, apply=True)
    db.commit()
    assert result["inserted"] == 4 and result["existing"] == 0
    assert result["raw_sha256_before"] == result["raw_sha256_after"]
    assert count(db, FinancialFact) == 8 and count(db, Document) == 8
    rows = db.scalars(select(FinancialFact).where(FinancialFact.source_type == SOURCE_TYPE)).all()
    assert all(is_reviewed_eps_adjustment(row) for row in rows)
    assert all(row.filed is None for row in rows)
    assert {(r.period, r.value) for r in rows} == {(p, Decimal(v)) for *_, p, v in PLAN}
    again = repair_reviewed_eps(db, tenant_id=2, apply=True)
    db.commit()
    assert again["inserted"] == 0 and again["existing"] == 4
    assert count(db, FinancialFact) == 8 and count(db, Document) == 8


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", Decimal("999")),
        ("period", "2020-01-01:FY"),
        ("is_reported", False),
        ("is_adjusted", True),
        ("unit", "USD/share"),
        ("fiscal_year", 2020),
    ],
)
def test_any_changed_raw_aborts_entire_batch(db, field, value):
    row = db.get(FinancialFact, PLAN[-1][0])
    setattr(row, field, value)
    db.commit()
    with pytest.raises(ValueError, match="original fact"):
        repair_reviewed_eps(db, tenant_id=2, apply=True)
    assert count(db, FinancialFact) == 4 and count(db, Document) == 4


def test_tenant_scope_must_match_and_have_all_four(db):
    with pytest.raises(ValueError, match="session tenant"):
        repair_reviewed_eps(db, tenant_id=1, apply=True)
    db.delete(db.get(FinancialFact, PLAN[-1][0]))
    db.commit()
    with pytest.raises(ValueError, match="exactly four"):
        repair_reviewed_eps(db, tenant_id=2, apply=True)


def test_conflicting_existing_target_never_overwritten(db):
    repair_reviewed_eps(db, tenant_id=2, apply=True)
    db.commit()
    row = db.scalar(select(FinancialFact).where(FinancialFact.source_type == SOURCE_TYPE))
    row.value = Decimal("999")
    db.commit()
    with pytest.raises(ValueError, match="target conflicts"):
        repair_reviewed_eps(db, tenant_id=2, apply=True)
    assert row.value == Decimal("999")


def test_duplicate_target_aborts(db):
    repair_reviewed_eps(db, tenant_id=2, apply=True)
    db.commit()
    row = db.scalar(select(FinancialFact).where(FinancialFact.source_type == SOURCE_TYPE))
    db.add(
        FinancialFact(
            tenant_id=2,
            company_id=row.company_id,
            metric=row.metric,
            value=row.value,
            unit=row.unit,
            period=row.period,
            fiscal_year=row.fiscal_year,
            fiscal_quarter="FY",
            source_type=SOURCE_TYPE,
            source_id=row.source_id,
            is_reported=False,
            is_adjusted=True,
        )
    )
    db.commit()
    with pytest.raises(ValueError, match="duplicate adjusted"):
        repair_reviewed_eps(db, tenant_id=2, apply=True)


def test_rollback_leaves_no_documents_or_facts(db):
    repair_reviewed_eps(db, tenant_id=2, apply=True)
    db.rollback()
    assert count(db, FinancialFact) == 4 and count(db, Document) == 4
