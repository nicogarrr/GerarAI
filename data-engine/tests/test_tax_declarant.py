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
        "nif": "abc12345", "apellidos_nombre": "GARCIA, NICO",
        "numero_declaracion": "7202025000001", "filed_720_before": False,
        "custody": {"us0378331005": "ie", "CASH:usd": "IE"},
    })
    assert out["nif"] == "ABC12345"
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


ENTITY = {
    "name": "BROKER DE PRUEBA SA", "nif": "tst000", "street": "CALLE PRUEBA 1",
    "city": "DUBLIN", "zip": "D01", "country": "ie",
}


def test_entity_and_first_date_saved_and_read(db):
    svc.write(db, {"custody": {"US0378331005": "IE"}})
    out = svc.write(db, {
        "custody_entities": {"us0378331005": ENTITY},
        "first_acquisition_dates": {"US0378331005": "2023-01-15"},
    })
    stored = db.get(Tenant, db.info["tenant_id"]).metadata_["tax_declarant"]
    assert stored["first_acquisition_dates"] == {"US0378331005": "20230115"}
    assert stored["custody_entities"]["US0378331005"]["country"] == "IE"
    assert stored["custody_entities"]["US0378331005"]["nif"] == "TST000"
    assert out["first_acquisition_dates"] == {"US0378331005": "2023-01-15"}
    assert out["custody_entities"]["US0378331005"]["name"] == "BROKER DE PRUEBA SA"


def test_entity_and_date_can_be_removed(db):
    svc.write(db, {"custody_entities": {"cash:USD": ENTITY}, "first_acquisition_dates": {"US0378331005": "2023-01-15"}})
    out = svc.write(db, {"custody_entities": {"cash:USD": None}, "first_acquisition_dates": {"US0378331005": ""}})
    assert out["custody_entities"] == {} and out["first_acquisition_dates"] == {}


@pytest.mark.parametrize("payload", [
    {"custody_entities": {"US0378331005": {**ENTITY, "street": ""}}},
    {"custody_entities": {"US0378331005": {**ENTITY, "country": "IRL"}}},
    {"custody_entities": {"NOEXISTE": ENTITY}},
    {"first_acquisition_dates": {"US0378331005": "15/01/2023"}},
    {"first_acquisition_dates": {"US0378331005": "2999-01-01"}},
    {"first_acquisition_dates": {"cash:USD": "2023-01-15"}},
])
def test_invalid_entity_or_date_rejected(db, payload):
    with pytest.raises(ValueError):
        svc.write(db, payload)
    assert (db.get(Tenant, db.info["tenant_id"]).metadata_ or {}).get("tax_declarant") is None


def test_entity_country_must_match_custody(db):
    svc.write(db, {"custody": {"US0378331005": "US"}})
    with pytest.raises(ValueError):
        svc.write(db, {"custody_entities": {"US0378331005": ENTITY}})


def test_declarant_input_acepta_nif_extranjero_o_raro():
    """El servidor no valida formato: un NIF extranjero pasa tal cual."""
    from app.api.routes.taxes import DeclarantInput

    assert DeclarantInput(nif="DE123456789").nif == "DE123456789"
    assert DeclarantInput(nif="abc-123 x").nif == "abc-123 x"
    assert DeclarantInput(nif=None).nif is None


def test_declarant_input_rechaza_longitud_absurda_y_controles():
    """Solo se rechaza lo imposible: >32 chars o caracteres de control."""
    from pydantic import ValidationError

    from app.api.routes.taxes import DeclarantInput

    with pytest.raises(ValidationError):
        DeclarantInput(nif="X" * 33)
    with pytest.raises(ValidationError):
        DeclarantInput(nif="12345678Z\x00")
    with pytest.raises(ValidationError):
        DeclarantInput(nif="12345678Z\n")
    # 32 justos sí entran
    assert len(DeclarantInput(nif="X" * 32).nif) == 32


@pytest.mark.parametrize("raw,clean", [
    ("DE-123456789", "DE123456789"),
    ("DE 123 456 789", "DE123456789"),
    ("IT 01234567890", "IT01234567890"),
    ("AB123456789012345678", "AB123456789012345678"),
])
def test_foreign_declarant_nif_separators_normalized(db, raw, clean):
    assert svc.write(db, {"nif": raw})["nif"] == clean
