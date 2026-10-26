"""Offline regressions for Core/ORM tenant reassignment and ordinary DML."""

import pytest
from sqlalchemy import bindparam, create_engine, delete, select, update
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.database import Base
from app.models import Tenant, WatchItem


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as admin:
        tenants = [Tenant(external_id=f"bulk-key-{i}", name=f"QA {i}") for i in range(2)]
        admin.add_all(tenants)
        admin.flush()
        ids = [tenant.id for tenant in tenants]
        admin.add_all([
            WatchItem(tenant_id=tid, symbol=f"SYNTH{tid}", company=f"QA {tid}")
            for tid in ids
        ])
        admin.commit()
    yield engine, ids
    engine.dispose()


def _statement(shape, target):
    table = WatchItem.__table__
    if shape == "orm":
        return update(WatchItem).values(tenant_id=target), None
    if shape == "core-string":
        return update(table).values(tenant_id=target), None
    if shape == "core-column":
        return update(table).values({table.c.tenant_id: target}), None
    if shape == "core-ordered":
        return update(table).ordered_values(("tenant_id", target)), None
    if shape == "core-params":
        return update(table), {"tenant_id": target}
    if shape == "core-mixed-params":
        return update(table).values(company="changed"), {"tenant_id": target}
    if shape == "core-many-params":
        return update(table), [{"tenant_id": target}, {"tenant_id": target}]
    if shape == "core-alias":
        return update(table.alias("qa_watch")).values(tenant_id=target), None
    raise AssertionError(shape)


@pytest.mark.parametrize("shape", [
    "orm", "core-string", "core-column", "core-ordered", "core-params",
    "core-many-params", "core-mixed-params", "core-alias",
])
@pytest.mark.parametrize("target", [None, "other"])
def test_reassignment_is_blocked_for_all_key_shapes(database, shape, target):
    engine, (tenant_a, tenant_b) = database
    value = tenant_b if target == "other" else None
    with Session(engine) as scoped:
        scoped.info["tenant_id"] = tenant_a
        statement, params = _statement(shape, value)
        with pytest.raises(RuntimeError, match="tenant_id"):
            scoped.execute(statement, params)
        scoped.rollback()
    with Session(engine) as admin:
        assert admin.scalars(select(WatchItem.tenant_id).order_by(WatchItem.id)).all() == [tenant_a, tenant_b]


@pytest.mark.parametrize("shape", ["orm", "core", "alias", "ordered", "params", "where-param"])
def test_ordinary_updates_and_deletes_remain_scoped(database, shape):
    engine, (tenant_a, tenant_b) = database
    table = WatchItem.__table__
    if shape == "alias":
        table = table.alias("qa_ordinary")
    statement = update(WatchItem if shape == "orm" else table)
    params = None
    if shape == "ordered":
        statement = statement.ordered_values(("company", "changed"))
    elif shape == "params":
        params = {"company": "changed"}
    elif shape in {"where-param"}:
        key = "tenant_id" if shape == "where-tenant-param" else "owner"
        statement = statement.where(table.c.tenant_id == bindparam(key)).values(company="changed")
        params = {key: tenant_a}
    else:
        statement = statement.values(company="changed")
    with Session(engine) as scoped:
        scoped.info["tenant_id"] = tenant_a
        scoped.execute(statement, params)
        scoped.commit()
    with Session(engine) as admin:
        rows = admin.execute(select(WatchItem.tenant_id, WatchItem.company).order_by(WatchItem.id)).all()
        assert rows == [(tenant_a, "changed"), (tenant_b, f"QA {tenant_b}")]
    with Session(engine) as scoped:
        scoped.info["tenant_id"] = tenant_a
        scoped.execute(delete(table))
        scoped.commit()
    with Session(engine) as admin:
        assert admin.scalars(select(WatchItem.tenant_id)).all() == [tenant_b]
