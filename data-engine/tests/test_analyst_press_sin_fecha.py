"""Un artículo sin fecha verificable no siembra estimaciones con as_of fabricado.

collect() fechaba con ``_published_from_html(html) or day or today``: un
artículo sin meta de fecha ni fecha RSS entraba con as_of = hoy. Ese as_of
fabricado (1) pisaba por antigüedad a cifras reales de la misma firma (la
regla "una más antigua nunca pisa a una más reciente" se invertía) y (2) se
servía como estimación fresca. Mismo vicio que el fetched_at de provenance:
fecha de request disfrazada de fecha de dato.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import AnalystNote, Company, Tenant
from app.models.declared_input_value import DeclaredInputValue
from app.services import analyst_press_estimates as ape

TEXT = "Clear Street expects Acme Press revenue of $500 million in 2027."


@pytest.fixture()
def tenant_company():
    init_db()
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"apx-{suffix}", name="apx")
        company = Company(ticker=f"AX{suffix}", name="Acme Press, Inc.", exchange="NASDAQ", currency="USD",
                          company_type="operating", valuation_model="standard_dcf")
        db.add_all([tenant, company])
        db.commit()
        ids = (company.id, tenant.id)
    yield ids
    with SessionLocal() as db:
        db.execute(delete(DeclaredInputValue).where(DeclaredInputValue.company_id == ids[0]))
        db.execute(delete(AnalystNote).where(AnalystNote.ticker == f"AX{suffix}"))
        db.execute(delete(Company).where(Company.id == ids[0]))
        db.execute(delete(Tenant).where(Tenant.id == ids[1]))
        db.commit()


def test_articulo_sin_fecha_no_se_guarda(tenant_company):
    company_id, tenant_id = tenant_company
    undated = ape.Article("https://nodate.example/a", "t", date(2026, 11, 16), TEXT, dated=False)
    reading = ape.read_article(undated)
    assert reading.estimates  # la lectura sí extrae (published=hoy solo para relativos)
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        out = ape.store_readings(db, company, tenant_id, [(undated, reading)])
        db.commit()
        assert out["stored"] == []
        assert any("sin fecha verificable" in s for s in out["skipped"])
        rows = db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.company_id == company_id,
            DeclaredInputValue.method == "analyst")).all()
        assert rows == []
        assert db.scalars(select(AnalystNote).where(AnalystNote.ticker == company.ticker)).all() == []


def test_articulo_fechado_se_guarda_con_su_fecha_real(tenant_company):
    company_id, tenant_id = tenant_company
    dated = ape.Article("https://dated.example/a", "t", date(2026, 8, 13), TEXT, dated=True)
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        out = ape.store_readings(db, company, tenant_id, [(dated, ape.read_article(dated))])
        db.commit()
        assert len(out["stored"]) == 1
        assert out["stored"][0]["date"] == "2026-08-13"
        row = db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.company_id == company_id,
            DeclaredInputValue.input_key == "analyst.revenue.fy2027.clear_street",
            DeclaredInputValue.superseded_at.is_(None))).one()
        assert row.as_of == date(2026, 8, 13)
