"""Revision GerarAI, hallazgo A2: point-in-time por fecha de filing (`filed`).

Antes: FinancialFact no guardaba la fecha de publicacion del filing, la
ingesta se quedaba con la cifra mas reciente (reexpresada) y
HistoricalValuationService.build() solo controlaba el ejercicio fiscal; con un
``as_of`` pasado lanzaba LookaheadError en vez de filtrar.

Ahora: la ingesta SEC persiste `filed`, y build(as_of=...) deja fuera lo que no
era publico en ``as_of`` (precio posterior, cifra presentada despues, o sin
`filed` y cierre + 120 dias posterior a as_of).

Caso real del hallazgo: la cifra FY2019 v1 se presenta en el 10-K de feb-2020 y
se REEXPRESA (v2) en el 10-K de feb-2021. Solo se guarda la ultima (v2, con su
fecha): un replay a jun-2020 no puede ver v2 y el ejercicio 2019 sale como
"sin datos", nunca con la cifra futura.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.historical_valuation_service import (
    UNFILED_PUBLICATION_LAG_DAYS,
    HistoricalValuationService,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="PIT"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fy(concept_val_filed_accn):
    rows = []
    for end, val, filed, accn in concept_val_filed_accn:
        year = int(end[:4])
        rows.append({
            "fy": year, "fp": "FY", "form": "10-K", "accn": accn,
            "start": f"{year}-01-01", "end": end, "val": val, "filed": filed,
        })
    return rows


# accn del 10-K FY2019 (presentado 2020-02-20) y del 10-K FY2020 (2021-02-18),
# que trae el FY2019 como comparativo REEXPRESADO.
A19, A20 = "0000000001-20-000010", "0000000001-21-000010"


class _FakeSECRestatement:
    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return {"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": _fy([
                ("2019-12-31", 1000, "2020-02-20", A19),   # v1
                ("2019-12-31", 900, "2021-02-18", A20),    # v2 reexpresada
                ("2020-12-31", 1200, "2021-02-18", A20),
            ])}},
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": _fy([
                ("2019-12-31", 100, "2020-02-20", A19),
                ("2020-12-31", 100, "2021-02-18", A20),
            ])}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": _fy([
                ("2019-12-31", 300, "2020-02-20", A19),
                ("2020-12-31", 350, "2021-02-18", A20),
            ])}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": _fy([
                ("2019-12-31", 100, "2020-02-20", A19),
                ("2020-12-31", 120, "2021-02-18", A20),
            ])}},
        }}}

    async def annual_report_anchors(self, cik):
        return {A19: "2019-12-31", A20: "2020-12-31"}

    async def index_accessions(self, cik):
        return {A19, A20}


def _ingest(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECRestatement)
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    return company


def _annual(db, company, metric):
    return {
        f.fiscal_year: f
        for f in db.scalars(select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == metric,
            FinancialFact.fiscal_quarter == "FY",
        ))
    }


def test_ingesta_sec_guarda_filed_de_la_cifra_guardada(db, monkeypatch):
    company = _ingest(db, monkeypatch)
    revenue = _annual(db, company, "revenue")
    # Se guarda la reexpresada (comportamiento actual) CON su fecha real:
    assert revenue[2019].value == Decimal("900")
    assert revenue[2019].filed == date(2021, 2, 18)
    assert revenue[2019].accession_number == A20
    assert revenue[2020].filed == date(2021, 2, 18)
    shares = _annual(db, company, "shares_diluted")
    assert shares[2019].filed == date(2020, 2, 20)


def test_fcf_derivado_hereda_el_filed_mas_tardio_de_sus_entradas(db, monkeypatch):
    company = _ingest(db, monkeypatch)
    fcf = _annual(db, company, "free_cash_flow")
    assert fcf[2019].value == Decimal("200")
    assert fcf[2019].is_reported is False
    assert fcf[2019].filed == date(2020, 2, 20)
    assert fcf[2020].filed == date(2021, 2, 18)


def test_derivada_sin_filed_en_una_entrada_queda_null():
    con = FinancialFact(metric="a", filed=date(2020, 1, 1))
    sin = FinancialFact(metric="b", filed=None)
    assert ingestion._latest_known_filed(con, sin) is None
    assert ingestion._latest_known_filed(con) == date(2020, 1, 1)


def _price(db, company, day, close):
    db.add(MarketPrice(
        company_id=company.id, date=day, open=close, high=close, low=close,
        close=close, adj_close=close, source="test",
    ))
    db.commit()


def test_replay_antes_de_la_reexpresion_no_ve_la_cifra_futura(db, monkeypatch):
    company = _ingest(db, monkeypatch)
    _price(db, company, date(2019, 12, 31), Decimal("50"))
    _price(db, company, date(2020, 12, 31), Decimal("60"))
    service = HistoricalValuationService()

    before = service.build(db, company, as_of=date(2020, 6, 30))
    points = {p["year"]: p for p in before["series"]}
    # Solo existe v2 (presentada 2021-02-18): en jun-2020 el 2019 es "sin
    # datos" de ventas, no 900. Las acciones (presentadas 2020-02-20) si.
    assert points[2019]["revenue_per_share"] is None
    assert 2019 in before["coverage"]["missing_by_metric"]["revenue_per_share"]
    assert "revenue" not in points[2019]["source_ids"]
    assert "shares_diluted" in points[2019]["source_ids"]
    # El precio de dic-2020 es posterior a as_of: ni aparece ni lanza.
    assert 2020 not in points
    excluded = before["point_in_time"]["excluded_not_public"]
    assert {"metric": "revenue", "fiscal_year": 2019, "known_on": "2021-02-18",
            "filed_known": True} in excluded
    assert before["point_in_time"]["as_of"] == "2020-06-30"

    after = service.build(db, company, as_of=date(2021, 6, 30))
    points = {p["year"]: p for p in after["series"]}
    # Tras la reexpresion: 900 / 100 acciones.
    assert points[2019]["revenue_per_share"] == Decimal("9")
    assert points[2020]["revenue_per_share"] == Decimal("12")


def test_mismo_dia_del_filing_ya_es_publico(db, monkeypatch):
    company = _ingest(db, monkeypatch)
    _price(db, company, date(2019, 12, 31), Decimal("50"))
    result = HistoricalValuationService().build(db, company, as_of=date(2021, 2, 18))
    point = next(p for p in result["series"] if p["year"] == 2019)
    assert point["revenue_per_share"] == Decimal("9")


def _manual_fact(db, company, *, metric, year, value, filed=None, created=None, period=None):
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
        period=period or f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
        source_type="FMP", is_reported=True, confidence=Decimal("0.9"), filed=filed,
    )
    if created is not None:
        fact.created_at = created
    db.add(fact)
    db.commit()
    return fact


def test_sin_filed_usa_cierre_mas_retraso_conservador(db):
    company = _company(db)
    _price(db, company, date(2019, 12, 31), Decimal("50"))
    _manual_fact(db, company, metric="eps", year=2019, value="5")
    lag_end = date(2020, 4, 29)  # 2019-12-31 + 120 dias
    assert UNFILED_PUBLICATION_LAG_DAYS == 120
    service = HistoricalValuationService()

    early = service.build(db, company, as_of=date(2020, 4, 28))
    assert next(p for p in early["series"] if p["year"] == 2019)["eps"] is None
    assert early["point_in_time"]["excluded_not_public"] == [
        {"metric": "eps", "fiscal_year": 2019, "known_on": lag_end.isoformat(),
         "filed_known": False}
    ]
    late = service.build(db, company, as_of=lag_end)
    assert next(p for p in late["series"] if p["year"] == 2019)["eps"] == Decimal("5")


def test_sin_filed_pero_guardada_antes_cuenta_desde_que_se_guardo(db):
    company = _company(db)
    # Guardada el 2020-01-15: era publica como muy tarde ese dia.
    _manual_fact(db, company, metric="eps", year=2019, value="5",
                 created=datetime(2020, 1, 15, tzinfo=UTC))
    result = HistoricalValuationService().build(db, company, as_of=date(2020, 2, 1))
    assert result["series"][0]["eps"] == Decimal("5")


def test_periodo_ilegible_sin_filed_no_tiene_fecha_de_conocimiento():
    fact = FinancialFact(metric="eps", period="sin fecha", fiscal_year=None, fiscal_quarter="FY")
    assert HistoricalValuationService._known_on(fact) is None


def test_as_of_por_defecto_hoy_conserva_lo_guardado(db):
    company = _company(db)
    _price(db, company, date(2024, 12, 31), Decimal("100"))
    _manual_fact(db, company, metric="eps_diluted", year=2024, value="4")
    result = HistoricalValuationService().build(db, company)
    point = next(p for p in result["series"] if p["year"] == 2024)
    assert point["pe"] == Decimal("25")
