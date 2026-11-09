"""Publication adapter reads real current inventory and degrades honestly."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Tenant
from app.models.entities import Base
from app.services import value_driver_publication_service as gate
from app.services.value_driver_service import ValueDriverItem, ValueDriverService


@pytest.fixture
def inventory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Tenant(id=7, external_id="gate-test"))
            company = Company(
                ticker="GATE",
                name="Gate Test",
                exchange="X",
                currency="USD",
                company_type="holding",
                valuation_model="unassigned",
            )
            db.add(company)
            db.commit()
            db.info["tenant_id"] = 7
            yield db, company
    finally:
        engine.dispose()


def _item(key, **changes):
    fields = dict(
        driver_key=key,
        category="contrato",
        name=key,
        status="firmado",
        source_type="filing",
        evidence="oficial",
        source_url="https://issuer.example/report",
        source_quote="A signed agreement.",
        as_of=date(2026, 1, 1),
        headline=True,
        economics={"amount_usd": 500_000_000},
    )
    fields.update(changes)
    return ValueDriverItem(**fields)


def test_blocked_inventory_payload_uses_current_rows_then_becomes_publishable(inventory):
    db, company = inventory
    service = ValueDriverService()
    service.upsert(db, company=company, tenant_id=7, item=_item("z_signed"))
    service.upsert(
        db,
        company=company,
        tenant_id=7,
        item=_item(
            "a_modelled",
            treatment="en_modelo",
            model_link="revenue.contract",
            value_per_share_marginal=Decimal("1.25"),
        ),
    )
    db.commit()
    blocked = gate.value_driver_gate(db, company)
    assert blocked["status"] == "blocked" and blocked["publishable"] is False
    assert blocked["blocker"] == "impulsor_material_sin_tratar"
    assert [row["driver_key"] for row in blocked["drivers"]] == ["a_modelled", "z_signed"]
    assert [row["driver_key"] for row in blocked["blocking"]] == ["z_signed"]
    modelled, untreated = blocked["drivers"]
    assert modelled["value_per_share_marginal"] == 1.25 and modelled["model_link"] == "revenue.contract"
    assert untreated["value_per_share_marginal"] is None and untreated["headline"] is True
    assert untreated["as_of"] == "2026-01-01" and untreated["source_quote"] == "A signed agreement."
    service.retire(db, company_id=company.id, tenant_id=7, driver_key="z_signed")
    db.commit()
    allowed = gate.value_driver_gate(db, company)
    assert allowed["status"] == "ok" and allowed["publishable"] is True
    assert allowed["blocker"] is None and allowed["blocking"] == []
    assert [row["driver_key"] for row in allowed["drivers"]] == ["a_modelled"]


@pytest.mark.parametrize("tenant", [None, 0, -1, True, "7"])
def test_invalid_tenant_never_reads_inventory(inventory, monkeypatch, tenant):
    db, company = inventory
    db.info["tenant_id"] = tenant

    def forbidden(*args, **kwargs):
        pytest.fail("invalid tenant must not read inventory")

    monkeypatch.setattr(ValueDriverService, "current", forbidden)
    assert gate.value_driver_gate(db, company) == {
        "status": "no_tenant",
        "publishable": True,
        "drivers": [],
        "blocking": [],
    }


def test_unpersisted_company_does_not_read_inventory(inventory, monkeypatch):
    db, _ = inventory
    monkeypatch.setattr(
        ValueDriverService, "current", lambda *args, **kwargs: pytest.fail("company has no id")
    )
    assert gate.value_driver_gate(db, Company(ticker="NEW"))["status"] == "no_tenant"


@pytest.mark.parametrize("method", ["current", "check_publication"])
def test_inventory_failure_is_explicit_without_leaking_exception_detail(inventory, monkeypatch, method):
    db, company = inventory

    def fail(*args, **kwargs):
        raise TimeoutError("private upstream detail")

    monkeypatch.setattr(ValueDriverService, method, fail)
    result = gate.value_driver_gate(db, company)
    assert result == {
        "status": "error",
        "publishable": False,
        "blocker": "inventario_impulsores_no_verificable",
        "reason": "TimeoutError",
        "drivers": [],
        "blocking": [],
    }
