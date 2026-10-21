"""F317: data_freshness filtra tenant en las fuentes tenant-owned.

El MAX(updated_at) agregado no hereda with_loader_criteria: sin filtro
explícito, una fila de otro tenant adelantaría la frescura y marcaría la
tesis como obsoleta sin cambiar su información. MarketPrice es global por
diseño (precios de mercado compartidos) y sí cuenta para todos.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    FinancialFact,
    MarketPrice,
)
from app.services.thesis_service import ThesisService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="KO", name="KO Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_freshness_ignores_other_tenant_rows(db: Session):
    company = _company(db)
    base = datetime(2026, 9, 1, tzinfo=UTC)

    # updated_at se fija en construcción: asignarlo tras el INSERT dispararía
    # el onupdate=utcnow de TimestampMixin y machacaría la marca.
    db.info["tenant_id"] = "tenant-test"
    db.add(FinancialFact(company_id=company.id, metric="revenue", value=100,
                         period="FY2025", updated_at=base))
    db.commit()

    db.info["tenant_id"] = 999
    db.add(FinancialFact(company_id=company.id, metric="revenue", value=200,
                         period="FY2025", updated_at=base + timedelta(days=10)))
    db.commit()

    db.info["tenant_id"] = "tenant-test"
    service = ThesisService()
    seen = service.data_freshness(db, company.id)
    assert seen is not None and seen.replace(tzinfo=UTC) == base

    db.info["tenant_id"] = 999
    seen_otro = service.data_freshness(db, company.id)
    assert seen_otro is not None and seen_otro.replace(tzinfo=UTC) == base + timedelta(days=10)


def test_freshness_market_price_stays_global(db: Session):
    company = _company(db)
    from datetime import date as date_type

    # El criterio de precios cambió (ver test_thesis_data_freshness_material):
    # solo cuenta una barra de CIERRE OFICIAL (source="yfinance") de sesión
    # posterior a la última cerrada que la versión pudo conocer; el precio
    # sigue siendo GLOBAL (sin filtro de tenant).
    db.info["tenant_id"] = "tenant-test"
    db.add(MarketPrice(company_id=company.id, date=date_type(2026, 9, 22),
                       source="yfinance",
                       updated_at=datetime(2026, 9, 22, 21, 35, tzinfo=UTC)))
    db.commit()
    db.info["tenant_id"] = 999  # el precio cuenta aunque la sesión sea de otro tenant
    service = ThesisService()
    # as_of martes 22 sep 14:00 NY (sesión abierta): ancla lunes 21 < barra 22.
    seen = service.data_freshness(db, company.id, as_of=datetime(2026, 9, 22, 18, 0, tzinfo=UTC))
    assert seen is not None
    # Y una fila spot (source distinto de cierre oficial) ya NO alimenta frescura.
    company2 = Company(
        ticker="PEP", name="PEP Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company2)
    db.commit()
    db.add(MarketPrice(company_id=company2.id, date=date_type(2026, 9, 22),
                       source="yahoo_finance_intraday",
                       updated_at=datetime(2026, 9, 22, 21, 35, tzinfo=UTC)))
    db.commit()
    assert service.data_freshness(db, company2.id, as_of=datetime(2026, 9, 22, 18, 0, tzinfo=UTC)) is None
