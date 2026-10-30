"""fx_table lee columnas, no entidades ORM, y sigue aislada por tenant.

/api/portfolio/intelligence llama a fx_table varias veces por peticion; con
dos años de historico (3 pares) eso eran ~8.700 objetos FXRate construidos solo
para leer cuatro columnas. Medido en local: la ruta pasa de ~700 ms a menos (ver
PR). Aqui se fija el contrato: mismas filas y mismo orden que la consulta de
entidades, ningun FXRate en el identity map, y el predicado de tenant explicito
(una consulta de columnas no recibe el with_loader_criteria de la sesion).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import FXRate, Tenant
from app.services.portfolio_fx_service import PortfolioFXService


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(engine):
    with Session(engine) as s:
        a, b = Tenant(external_id="fx-a"), Tenant(external_id="fx-b")
        s.add_all([a, b])
        s.flush()
        d0 = date(2025, 1, 1)
        for i in range(40):
            d = d0 + timedelta(days=i)
            s.add(FXRate(tenant_id=a.id, base_currency="EUR", quote_currency="USD",
                         rate=Decimal("0.9") + Decimal(i) / 1000, rate_date=d, source="t"))
            s.add(FXRate(tenant_id=a.id, base_currency="EUR", quote_currency="GBP",
                         rate=Decimal("1.1"), rate_date=d, source="t"))
            # Otro tenant: tipos distintos que nunca deben mezclarse.
            s.add(FXRate(tenant_id=b.id, base_currency="EUR", quote_currency="USD",
                         rate=Decimal("5"), rate_date=d, source="t"))
        s.commit()
        return a.id, b.id


def test_fx_table_same_rows_no_orm_entities_and_tenant_scoped(engine):
    a_id, b_id = _seed(engine)
    loaded = []

    def _on_load(target, _context):
        loaded.append(target)

    event.listen(FXRate, "load", _on_load)
    try:
        with Session(engine) as s:
            s.info["tenant_id"] = a_id
            table = PortfolioFXService().fx_table(
                s, currencies={"USD", "GBP"}, base_currency="EUR", as_of_max=date(2025, 1, 20)
            )
    finally:
        event.remove(FXRate, "load", _on_load)
    # Ninguna entidad construida: solo tuplas de columnas.
    assert loaded == []
    with Session(engine) as s:
        s.info["tenant_id"] = a_id
        # Referencia: la consulta de entidades, con el filtro de tenant de la sesion.
        expected: dict = {}
        for row in s.scalars(
            select(FXRate)
            .where(FXRate.tenant_id == a_id, FXRate.rate_date <= date(2025, 1, 20))
            .order_by(FXRate.rate_date, FXRate.created_at)
        ):
            expected.setdefault((row.base_currency, row.quote_currency), []).append(
                (row.rate_date, row.rate)
            )
    assert table == expected
    assert len(table[("EUR", "USD")]) == 20
    assert all(rate != Decimal("5") for _, rate in table[("EUR", "USD")])

    with Session(engine) as s:
        s.info["tenant_id"] = b_id
        other = PortfolioFXService().fx_table(
            s, currencies={"USD"}, base_currency="EUR", as_of_max=date(2025, 1, 20)
        )
    assert {k: {r for _, r in v} for k, v in other.items()} == {("EUR", "USD"): {Decimal("5")}}
