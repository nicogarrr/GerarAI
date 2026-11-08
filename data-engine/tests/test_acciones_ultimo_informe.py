"""Acciones del ultimo informe, no la media diluida del ejercicio.

Antes (main 95a9c193d) el DCF dividia por la media diluida del ultimo
ejercicio aunque hubiera 10-Q o portadas posteriores: ASTS 256 M (2T-26: 299),
RXRX 447 (portada: 623), TSLA 3.528 (en circulacion: 3.953), CB 401,5 (3T-26:
389,4). Ahora: diluida trimestral mas reciente de la misma fuente, sin bajar de
la anual si el trimestre tiene perdidas (antidilucion) y nunca por debajo de
las acciones en circulacion posteriores. La anual queda en la traza.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, FinancialFact
from app.valuation.engines.base import snapshot_trace
from app.valuation.financial_snapshot import FinancialSnapshot, FinancialSnapshotBuilder


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.info["tenant_id"] = 2
        company = Company(ticker="SHR", name="Shares", exchange="NASDAQ", currency="USD", sector="S",
                          industry="I", company_type="operating", valuation_model="unassigned",
                          special_sources=[], special_risks=[], factor_tags=[])
        session.add(company)
        session.commit()
        yield session
    eng.dispose()


def _fact(metric, period, value, *, quarter=None, source="SEC", filed=date(2026, 11, 2)):
    return FinancialFact(metric=metric, period=period, value=Decimal(str(value)), unit="shares",
                         fiscal_quarter=quarter, source_type=source, filed=filed)


ANNUAL = _fact("shares_diluted", "2025-12-31:FY", 447.4e6, quarter="FY", filed=date(2026, 2, 27))


def _run(db, facts, annual=ANNUAL):
    company = db.query(Company).one()
    snap = FinancialSnapshot(facts={"shares_diluted": annual}, shares_period=annual.period)
    pool: dict[str, list] = {}
    for fact in facts:
        pool.setdefault(fact.metric, []).append(fact)
    FinancialSnapshotBuilder._latest_share_count(db, company, snap, lambda m: pool.get(m, []), date(2026, 11, 6))
    return snap


def test_usa_la_diluida_del_ultimo_10q(db):
    snap = _run(db, [_fact("shares_diluted", "2026-06-30:Q2", 532.5e6, quarter="Q2"),
                     _fact("shares_diluted", "2026-09-30:Q3", 543.0e6, quarter="Q3")])
    assert snap.value("shares_diluted") == pytest.approx(543.0e6)
    assert snap.shares_period == "2026-09-30:Q3"
    assert snapshot_trace(snap)["shares_fiscal_year"]["value"] == pytest.approx(447.4e6)


def test_nunca_por_debajo_de_las_acciones_en_circulacion_posteriores(db):
    snap = _run(db, [_fact("shares_diluted", "2026-09-30:Q3", 543.0e6, quarter="Q3"),
                     _fact("shares_outstanding", "2026-10-26:DEI", 622.8e6)])
    assert snap.value("shares_diluted") == pytest.approx(622.8e6)
    assert "circulación" in snap.warnings[-1]


def test_trimestre_con_perdidas_no_rebaja_la_diluida_anual(db):
    annual = _fact("shares_diluted", "2025-12-31:FY", 258.2e6, quarter="FY", filed=date(2026, 2, 27))
    snap = _run(db, [_fact("shares_diluted", "2026-06-30:Q2", 231.7e6, quarter="Q2"),
                     FinancialFact(metric="net_income", period="2026-06-30:Q2", value=Decimal("-86.3e6"),
                                   unit="USD", source_type="SEC")], annual=annual)
    assert snap.value("shares_diluted") == pytest.approx(258.2e6)
    assert "pérdidas" in snap.warnings[-1]


def test_recompras_bajan_las_acciones(db):
    annual = _fact("shares_diluted", "2025-12-31:FY", 401.5e6, quarter="FY", filed=date(2026, 2, 27))
    snap = _run(db, [_fact("shares_diluted", "2026-09-30:Q3", 389.4e6, quarter="Q3"),
                     _fact("shares_outstanding", "2026-10-20:DEI", 382.1e6)], annual=annual)
    assert snap.value("shares_diluted") == pytest.approx(389.4e6)


def test_no_mezcla_fuentes_ni_escalas(db):
    # Serie de otro proveedor (ADS) y un trimestre en miles: no sustituyen.
    snap = _run(db, [_fact("shares_diluted", "2026-09-30:Q3", 89.0e6, quarter="Q3", source="YAHOO_FUNDAMENTALS"),
                     _fact("shares_diluted", "2026-06-30:Q2", 543.0e3, quarter="Q2")])
    assert snap.value("shares_diluted") == pytest.approx(447.4e6)
    assert "escala incompatible" in snap.warnings[-1]
