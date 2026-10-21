"""Criterio material del aviso «Datos nuevos» (data_freshness).

Antes: MAX(updated_at) sobre Fact/Price/News/Doc — el refresco spot pisa
updated_at de la fila de HOY en cada tick y auto-marcaba la tesis como
obsoleta. Ahora:
- Facts/News/Docs: updated_at (no hay refresco vacío conocido; cubre
  correcciones del mismo período).
- MarketPrice: SOLO barra de cierre oficial (source="yfinance", la única
  fuente que el ecosistema considera cierre, ver market_close_sync) con
  fecha de sesión posterior a la última sesión cerrada que la versión pudo
  conocer (regla real 16:30 NY del escritor, sin calendario inventado).
  Tick intradía NO; backfill viejo NO.
"""
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services.thesis_service import ThesisService, _last_official_close_date


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


# Martes 22 sep 2026, 14:00 Nueva York (sesión ABIERTA) = 18:00 UTC (EDT).
AS_OF_SESION_ABIERTA = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
# Mismo día 17:35 NY (sesión YA cerrada) = 21:35 UTC.
AS_OF_TRAS_CIERRE = datetime(2026, 9, 22, 21, 35, tzinfo=UTC)
SESION = date(2026, 9, 22)  # martes


def test_tick_spot_intradia_no_marca_stale(db: Session):
    """El falso positivo original: spot de HOY con updated_at fresco."""
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=SESION, close=10,
                       source="yahoo_finance_intraday",
                       updated_at=AS_OF_SESION_ABIERTA + timedelta(minutes=5)))
    db.commit()
    assert ThesisService().data_freshness(db, company.id, as_of=AS_OF_SESION_ABIERTA) is None


def test_barra_cierre_oficial_nueva_marca_stale(db: Session):
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=SESION, close=10, source="yfinance",
                       updated_at=AS_OF_TRAS_CIERRE))
    db.commit()
    seen = ThesisService().data_freshness(db, company.id, as_of=AS_OF_SESION_ABIERTA)
    assert seen is not None and seen.replace(tzinfo=UTC) > AS_OF_SESION_ABIERTA


def test_backfill_viejo_no_marca_stale(db: Session):
    """Barra oficial de hace un mes escrita AHORA: fecha vieja, no cuenta."""
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=date(2026, 8, 10), close=10,
                       source="yfinance",
                       updated_at=AS_OF_SESION_ABIERTA + timedelta(minutes=5)))
    db.commit()
    assert ThesisService().data_freshness(db, company.id, as_of=AS_OF_SESION_ABIERTA) is None


def test_spot_post_cierre_fecha_hoy_no_marca(db: Session):
    """Spot tardío (tras 16:30 NY) sobre la sesión de hoy: no es cierre."""
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=SESION, close=10,
                       source="yahoo_finance_intraday",
                       updated_at=AS_OF_TRAS_CIERRE + timedelta(minutes=20)))
    db.commit()
    assert ThesisService().data_freshness(db, company.id, as_of=AS_OF_TRAS_CIERRE) is None


def test_cierre_de_hoy_ya_conocido_no_marca(db: Session):
    """Versión generada tras el cierre: la barra de HOY ya la conoce."""
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=SESION, close=10, source="yfinance",
                       updated_at=AS_OF_TRAS_CIERRE))
    db.commit()
    assert ThesisService().data_freshness(db, company.id, as_of=AS_OF_TRAS_CIERRE) is None


def test_hechos_corregidos_mismo_periodo_marcan(db: Session):
    """Corrección material del mismo período (updated_at) se preserva."""
    company = _company(db)
    db.info["tenant_id"] = "tenant-test"
    db.add(FinancialFact(company_id=company.id, metric="revenue", value=200,
                         period="FY2025",
                         updated_at=AS_OF_SESION_ABIERTA + timedelta(minutes=3)))
    db.commit()
    seen = ThesisService().data_freshness(db, company.id, as_of=AS_OF_SESION_ABIERTA)
    assert seen is not None and seen.replace(tzinfo=UTC) > AS_OF_SESION_ABIERTA


def test_sin_as_of_omite_criterio_precios(db: Session):
    """Sin ancla de sesión no hay criterio de precios (conservador)."""
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=SESION, close=10, source="yfinance",
                       updated_at=AS_OF_TRAS_CIERRE))
    db.commit()
    assert ThesisService().data_freshness(db, company.id) is None


@pytest.mark.parametrize("as_of,esperado", [
    (datetime(2026, 9, 22, 18, 0, tzinfo=UTC), date(2026, 9, 21)),   # mar 14:00 NY abierta → lunes
    (datetime(2026, 9, 22, 21, 35, tzinfo=UTC), date(2026, 9, 22)),  # mar 17:35 NY cerrada → martes
    (datetime(2026, 9, 26, 16, 0, tzinfo=UTC), date(2026, 9, 25)),   # sábado → viernes
    (datetime(2026, 9, 28, 13, 0, tzinfo=UTC), date(2026, 9, 25)),   # lunes 09:00 NY abierta → viernes
    (datetime(2026, 3, 9, 13, 0, tzinfo=UTC), date(2026, 3, 6)),     # lunes tras inicio DST (EDT) → viernes
    (datetime(2026, 11, 2, 14, 35, tzinfo=UTC), date(2026, 10, 30)), # lunes tras fin DST (EST) → viernes
    (None, None),
])
def test_ancla_ultima_sesion_cerrada(as_of, esperado):
    assert _last_official_close_date(as_of) == esperado
