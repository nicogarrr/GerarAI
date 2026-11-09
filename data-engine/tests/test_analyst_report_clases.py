"""Informe: acciones en circulación con TODAS las clases de la portada (regla «acciones-vigentes-v1»).

Caso real (BD local, 9-nov-2026): la portada del 10-Q de agosto de 2026 de AST SpaceMobile declara
A 299.789.305 + B 11.215.111 + C 78.163.078 = 389.167.494 acciones (dei:EntityCommonStockSharesOutstanding
por clase). La valoración ya usaba esa suma; el Informe se quedaba con la media diluida de la clase A del 2T
(299.061.662) y su capitalización salía un 23 % por debajo (9.669 M$ frente a 12.582 M$ a 32,33 $).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact, MarketPrice
from app.services.analyst_report import build_company_report, build_market

PROV = {"concept": "dei:EntityCommonStockSharesOutstanding", "derivation": "sum_of_class_members",
        "as_of": "2026-08-06", "members": {"CommonClassAMember": "299789305", "CommonClassBMember": "11215111",
                                           "CommonClassCMember": "78163078"}}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _seed(db, *, cover_period="2026-08-06:DEI", provenance=PROV):
    company = Company(ticker="ASTS", name="ASTS", exchange="NASDAQ", currency="USD", sector="S", industry="I",
                      company_type="quality", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    doc = Document(company_id=company.id, title="10-Q instancia XBRL", source_type="SEC",
                   metadata_={"provider": "SEC", "xbrl_instance": True, "class_shares_provenance": provenance})
    db.add(doc)
    db.commit()
    db.add(MarketPrice(company_id=company.id, date=date(2026, 11, 6), open=32.33, high=32.33, low=32.33,
                       close=Decimal("32.33"), volume=1000, quote_currency="USD", source="test"))
    for metric, value in (("shares_diluted", 299_061_662), ("cash_and_equivalents", 1_200_000_000),
                          ("total_debt", 700_000_000)):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
                             period="2026-06-30:Q2", fiscal_quarter="Q2", source_type="SEC", is_reported=True))
    db.add(FinancialFact(company_id=company.id, metric="shares_outstanding", value=Decimal(389_167_494),
                         unit="shares", period=cover_period, source_type="derived", is_reported=False,
                         source_id=doc.id))
    db.commit()
    return company


def test_informe_usa_la_suma_de_clases_de_la_portada(db):
    market = build_company_report(db, _seed(db), today=date(2026, 11, 9))["market"]
    assert market["shares_outstanding"]["value"] == 389_167_494
    assert market["shares_outstanding"]["period_end"] == date(2026, 8, 6)
    assert market["shares_outstanding"]["class_members"] == {"A": 299_789_305.0, "B": 11_215_111.0,
                                                             "C": 78_163_078.0}
    assert market["market_cap_basis"] == "shares_outstanding"
    assert market["market_cap"] == pytest.approx(32.33 * 389_167_494)
    assert market["enterprise_value"] == pytest.approx(32.33 * 389_167_494 + 700e6 - 1_200e6)


def test_sin_procedencia_de_esa_portada_no_se_usa(db):
    # La procedencia es de otra portada: el hecho derivado no es la suma de clases de esa fecha.
    market = build_company_report(db, _seed(db, provenance={**PROV, "as_of": "2026-05-08"}),
                                  today=date(2026, 11, 9))["market"]
    assert market["shares_outstanding"] is None
    assert market["market_cap_basis"] == "shares_diluted"


def test_una_portada_mas_antigua_que_el_recuento_no_manda():
    class _P:
        def __init__(self, value, end):
            self.value, self.unit, self.period_end, self.provenance = Decimal(value), "shares", end, "OFICIAL"

    old = {"value": 389e6, "unit": "shares", "period_end": date(2026, 5, 8), "provenance": "OFICIAL"}
    market = build_market(price=Decimal("10"), price_date=date(2026, 11, 6), price_currency="USD", volumes=[],
                          points={"shares_outstanding": _P(400e6, date(2026, 9, 30))}, cover=old)
    assert market["shares_outstanding"]["value"] == 400e6


def _seed_cover(db, cover_value):
    company = Company(ticker="RXRX", name="RXRX", exchange="NASDAQ", currency="USD", sector="S", industry="I",
                      company_type="quality", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    db.add(MarketPrice(company_id=company.id, date=date(2026, 11, 6), open=3.51, high=3.51, low=3.51,
                       close=Decimal("3.51"), volume=1000, quote_currency="USD", source="test"))
    rows = (("shares_outstanding", "2026-09-30:Q3", "Q3", 561_067_055), ("shares_diluted", "2026-09-30:Q3", "Q3",
            548_000_000), ("shares_outstanding", "2026-10-26:DEI", None, cover_value))
    for metric, period, quarter, value in rows:
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit="shares",
                             period=period, fiscal_quarter=quarter, source_type="SEC", is_reported=True))
    db.commit()
    return company


def test_portada_sec_posterior_al_balance_manda(db):
    # Recursion (BD local): balance del 3T 561.067.055; portada del 10-Q (26-oct-2026) 622.759.259.
    market = build_company_report(db, _seed_cover(db, 622_759_259), today=date(2026, 11, 9))["market"]
    assert market["shares_outstanding"]["value"] == 622_759_259
    assert market["shares_outstanding"]["basis"] == "cover"
    assert market["market_cap"] == pytest.approx(3.51 * 622_759_259)


def test_portada_sin_desglose_muy_por_debajo_de_la_diluida_se_descarta(db):
    # 300 M frente a 548 M diluidas (55 %): puede ser una sola clase; manda el balance.
    market = build_company_report(db, _seed_cover(db, 300_000_000), today=date(2026, 11, 9))["market"]
    assert market["shares_outstanding"]["value"] == 561_067_055
