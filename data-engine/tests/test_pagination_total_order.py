"""Paginacion con orden total: id como desempate en las reglas de alerta.

Con la clave de orden repetida (reglas creadas en lote con el mismo created_at)
LIMIT/OFFSET no tiene orden definido:
Postgres puede repetir una fila en dos paginas y saltarse otra. El contrato:
mas reciente primero y, a igualdad, el id mayor primero.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.alerts import list_alert_rules
from app.models.entities import AlertRule, Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_reglas_con_el_mismo_created_at_paginan_por_id_descendente(db):
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", sector="Tech",
        industry="Tech", company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    same = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    for i in range(5):
        db.add(AlertRule(
            company_id=company.id, name=f"r{i}", rule_type="price_above",
            condition={"operator": ">", "value": 1}, target={"kind": "market_price"},
            severity="medium", channels=["in_app"], active=True, created_at=same,
        ))
    db.commit()
    pages = [
        [r.id for r in list_alert_rules(ticker=None, active=None, limit=2, offset=o, db=db)]
        for o in (0, 2, 4)
    ]
    flat = [i for page in pages for i in page]
    assert flat == sorted(flat, reverse=True)
    assert len(set(flat)) == 5
