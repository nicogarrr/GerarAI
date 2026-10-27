"""Divisa de reporte en cada hecho financiero (FMP ``reportedCurrency`` y SEC).

Regresion (auditoria de divisas, 27-oct-2026): los hechos de FMP se guardaban
SIEMPRE con unidad ``USD``. BABA reporta en CNY: su DCF en yuanes se comparaba
con el precio del ADR en dolares (~7x). Por la via SEC solo se leia la clave
``USD`` de companyfacts, asi que un 20-F en US GAAP que reporta en CNY se
quedaba sin hechos.

Tests hermeticos: doble de FMP inyectado, sin red.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.financial_ingestion_service import (
    FinancialIngestionService,
    _sec_reporting_currency,
    _sec_unit_keys,
    _with_reporting_currency,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "BABA") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
        sector="Consumer", industry="Ecommerce", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class FakeFMP:
    def __init__(self, *, income=(), balance=(), cash_flow=(), profile=()):
        self._income = list(income)
        self._balance = list(balance)
        self._cash_flow = list(cash_flow)
        self._profile = list(profile)

    async def income_statement(self, ticker: str, limit: int = 10):
        return list(self._income)

    async def balance_sheet(self, ticker: str, limit: int = 10):
        return list(self._balance)

    async def cash_flow(self, ticker: str, limit: int = 10):
        return list(self._cash_flow)

    async def ratios(self, ticker: str, limit: int = 10):
        return []

    async def company_profile(self, ticker: str):
        return list(self._profile)

    async def quote(self, ticker: str):
        return []


def _refresh(db: Session, company: Company, client: FakeFMP) -> dict:
    return asyncio.run(FinancialIngestionService().refresh_from_fmp(db, company, client=client))


def _units(db: Session, company: Company) -> dict[str, str]:
    return {
        fact.metric: fact.unit
        for fact in db.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company.id)
        )
    }


_ROW = {"date": "2025-03-31", "calendarYear": "2025", "period": "FY", "symbol": "BABA"}


def test_fmp_baba_en_cny_se_guarda_en_cny(db):
    company = _company(db)
    client = FakeFMP(
        income=[{**_ROW, "reportedCurrency": "CNY", "revenue": 996_347_000_000,
                 "netIncome": 129_470_000_000, "epsdiluted": 6.9,
                 "weightedAverageShsOutDil": 19_000_000_000}],
        balance=[{**_ROW, "reportedCurrency": "CNY", "totalDebt": 236_000_000_000,
                  "cashAndCashEquivalents": 145_000_000_000}],
        cash_flow=[{**_ROW, "reportedCurrency": "CNY", "operatingCashFlow": 163_500_000_000,
                    "capitalExpenditure": -85_800_000_000}],
    )

    _refresh(db, company, client)
    units = _units(db, company)

    assert units["revenue"] == "CNY"
    assert units["net_income"] == "CNY"
    assert units["eps_diluted"] == "CNY/share"
    assert units["shares_diluted"] == "shares"
    assert units["operating_cash_flow"] == "CNY"
    # Derivadas: heredan la divisa de sus componentes.
    assert units["free_cash_flow"] == "CNY"
    assert units["net_debt"] == "CNY"
    assert units["fcf_margin"] == "decimal"


def test_fmp_sin_reported_currency_conserva_usd(db):
    company = _company(db, "AAPL")
    client = FakeFMP(
        income=[{**_ROW, "symbol": "AAPL", "revenue": 391_035_000_000}],
    )
    _refresh(db, company, client)
    assert _units(db, company)["revenue"] == "USD"


def test_fcf_no_se_deriva_mezclando_divisas(db):
    company = _company(db)
    client = FakeFMP(
        cash_flow=[{**_ROW, "reportedCurrency": "CNY", "operatingCashFlow": 100}],
        balance=[{**_ROW, "reportedCurrency": "USD", "totalDebt": 50,
                  "cashAndCashEquivalents": 10}],
    )
    # El capex llega en otra fila con otra divisa: no se suman.
    client._cash_flow.append(
        {**_ROW, "date": "2025-03-31", "reportedCurrency": "USD", "capitalExpenditure": -40}
    )
    _refresh(db, company, client)
    derived = [
        fact for fact in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "free_cash_flow",
            )
        )
    ]
    assert derived == []


def test_market_cap_del_perfil_en_divisa_de_cotizacion(db):
    company = _company(db, "SAN.MC")
    client = FakeFMP(profile=[{"currency": "EUR", "mktCap": 70_000_000_000, "beta": 1.1}])
    _refresh(db, company, client)
    assert _units(db, company)["market_cap"] == "EUR"


def test_market_cap_en_subunidad_no_se_guarda(db):
    company = _company(db, "CGEO.L")
    client = FakeFMP(profile=[{"currency": "GBp", "mktCap": 330_000_000_000, "beta": 0.9}])
    _refresh(db, company, client)
    units = _units(db, company)
    assert "market_cap" not in units
    assert units["beta"] == "decimal"


def test_divisa_de_reporte_sec():
    baba = {
        "Assets": {"units": {"CNY": [{"val": 1}] * 10, "USD": [{"val": 1}]}},
        "Revenues": {"units": {"CNY": [{"val": 1}] * 6}},
        "EarningsPerShareDiluted": {"units": {"CNY/shares": [{"val": 1}]}},
    }
    assert _sec_reporting_currency(baba) == "CNY"
    assert _sec_reporting_currency({"Assets": {"units": {"USD": [{"val": 1}]}}}) == "USD"
    assert _sec_reporting_currency({}) is None
    # Empate: desconocido, no preferir USD ni orden alfabetico.
    tie = {"Assets": {"units": {"USD": [{"val": 1}], "EUR": [{"val": 1}]}}}
    assert _sec_reporting_currency(tie) is None


def test_unidades_sec_por_divisa():
    assert _sec_unit_keys("USD", "CNY") == ("CNY", "CNY")
    assert _sec_unit_keys("USD/share", "CNY") == ("CNY/share", "CNY/shares")
    assert _sec_unit_keys("USD/share", "USD") == ("USD/share", "USD/shares")
    assert _sec_unit_keys("shares", "CNY") == ("shares", "shares")
    assert _with_reporting_currency("decimal", "JPY") == "decimal"
    assert _with_reporting_currency("USD", None) == "USD"


def test_sec_currency_tie_without_usd_is_also_unknown():
    facts = {"Assets": {"units": {"CNY": [{"val": 1}], "EUR": [{"val": 1}]}}}
    assert _sec_reporting_currency(facts) is None


def test_sec_unknown_currency_omits_money_but_keeps_non_monetary():
    assert _sec_unit_keys("USD", None) is None
    assert _sec_unit_keys("USD/share", None) is None
    assert _sec_unit_keys("shares", None) == ("shares", "shares")
    assert _sec_unit_keys("decimal", None) == ("decimal", "decimal")
