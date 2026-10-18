"""Datos del declarante: lectura, validación y fusión sin perder claves ajenas.

Run from data-engine/:
    pytest tests/test_tax_declarant.py -v
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, Company, Portfolio, Position, Tenant
from app.services import tax_declarant_service as svc


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="decl-test", name="t", metadata_={})
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", company_type="imported_holding", valuation_model="unassigned", isin="US0378331005")
        session.add(company)
        session.flush()
        portfolio = Portfolio(name="Main", base_currency="EUR")
        session.add(portfolio)
        session.flush()
        session.add(Position(
            tenant_id=tenant.id, portfolio_id=portfolio.id, company_id=company.id,
            quantity=1, base_currency="EUR",
        ))
        session.add(CashBalance(tenant_id=tenant.id, currency="usd", balance=10))
        session.commit()
        yield session


def test_read_empty_lists_partidas(db):
    out = svc.read(db)
    assert out["nif"] == "" and out["custody"] == {} and out["filed_720_before"] is None
    assert out["partidas"] == ["US0378331005", "cash:USD"]


def test_write_merges_and_keeps_foreign_keys(db):
    tenant = db.get(Tenant, db.info["tenant_id"])
    tenant.metadata_ = {"tax_declarant": {"custody_entities": {"X": {"name": "B"}}}, "otra": 1}
    db.commit()
    out = svc.write(db, {
        "nif": "12345678a", "apellidos_nombre": "GARCIA, NICO",
        "numero_declaracion": "7202025000001", "filed_720_before": False,
        "custody": {"us0378331005": "ie", "CASH:usd": "IE"},
    })
    assert out["nif"] == "12345678A"
    assert out["custody"] == {"US0378331005": "IE", "cash:USD": "IE"}
    stored = db.get(Tenant, tenant.id).metadata_
    assert stored["otra"] == 1
    assert stored["tax_declarant"]["custody_entities"] == {"X": {"name": "B"}}
    assert stored["tax_declarant"]["filed_720_before"] is False


def test_empty_value_removes_field(db):
    svc.write(db, {"telefono": "600000000", "custody": {"US0378331005": "IE"}})
    out = svc.write(db, {"telefono": "", "custody": {"US0378331005": ""}})
    assert out["telefono"] == "" and out["custody"] == {}


@pytest.mark.parametrize("payload", [
    {"nif": "!!"},
    {"numero_declaracion": "123"},
    {"telefono": "abc"},
    {"custody": {"US0378331005": "IRL"}},
    {"custody": {"NOEXISTE": "IE"}},
    {"filed_720_before": "si"},
])
def test_invalid_input_rejected_and_nothing_saved(db, payload):
    with pytest.raises(ValueError):
        svc.write(db, payload)
    assert (db.get(Tenant, db.info["tenant_id"]).metadata_ or {}).get("tax_declarant") is None


def test_requires_tenant_context(db):
    db.info.pop("tenant_id")
    with pytest.raises(PermissionError):
        svc.read(db)
