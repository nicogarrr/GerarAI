"""Tipos de cambio del BCE de la fecha de cada operación (art. 34-35 LIRPF).

1) Antigüedad máxima: el informe solo acepta el último tipo publicado si es
   de como mucho 7 días antes (fines de semana y festivos TARGET). Antes se
   usaba cualquier tipo anterior, aunque fuera de meses atrás.
2) Descarga histórica del BCE: serie EXR D.<DIVISA>.EUR.SP00.A. El BCE
   publica unidades por 1 EUR; la tabla guarda EUR por 1 unidad (1/publicado).

Cálculo a mano:
  USD 29/12/2025 = 1,1766 por EUR → 1 USD = 1/1,1766 = 0,849906510 EUR.
  Dividendo de 100 $ el 29/12/2025 → 84,99 €.
  GBP 29/12/2025 = 0,8726 por EUR → 1 GBX (penique) = 1/(0,8726×100) =
  0,011460... EUR; 250 GBX → 2,87 €.
  Tipo guardado solo el 02/01/2025 (1 USD = 0,96 EUR):
    dividendo del 06/01/2025 (4 días): 100 $ → 96,00 € (se acepta);
    dividendo del 01/03/2025 (58 días): sin tipo → importe en EUR desconocido.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.connectors.ecb_history import backfill_ecb_rates, parse_ecb_csv
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.tax_report_service import TaxReportService

CSV = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "EXR.D.GBP.EUR.SP00.A,D,GBP,EUR,SP00,A,2025-12-29,0.8726,A\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2025-12-29,1.1766,A\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2025-12-30,1.1740,A\n"
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker="USX", name="USX", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[], domicile_country="US",
    )
    db.add(company)
    db.commit()
    return company


def _dividend(db, company, day, amount, currency="USD"):
    db.add(Transaction(
        company_id=company.id, trade_date=day, action="dividend",
        quantity=Decimal("1"), price=Decimal(str(amount)),
        fees=Decimal("0"), currency=currency,
    ))
    db.commit()


def test_parse_ecb_csv():
    rows = parse_ecb_csv(CSV)
    assert (date(2025, 12, 29), "USD", Decimal("1.1766")) in rows
    assert len(rows) == 3


def test_backfill_guarda_eur_por_unidad_y_subunidades(db):
    async def fake_fetch(codes, start, end):
        assert codes == ["GBP", "USD"]
        return CSV

    summary = asyncio.run(backfill_ecb_rates(
        db, currencies={"USD", "GBX", "EUR"},
        start=date(2025, 12, 29), end=date(2025, 12, 30), fetcher=fake_fetch,
    ))
    assert summary["written"] == {"USD": 2, "GBX": 1}
    usd = db.scalar(select(FXRate).where(
        FXRate.quote_currency == "USD", FXRate.rate_date == date(2025, 12, 29)))
    assert usd is not None and usd.source == "ECB"
    assert usd.rate == pytest.approx(Decimal("0.849906510"), abs=Decimal("1e-9"))
    gbx = PortfolioFXService().rate(
        db, quote_currency="GBX", base_currency="EUR", as_of=date(2025, 12, 29))
    assert gbx is not None
    assert gbx * 250 == pytest.approx(Decimal("2.8650"), abs=Decimal("0.0001"))


def test_informe_usa_el_tipo_bce_descargado(db):
    company = _company(db)

    async def fake_fetch(codes, start, end):
        return CSV

    asyncio.run(backfill_ecb_rates(
        db, currencies={"USD"}, start=date(2025, 12, 29), end=date(2025, 12, 30),
        fetcher=fake_fetch,
    ))
    _dividend(db, company, date(2025, 12, 29), 100)
    report = TaxReportService().compute_report(db, 2025)
    assert report["dividends"][0]["dividends_base"] == 84.99


def test_tipo_de_mas_de_7_dias_no_se_usa(db):
    company = _company(db)
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2025, 1, 2), rate=Decimal("0.96"), source="ECB"))
    db.commit()
    _dividend(db, company, date(2025, 1, 6), 100)   # 4 días: válido
    _dividend(db, company, date(2025, 3, 1), 100)   # 58 días: caducado
    report = TaxReportService().compute_report(db, 2025)
    bucket = report["dividends"][0]
    assert bucket["missing_fx"] is True
    payments = [p for p in bucket["payments"] if p["type"] == "dividend"]
    by_date = {p["date"]: p["amount_base"] for p in payments}
    assert by_date["2025-01-06"] == 96.0
    assert by_date["2025-03-01"] is None


def test_cartera_solo_en_peniques_tiene_tipo_tras_la_descarga(db):
    """Solo hay operaciones en GBp (peniques), ninguna en GBP.

    A mano: GBP 29/12/2025 = 0,8726 por EUR → 1 GBP = 1/0,8726 EUR =
    1,1460005 EUR; 1 GBp = 0,011460005 EUR; dividendo de 250 GBp → 2,86 €
    (2,8650 redondeado a céntimos: 2,86 o 2,87 según la regla del informe).
    Antes la descarga guardaba una fila «GBX» que ningún lector consulta y
    el tipo de GBp seguía sin existir: el dividendo salía «sin tipo».
    """
    company = _company(db)

    async def fake_fetch(codes, start, end):
        assert codes == ["GBP"]
        return CSV

    asyncio.run(backfill_ecb_rates(
        db, currencies={"GBp"}, start=date(2025, 12, 29), end=date(2025, 12, 30),
        fetcher=fake_fetch,
    ))
    rate = PortfolioFXService().rate(
        db, quote_currency="GBp", base_currency="EUR", as_of=date(2025, 12, 29))
    assert rate is not None
    assert rate * 250 == pytest.approx(Decimal("2.8650"), abs=Decimal("0.0001"))
    gbp = PortfolioFXService().rate(
        db, quote_currency="GBP", base_currency="EUR", as_of=date(2025, 12, 29))
    assert gbp == pytest.approx(Decimal("1.1460005"), abs=Decimal("0.000001"))
    _dividend(db, company, date(2025, 12, 29), 250, currency="GBp")
    bucket = TaxReportService().compute_report(db, 2025)["dividends"][0]
    assert not bucket.get("missing_fx")
    assert bucket["dividends_base"] == pytest.approx(2.87, abs=0.011)
