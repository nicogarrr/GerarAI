"""FIX5: guardas de los defectos de ingesta SEC/FMP/ESEF.

Cada test protege un defecto concreto de la lista FIX5 (el eval de
`evals/ingest/` cubre los mismos via casos del dataset; aqui se fijan los
contratos del servicio: claves del resultado, colapso de claves, fail-closed de
entidad y fechas de publicacion).

Hermetico: sin red (el snapshot best-effort de filings/macro se sustituye).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import (
    FinancialIngestionService,
    _norm_date,
    _period,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture(autouse=True)
def _sin_free_data(monkeypatch):
    async def _stub(ticker, cik):
        return {"status": "skipped", "recent_filings": [], "macro": None}

    monkeypatch.setattr(ingestion, "_free_data_snapshot", _stub)


def _company(db, ticker="ACME", cik=None):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[], cik=cik,
    )
    db.add(company)
    db.commit()
    return company


def _facts(db, company, metric):
    return list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id, FinancialFact.metric == metric
        )
    ))


# --------------------------------------------------------------------------
# FIX5-1: refresh_from_sec recibe as_of y filtra por fecha de publicacion
# --------------------------------------------------------------------------


class _FakeSECConCortes:
    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return {"cik": 1, "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"fy": 2999, "fp": "FY", "form": "10-K", "start": "2999-01-01",
                 "end": "2999-12-31", "val": 42000000000, "filed": "3000-02-10",
                 "accn": "0000000001-99-000001"},
                {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
                 "end": "2025-12-31", "val": 5000000000, "filed": "2026-02-10",
                 "accn": "0000000001-25-000001"},
            ]}}}}}

    async def annual_report_anchors(self, cik):
        return {"0000000001-99-000001": "2999-12-31", "0000000001-25-000001": "2025-12-31"}


def test_as_of_excluye_lo_no_publicado_y_se_declara(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECConCortes)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company, as_of=date(2026, 10, 1))
    )
    assert result["status"] == "ingested"
    assert result["as_of"] == "2026-10-01"
    assert result["date_filter_applied"] is True
    periods = {f.period for f in _facts(db, company, "revenue")}
    assert periods == {"2025-12-31:FY"}  # el FY2999 (filed 3000) no entra


def test_sin_as_of_el_filtro_de_fecha_no_se_aplica(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECConCortes)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["date_filter_applied"] is False
    assert result["as_of"] is None
    periods = {f.period for f in _facts(db, company, "revenue")}
    assert periods == {"2999-12-31:FY", "2025-12-31:FY"}


# --------------------------------------------------------------------------
# FIX5-2: _period normaliza epochs y conserva lo no parseable
# --------------------------------------------------------------------------


def test_period_normaliza_epoch_de_fmp():
    period, fiscal_year, fiscal_quarter = _period({"date": 1767139200, "period": "FY"})
    assert period == "2025-12-31:FY"
    assert fiscal_quarter == "FY"
    assert fiscal_year is None
    assert _norm_date(1767139200) == "2025-12-31"
    assert _norm_date("1767139200.0") == "2025-12-31"
    assert _norm_date(1767139200000) == "2025-12-31"  # epoch en milisegundos


def test_period_conserva_fechas_imposibles_verbatim():
    """Un cierre imposible debe llegar a la etiqueta para que la puerta
    no_lookahead lo acuse, no esfumarse en un `unknown` (FIX5-10)."""
    period, fiscal_year, _fiscal_quarter = _period(
        {"date": "2025-99-99", "period": "FY", "calendarYear": 2025}
    )
    assert period == "2025-99-99:FY"
    assert fiscal_year == 2025


# --------------------------------------------------------------------------
# FIX5-3: refresh_from_fmp contrasta el symbol de cada fila
# --------------------------------------------------------------------------


class _FakeFMPConSymbol:
    async def income_statement(self, ticker, limit=5):
        return [
            {"symbol": "OTRA", "date": "2025-12-31", "period": "FY", "calendarYear": 2025,
             "revenue": 999000000000, "netIncome": 99000000000},
            {"symbol": "ACME", "date": "2025-12-31", "period": "FY", "calendarYear": 2025,
             "revenue": 5000000000, "netIncome": 500000000},
        ]

    async def balance_sheet(self, ticker, limit=5):
        return []

    async def cash_flow(self, ticker, limit=5):
        return []

    async def ratios(self, ticker, limit=5):
        return []

    async def company_profile(self, ticker):
        return []

    async def quote(self, ticker):
        return []


def test_refresh_from_fmp_rechaza_filas_de_otro_simbolo(db):
    company = _company(db, "ACME")
    result = asyncio.run(
        FinancialIngestionService().refresh_from_fmp(db, company, client=_FakeFMPConSymbol())
    )
    assert result["rows_rechazadas_por_symbol"] == 1
    revenues = _facts(db, company, "revenue")
    assert [f.value for f in revenues] == [Decimal("5000000000")]
    assert all(f.period == "2025-12-31:FY" for f in revenues)


# --------------------------------------------------------------------------
# FIX5-4: _add_facts colapsa (metrica, periodo)
# --------------------------------------------------------------------------


class _FakeFMPDuplicado:
    async def income_statement(self, ticker, limit=5):
        return [
            {"symbol": "ACME", "date": "2025-12-31", "period": "FY", "calendarYear": 2025,
             "revenue": 5000000000, "netIncome": 500000000},
            {"symbol": "ACME", "date": "2025-12-31", "period": "FY", "calendarYear": 2025,
             "revenue": 5000000000, "netIncome": 500000000},
        ]

    async def balance_sheet(self, ticker, limit=5):
        return []

    async def cash_flow(self, ticker, limit=5):
        return []

    async def ratios(self, ticker, limit=5):
        return []

    async def company_profile(self, ticker):
        return []

    async def quote(self, ticker):
        return []


def test_add_facts_collapse_por_metrica_y_periodo(db):
    company = _company(db, "ACME")
    asyncio.run(FinancialIngestionService().refresh_from_fmp(db, company, client=_FakeFMPDuplicado()))
    revenues = _facts(db, company, "revenue")
    assert len(revenues) == 1, "el mismo (metrica, periodo) debe colapsar a una fila"
    assert revenues[0].value == Decimal("5000000000")


def test_add_facts_sustituye_la_derivada_vieja_de_la_clave(db):
    company = _company(db, "ACME")
    stale = FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("1"),
        unit="USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
        source_type="SEC", is_reported=False, confidence=Decimal("0.5"),
    )
    db.add(stale)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_fmp(db, company, client=_FakeFMPDuplicado()))
    revenues = _facts(db, company, "revenue")
    assert [f.value for f in revenues] == [Decimal("5000000000")]
    assert revenues[0].is_reported is True


# --------------------------------------------------------------------------
# FIX5-6: el CIK del payload se contrasta con el resuelto y con la ficha
# --------------------------------------------------------------------------


class _FakeSECConCik:
    payload = {"cik": 99, "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
             "end": "2025-12-31", "val": 5000000000, "filed": "2026-02-10",
             "accn": "0000000001-25-000001"},
        ]}}}}}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000001": "2025-12-31"}


def test_refresh_from_sec_fail_closed_si_el_cik_del_payload_no_casa(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECConCik)
    company = _company(db)
    with pytest.raises(RuntimeError, match="CIK del payload"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _facts(db, company, "revenue") == []


def test_refresh_from_sec_fail_closed_si_la_ficha_declara_otro_cik(db, monkeypatch):
    class _Fake(_FakeSECConCik):
        payload = {"cik": 1, "facts": {"us-gaap": {}}}

    monkeypatch.setattr(ingestion, "SECClient", _Fake)
    company = _company(db, cik="0000000099")
    with pytest.raises(RuntimeError, match="CIK de la ficha"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))


def test_payload_sin_cik_declarado_no_se_puede_contrastar(db, monkeypatch):
    """Sin entidad declarada no hay nada que falsificar (los payloads
    sinteticos de tests viven aqui; la API real siempre declara `cik`)."""
    class _Fake(_FakeSECConCik):
        payload = {"facts": {"us-gaap": {}}}

    monkeypatch.setattr(ingestion, "SECClient", _Fake)
    company = _company(db)
    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert result["status"] == "ingested"


# --------------------------------------------------------------------------
# FIX5-8: shares_diluted no mezcla saldo instantaneo con promedio ponderado
# --------------------------------------------------------------------------


class _FakeSECShares:
    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return {"cik": 1, "facts": {"us-gaap": {
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
                {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
                 "end": "2025-12-31", "val": 1176000000, "filed": "2026-02-10",
                 "accn": "0000000001-25-000001"},
            ]}},
            "CommonStockSharesOutstanding": {"units": {"shares": [
                {"fy": 2025, "fp": "FY", "form": "10-K", "end": "2025-12-31",
                 "val": 1250000000, "filed": "2026-03-01", "accn": "0000000001-25-000001"},
            ]}},
        }}}

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000001": "2025-12-31"}


class _FakeSECSharesTrimestral(_FakeSECShares):
    async def company_facts(self, cik):
        return {"cik": 1, "facts": {"us-gaap": {
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
                {"fy": 2025, "fp": "Q2", "form": "10-Q", "start": "2025-04-01",
                 "end": "2025-06-30", "val": 1170000000, "filed": "2025-08-01",
                 "accn": "0000000001-25-000010"},
            ]}},
            "CommonStockSharesOutstanding": {"units": {"shares": [
                {"fy": 2025, "fp": "Q3", "form": "10-Q", "end": "2025-08-15",
                 "val": 1260000000, "filed": "2025-08-15", "accn": "0000000001-25-000010"},
            ]}},
        }}}


def test_shares_diluted_es_el_promedio_y_el_saldo_es_otra_metrica(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECShares)
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    diluted = _facts(db, company, "shares_diluted")
    assert [f.value for f in diluted] == [Decimal("1176000000")]
    outstanding = _facts(db, company, "shares_outstanding")
    assert [f.value for f in outstanding] == [Decimal("1250000000")]


def test_el_conteo_de_portada_no_entra_como_shares_diluted_trimestral(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECSharesTrimestral)
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    diluted = _facts(db, company, "shares_diluted")
    assert [f.period for f in diluted] == ["2025-06-30:Q2"]
    outstanding = _facts(db, company, "shares_outstanding")
    assert [f.period for f in outstanding] == ["2025-08-15:Q3"]




@pytest.mark.parametrize("foreign_source,quarter", [("SEC", "FY"), ("FMP", "TTM")])
def test_fmp_derivatives_never_borrow_foreign_provider_or_ttm(db, foreign_source, quarter):
    from app.models.entities import Document
    company = _company(db)
    document = Document(company_id=company.id, title="FMP test", source_type="FMP")
    db.add(document)
    db.flush()
    for metric, value, source, period_type in (
        ("operating_cash_flow", "100", "FMP", "FY"),
        ("capital_expenditure", "-20", foreign_source, quarter),
    ):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value),
            unit="USD", period=f"2025-12-31:{period_type}", fiscal_year=2025,
            fiscal_quarter=period_type, source_type=source, is_reported=True,
            confidence=Decimal("0.9")))
    db.flush()
    FinancialIngestionService()._add_derived_facts(db, company, document)
    assert _facts(db, company, "free_cash_flow") == []


def test_fmp_derivatives_use_only_own_annual_pair(db):
    from app.models.entities import Document
    company = _company(db)
    document = Document(company_id=company.id, title="FMP test", source_type="FMP")
    db.add(document)
    db.flush()
    for metric, value, source, quarter in (
        ("operating_cash_flow", "100", "FMP", "FY"),
        ("capital_expenditure", "-20", "FMP", "FY"),
        ("operating_cash_flow", "900", "SEC", "FY"),
        ("capital_expenditure", "-800", "FMP", "TTM"),
    ):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value),
            unit="USD", period=f"2025-12-31:{quarter}", fiscal_year=2025,
            fiscal_quarter=quarter, source_type=source, is_reported=True,
            confidence=Decimal("0.9")))
    db.flush()
    FinancialIngestionService()._add_derived_facts(db, company, document)
    (fact,) = _facts(db, company, "free_cash_flow")
    assert fact.value == Decimal("80")
    assert fact.source_type == "FMP"
    assert fact.fiscal_quarter == "FY"


# --------------------------------------------------------------------------
# Fail-closed de red y entidad en refresh_from_sec (caminos async, clientes
# doblados, SQLite real en memoria). NO prueba: red real, el indice DEI con
# accessiones verificadas, ni la deduplicacion por fingerprint (otros tests).
# --------------------------------------------------------------------------


class _FakeSECSinCik:
    async def cik_for_ticker(self, ticker):
        return None


def test_refresh_from_sec_sin_cik_fail_closed(db, monkeypatch):
    """Un ticker sin CIK resoluble no reporta a la SEC: RuntimeError y la
    ficha queda sin hechos (el emisor usa la fuente de su mercado local)."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECSinCik)
    company = _company(db)
    with pytest.raises(RuntimeError, match="Sin CIK"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _facts(db, company, "revenue") == []


class _FakeSECCaidaEnCik:
    async def cik_for_ticker(self, ticker):
        raise ConnectionError("red caida")


def test_refresh_from_sec_error_resolviendo_cik_es_runtime_error(db, monkeypatch):
    """Un fallo de red resolviendo el CIK no se traga: RuntimeError 'SEC
    fetch failed' y sin hechos persistidos."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECCaidaEnCik)
    company = _company(db)
    with pytest.raises(RuntimeError, match="SEC fetch failed"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _facts(db, company, "revenue") == []


class _FakeSECCaidaEnFacts:
    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        raise TimeoutError("timeout")


def test_refresh_from_sec_error_leyendo_facts_es_runtime_error(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECCaidaEnFacts)
    company = _company(db)
    with pytest.raises(RuntimeError, match="SEC fetch failed"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _facts(db, company, "revenue") == []


class _FakeSECEntidadAjena:
    """Mismo ticker, otro emisor (PRIM en BME vs Perimeter en NYSE)."""

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return {"cik": 1, "entityName": "Perimeter Solutions Inc.",
                "facts": {"us-gaap": {}}}

    async def annual_report_anchors(self, cik):
        return {}


def test_refresh_from_sec_entidad_ajena_en_bolsa_extranjera_falla(db, monkeypatch):
    """Listado no estadounidense cuya razon social SEC no casa con la ficha:
    RuntimeError y ningun hecho del homonimo entra."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECEntidadAjena)
    company = Company(
        ticker="PRM", name="Prim SA", exchange="BME", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[], cik=None,
    )
    db.add(company)
    db.commit()
    with pytest.raises(RuntimeError, match="no es el emisor"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _facts(db, company, "revenue") == []


class _FakeSECAnclasCaidas:
    payload = {"cik": 1, "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
             "end": "2025-12-31", "val": 5000000000, "filed": "2026-02-10",
             "accn": "0000000001-25-000001"},
        ]}}}}}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        raise ConnectionError("submissions caido")


def test_refresh_from_sec_anclas_caidas_fail_closed_anual(db, monkeypatch):
    """Sin anclas de filing no entra NINGUN hecho anual (fail closed): el
    refresh termina 'ingested', declara 0 anclas y no persiste el FY."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECAnclasCaidas)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    assert result["annual_anchored_filings"] == 0
    assert _facts(db, company, "revenue") == []


# --------------------------------------------------------------------------
# Atajo unchanged por fingerprint e ifrs-full en refresh_from_sec. NO prueba:
# mirror real (drain vacio en tests), DEI verificado, ni reglas NCI del mapa
# ifrs (el doble solo etiqueta Revenue, sin minoritarios).
# --------------------------------------------------------------------------


class _FakeSECEstable:
    payload = {"cik": 1, "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
             "end": "2025-12-31", "val": 5000000000, "filed": "2026-02-10",
             "accn": "0000000001-25-000001"},
        ]}}}}}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000001": "2025-12-31"}


def test_refresh_from_sec_segunda_corrida_identica_es_unchanged(db, monkeypatch):
    """Mismo payload y mismas anclas: la segunda corrida no reingiere, sale
    por el atajo 'unchanged' (facts_imported 0) y no duplica hechos."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECEstable)
    company = _company(db)
    servicio = FinancialIngestionService()
    primero = asyncio.run(servicio.refresh_from_sec(db=db, company=company))
    assert primero["status"] == "ingested"
    segundo = asyncio.run(servicio.refresh_from_sec(db=db, company=company))
    assert segundo["status"] == "unchanged"
    assert segundo["facts_imported"] == 0
    assert segundo["source_document_id"] == primero["source_document_id"]
    assert len(_facts(db, company, "revenue")) == 1


class _FakeSECIfrs:
    """Filer IFRS (20-F): companyfacts solo trae la taxonomia ifrs-full."""

    # La divisa de reporte se prueba con conceptos de referencia (Assets):
    # sin ellos la moneda es desconocida y el USD entra fail closed (nada).
    payload = {"cik": 1, "facts": {"ifrs-full": {
        "Assets": {"units": {"USD": [
            {"fy": 2025, "fp": "FY", "form": "20-F",
             "end": "2025-12-31", "val": 20000000000, "filed": "2026-03-01",
             "accn": "0000000001-25-000002"},
        ]}},
        "Revenue": {"units": {"USD": [
            {"fy": 2025, "fp": "FY", "form": "20-F", "start": "2025-01-01",
             "end": "2025-12-31", "val": 7000000000, "filed": "2026-03-01",
             "accn": "0000000001-25-000002"},
        ]}}}}}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000002": "2025-12-31"}


def test_refresh_from_sec_filer_ifrs_ingiere_con_mapa_ifrs(db, monkeypatch):
    """Sin hechos us-gaap pero con ifrs-full: la ingesta cambia de taxonomia
    y de mapa de conceptos y el revenue IFRS entra con su periodo FY."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECIfrs)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    (revenue,) = _facts(db, company, "revenue")
    assert revenue.value == Decimal("7000000000")
    assert revenue.period == "2025-12-31:FY"


# --------------------------------------------------------------------------
# Carril DEI (acciones en circulacion de portada) verificado contra el indice
# de filings. NO prueba: multi-clase por dimension (va por otro carril),
# formularios /A, ni el dedupe contra shares us-gaap con el mismo end.
# --------------------------------------------------------------------------


_DEI_ACCN = "0000000001-25-000009"


class _FakeSECConDei:
    payload = {"cik": 1, "facts": {"us-gaap": {}, "dei": {
        "EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"form": "10-Q", "end": "2025-10-24", "val": 15200000000,
             "filed": "2025-10-31", "accn": _DEI_ACCN},
        ]}}}}}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        return {}

    async def index_accessions(self, cik):
        return {_DEI_ACCN}


def test_refresh_from_sec_dei_verificado_entra_como_instante(db, monkeypatch):
    """Saldo de portada cuyo accn SI lista el indice: entra como
    shares_outstanding con periodo :DEI, sin anclaje fiscal (fiscal_year y
    fiscal_quarter NULL), con su filed exacto y el accession de procedencia."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECConDei)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    (fact,) = _facts(db, company, "shares_outstanding")
    assert fact.value == Decimal("15200000000")
    assert fact.period == "2025-10-24:DEI"
    assert fact.fiscal_year is None
    assert fact.fiscal_quarter is None
    assert fact.accession_number == _DEI_ACCN
    assert str(fact.filed) == "2025-10-31"


class _FakeSECDeiSinIndice(_FakeSECConDei):
    async def index_accessions(self, cik):
        raise ConnectionError("indice caido")


def test_refresh_from_sec_dei_sin_indice_fail_closed(db, monkeypatch):
    """Indice caido -> None -> NINGUN hecho de portada entra (regla de oro:
    OFICIAL solo si el indice lo verifica). El resto del refresh sigue."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECDeiSinIndice)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    assert _facts(db, company, "shares_outstanding") == []


class _FakeSECPayloadCambiado(_FakeSECEstable):
    """Mismo emisor, restatement: el valor anual cambia entre corridas."""

    valor = 5000000000

    async def company_facts(self, cik):
        payload = {"cik": 1, "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
                 "end": "2025-12-31", "val": self.valor, "filed": "2026-02-10",
                 "accn": "0000000001-25-000001"},
            ]}}}}}
        return payload


def test_refresh_from_sec_payload_cambiado_reingiere(db, monkeypatch):
    """Un payload DISTINTO no sale por el atajo unchanged: reingiere y el
    restatement machaca la cifra vieja (una sola fila, valor nuevo)."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECPayloadCambiado)
    company = _company(db)
    servicio = FinancialIngestionService()
    primero = asyncio.run(servicio.refresh_from_sec(db=db, company=company))
    assert primero["status"] == "ingested"
    # via monkeypatch: la clase queda restaurada al terminar el test.
    monkeypatch.setattr(_FakeSECPayloadCambiado, "valor", 5200000000)
    segundo = asyncio.run(servicio.refresh_from_sec(db=db, company=company))
    assert segundo["status"] == "ingested"
    assert segundo["facts_imported"] > 0
    (revenue,) = _facts(db, company, "revenue")
    assert revenue.value == Decimal("5200000000")


# --------------------------------------------------------------------------
# Plan B SEC: el ultimo filing anual que companyfacts no trae se lee de su
# propia instancia XBRL (caso real: 20-F de TSM 2025). XML sintetico con la
# forma de una instancia EDGAR; submissions doblado. NO prueba: la URL real
# de EDGAR, instancias con dimensiones ni traduccion de conveniencia.
# --------------------------------------------------------------------------


_PLANB_ACCN = "0000000001-26-000050"

_PLANB_XML = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <context id="c1">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period>
  </context>
  <unit id="u1"><measure>iso4217:USD</measure></unit>
  <us-gaap:Revenues contextRef="c1" unitRef="u1">9000000000</us-gaap:Revenues>
</xbrl>
"""


# Contador compartido (sin sombra por subclase): los tests lo resetean con
# monkeypatch.setitem, que restaura el valor al terminar.
_PLANB_LLAMADAS = {"n": 0}


class _FakeSECPlanB:
    """companyfacts no trae el 10-K de 2025 (sin hechos us-gaap); submissions
    lo lista con XBRL y la instancia se sirve doblada."""

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return {"cik": 1, "facts": {"us-gaap": {}}}

    async def annual_report_anchors(self, cik):
        return {_PLANB_ACCN: "2025-12-31"}

    async def submissions(self, cik):
        return {"filings": {"recent": {
            "form": ["10-K"],
            "accessionNumber": [_PLANB_ACCN],
            "filingDate": ["2026-02-10"],
            "reportDate": ["2025-12-31"],
            "primaryDocument": ["acme-20251231.htm"],
            "isXBRL": [1],
        }}}

    async def filing_document(self, url):
        _PLANB_LLAMADAS["n"] += 1
        return _PLANB_XML, "application/xml"


def test_refresh_from_sec_plan_b_lee_la_instancia_del_filing(db, monkeypatch):
    """El 10-K ausente de companyfacts se lee de su instancia XBRL: el
    revenue FY entra con valor y filed exactos y la procedencia queda en
    los metadatos del documento."""
    from app.models import Document

    monkeypatch.setitem(_PLANB_LLAMADAS, "n", 0)
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECPlanB)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    assert _PLANB_LLAMADAS["n"] == 1
    (revenue,) = _facts(db, company, "revenue")
    assert revenue.value == Decimal("9000000000")
    assert revenue.period == "2025-12-31:FY"
    assert str(revenue.filed) == "2026-02-10"
    document = db.get(Document, result["source_document_id"])
    instancia = (document.metadata_ or {}).get("sec_filing_instance")
    assert instancia["accession"] == _PLANB_ACCN
    assert instancia["facts_added"] == 1


class _FakeSECPlanBInnecesario(_FakeSECPlanB):
    """companyfacts YA trae el unico filing anual: Plan B no se dispara."""

    async def company_facts(self, cik):
        return {"cik": 1, "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
                 "end": "2025-12-31", "val": 9000000000, "filed": "2026-02-10",
                 "accn": _PLANB_ACCN},
            ]}}}}}


def test_refresh_from_sec_plan_b_no_se_dispara_si_ya_esta(db, monkeypatch):
    monkeypatch.setitem(_PLANB_LLAMADAS, "n", 0)
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECPlanBInnecesario)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    assert _PLANB_LLAMADAS["n"] == 0
    (revenue,) = _facts(db, company, "revenue")
    assert revenue.value == Decimal("9000000000")


# --------------------------------------------------------------------------
# Flujo trimestral SEC: trimestre directo (10-Q) etiquetado con la moda de
# cierre y Q derivado de acumulados YTD. Y dedupe DEI vs us-gaap con el
# mismo end. NO prueba: bancos, alias fusionados, ni el cap de 12 trimestres.
# --------------------------------------------------------------------------


class _FakeSECQuarterly:
    payload = {"cik": 1, "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"fy": 2026, "fp": "Q1", "form": "10-Q", "start": "2026-01-01",
             "end": "2026-03-31", "val": 1000, "filed": "2026-04-25",
             "accn": "0000000001-26-000010"},
            {"fy": 2026, "fp": "Q2", "form": "10-Q", "start": "2026-01-01",
             "end": "2026-06-30", "val": 2500, "filed": "2026-07-25",
             "accn": "0000000001-26-000011"},
        ]}}}}}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000001": "2025-12-31"}


def test_refresh_from_sec_trimestre_directo_y_derivado_de_ytd(db, monkeypatch):
    """Q1 directo de 10-Q queda '2026-03-31:Q1' (reportado, moda dic); Q2 no
    presentado se deriva del acumulado H1 - Q1 (1500) con is_reported False y
    el filed del acumulado mas reciente."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECQuarterly)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    revenues = {f.period: f for f in _facts(db, company, "revenue")}
    q1 = revenues["2026-03-31:Q1"]
    assert q1.value == Decimal("1000")
    assert q1.is_reported is True
    assert q1.fiscal_quarter == "Q1"
    assert str(q1.filed) == "2026-04-25"
    q2 = revenues["2026-06-30:Q2"]
    assert q2.value == Decimal("1500")
    assert q2.is_reported is False
    assert str(q2.filed) == "2026-07-25"


_DEDUPE_ACCN = "0000000001-26-000020"


class _FakeSECDedupeDei:
    payload = {"cik": 1, "facts": {
        "us-gaap": {
            "CommonStockSharesOutstanding": {"units": {"shares": [
                {"fy": 2025, "fp": "FY", "form": "10-K",
                 "end": "2025-12-31", "val": 100, "filed": "2026-02-10",
                 "accn": "0000000001-25-000001"},
            ]}},
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {"units": {"shares": [
                {"form": "10-K", "end": "2025-12-31", "val": 100,
                 "filed": "2026-02-10", "accn": _DEDUPE_ACCN},
            ]}},
        },
    }}

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return self.payload

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000001": "2025-12-31"}

    async def index_accessions(self, cik):
        return {_DEDUPE_ACCN}


def test_refresh_from_sec_dei_no_duplica_el_saldo_us_gaap(db, monkeypatch):
    """El concepto us-gaap ya informo el mismo saldo con el mismo end (mismo
    filing): la fila de portada DEI no se duplica; queda una sola, la FY."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECDedupeDei)
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_sec(db=db, company=company)
    )
    assert result["status"] == "ingested"
    shares = _facts(db, company, "shares_outstanding")
    assert len(shares) == 1
    assert shares[0].period == "2025-12-31:FY"
    assert shares[0].value == Decimal("100")
