"""Fundamentales para emisores UE/UK fuera del IBEX revisado (caso BFIT.AS, nov 2026).

Prod, 2026-11-03: Basic-Fit N.V. (BFIT.AS, Euronext Amsterdam) entra en la
watchlist con 255 precios y 0 hechos; la siembra falla con «Sin snapshot ESEF
local» y la reserva Yahoo solo cubre el mapa revisado. Estos tests prueban,
sin red (MockTransport con la forma real de GLEIF y filings.xbrl.org medida
ese dia), que:

- el ISIN -> LEI (GLEIF) -> filings ESEF del emisor da hechos OFICIALES
  (source_type ESEF) por la misma ruta de mapeo que el IBEX, con la divisa de
  presentacion del filing (SEK para un emisor sueco, no EUR fijo);
- un ISIN de la ficha distinto del usado para el LEI bloquea la escritura;
- sin SEC ni ESEF, los estados completos de Yahoo entran como UNA SOLA
  FUENTE NO OFICIAL (titulo propio, metadata single_source, nota), con las
  guardas del modo huecos (nombre real, divisa declarada);
- la tesis y la siembra recorren ese orden y lo dejan en la cadena;
- el stub de un listado revisado nace con ISIN, bolsa y divisa.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import esef_live
from app.services import financial_ingestion_service as ingestion
from app.services import yahoo_fundamentals_service as yfs
from app.services.connectors import esef as esef_connector
from app.services.financial_ingestion_service import FinancialIngestionService

LEI = "724500HUXGTQC07CAZ61"
ISIN = "NL0011872650"
SE_LEI = "5493000SEKSEKSEK0001"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(esef_connector, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: None)


def _company(db, ticker="BFIT.AS", name="BASIC-FIT NV", **kw):
    company = Company(
        ticker=ticker, name=name, exchange=kw.pop("exchange", "UNKNOWN"),
        currency=kw.pop("currency", "EUR"), sector="S", industry="I",
        company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[], **kw,
    )
    db.add(company)
    db.commit()
    return company


def _fact(concept, value, period, unit="iso4217:EUR", lei=LEI):
    return {"value": str(value), "decimals": -5, "dimensions": {
        "concept": concept, "entity": f"http://standards.iso.org/iso/17442:{lei}",
        "period": period, "unit": unit,
    }}


def _year(y):
    return f"{y}-01-01T00:00:00/{y + 1}-01-01T00:00:00"


def _inst(y):
    return f"{y + 1}-01-01T00:00:00"


def _bfit_doc(year, *, revenue_concept, unit="iso4217:EUR", lei=LEI):
    rev = {2025: 1420500000, 2024: 1215200000}[year]
    facts = {
        "f1": _fact(revenue_concept, rev, _year(year), unit, lei),
        "f2": _fact("ifrs-full:ProfitLoss", {2025: 14300000, 2024: 8000000}[year], _year(year), unit, lei),
        "f3": _fact("ifrs-full:CashAndCashEquivalents", {2025: 115000000, 2024: 56700000}[year], _inst(year), unit, lei),
        "f4": _fact("ifrs-full:CashFlowsFromUsedInOperatingActivities", {2025: 647400000, 2024: 581800000}[year], _year(year), unit, lei),
        "f5": _fact("ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                    {2025: 278000000, 2024: 334900000}[year], _year(year), unit, lei),
        "f6": _fact("ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
                    {2025: 294200000, 2024: 1600000}[year], _inst(year), unit, lei),
        "f7": _fact("ifrs-full:LongtermBorrowings", {2025: 932600000, 2024: 993200000}[year], _inst(year), unit, lei),
        # Desglose por segmento: nunca es el consolidado.
        "f8": {"value": "1", "dimensions": {
            "concept": revenue_concept, "entity": f"x:{lei}", "period": _year(year), "unit": unit,
            "ifrs-full:SegmentsAxis": "bas:BeneluxMember",
        }},
    }
    return {"documentInfo": {}, "facts": facts}


def _filing_row(lei, year, country="NL"):
    path = f"/{lei}/{year}-12-31/ESEF/{country}/0/{lei}-{year}-12-31-en.json"
    return {"type": "filing", "id": str(year), "attributes": {
        "fxo_id": f"{lei}-{year}-12-31-ESEF-{country}-0", "country": country,
        "period_end": f"{year}-12-31", "json_url": path, "package_url": None,
        "sha256": f"sha{year}", "error_count": 0, "warning_count": 0,
    }}


def _handler(*, lei=LEI, legal="Basic-Fit N.V.", country="NL", unit="iso4217:EUR",
             isin_hits=None, fulltext_hits=None, calls=None):
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if "api.gleif.org" in url:
            params = dict(request.url.params)
            if "filter[isin]" in params:
                hits = isin_hits if isin_hits is not None else [(lei, legal, country)]
            else:
                hits = fulltext_hits if fulltext_hits is not None else [(lei, legal, country)]
            data = [{"type": "lei-records", "id": h[0], "attributes": {
                "lei": h[0], "entity": {"legalName": {"name": h[1]}, "jurisdiction": h[2]},
                "registration": {"status": "ISSUED"}}} for h in hits]
            return httpx.Response(200, json={"data": data})
        if url.endswith(f"/api/entities/{lei}/filings") or f"/api/entities/{lei}/filings?" in url:
            rows = [_filing_row(lei, 2024, country), _filing_row(lei, 2025, country)]
            return httpx.Response(200, json={"data": rows, "meta": {"count": 2}})
        if "/api/entities/" in url and url.split("?")[0].endswith("/filings"):
            return httpx.Response(404, json={"errors": [{"status": "404"}]})
        if url.split("?")[0].endswith(f"/api/entities/{lei}"):
            return httpx.Response(200, json={"data": {"attributes": {"identifier": lei, "name": legal}}})
        if url.endswith(".json"):
            year = 2025 if "2025-12-31" in url else 2024
            concept = "ifrs-full:RevenueFromContractsWithCustomers" if year == 2025 else "ifrs-full:Revenue"
            return httpx.Response(200, content=json.dumps(_bfit_doc(year, revenue_concept=concept, unit=unit, lei=lei)))
        return httpx.Response(404, json={"errors": [{"status": "404"}]})
    return handle


def _patch_live(monkeypatch, **kw):
    transport = httpx.MockTransport(_handler(**kw))
    real = esef_live.fetch_live_snapshot

    async def fake(company, **_):
        http = httpx.AsyncClient(transport=transport)
        esef = esef_connector.EsefClient(client=httpx.AsyncClient(
            transport=transport, base_url=esef_connector.ESEF_BASE_URL))
        return await real(company, esef=esef, http=http)

    monkeypatch.setattr(esef_live, "fetch_live_snapshot", fake)
    monkeypatch.setattr(esef_live, "live_lookup_enabled", lambda: True)


def _facts(db, company):
    return {(f.metric, f.fiscal_year): f for f in db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id))}


# -- ESEF en vivo ------------------------------------------------------------


def test_bfit_sin_snapshot_local_obtiene_hechos_oficiales_por_isin_lei(db, monkeypatch):
    _patch_live(monkeypatch)
    company = _company(db)  # ficha real de prod: ISIN vacio, bolsa UNKNOWN
    result = asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    assert result["provider"] == "ESEF" and result["lei"] == LEI
    facts = _facts(db, company)
    # FY2025 solo trae RevenueFromContractsWithCustomers: ahora cuenta.
    assert facts[("revenue", 2025)].value == Decimal("1420500000")
    assert facts[("revenue", 2024)].value == Decimal("1215200000")
    assert facts[("revenue", 2025)].source_type == "ESEF" and facts[("revenue", 2025)].is_reported
    assert facts[("revenue", 2025)].unit == "EUR"
    # Deuda financiera desde los prestamos (sin arrendamientos): derivada, no reportada.
    debt = facts[("total_debt", 2025)]
    assert debt.value == Decimal("1226800000") and debt.is_reported is False
    assert facts[("free_cash_flow", 2025)].value == Decimal("369400000")
    doc = db.get(Document, result["source_document_id"])
    assert doc.metadata_["origin"] == "live"
    assert doc.metadata_["identity"]["method"] == "isin_gleif"
    assert doc.metadata_["identity"]["isin"] == ISIN  # del listado revisado de BFIT.AS
    assert doc.metadata_["reporting_currency"] == "EUR"


def test_emisor_sueco_se_guarda_en_sek_no_en_eur(db, monkeypatch):
    _patch_live(monkeypatch, lei=SE_LEI, legal="Exempel AB", country="SE", unit="iso4217:SEK")
    company = _company(db, ticker="EXEM.ST", name="Exempel AB", currency="SEK", isin="SE0000000001")
    asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    facts = _facts(db, company)
    assert facts[("revenue", 2025)].unit == "SEK"
    assert facts[("total_debt", 2025)].unit == "SEK"
    assert facts[("free_cash_flow", 2025)].unit == "SEK"


def test_isin_de_la_ficha_distinto_no_escribe_hechos(db, monkeypatch):
    _patch_live(monkeypatch)
    company = _company(db)
    monkeypatch.setattr(esef_live, "_company_isin", lambda c: ISIN)
    company.isin = "NL0000000000"
    db.commit()
    with pytest.raises(RuntimeError, match="company_mismatch"):
        asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    assert not _facts(db, company)


def test_sin_isin_por_nombre_ambiguo_no_elige(db, monkeypatch):
    other = "391200N6BT0BQ6FQL860"
    calls: list[str] = []
    transport = httpx.MockTransport(_handler(
        fulltext_hits=[(LEI, "Basic-Fit N.V.", "NL"), (other, "Basic Fit N.V. Holding", "NL")], calls=calls))

    def handler2(request):
        if f"/api/entities/{other}/filings" in str(request.url):
            return httpx.Response(200, json={"data": [_filing_row(other, 2025)], "meta": {"count": 1}})
        return transport.handle_request(request)

    t2 = httpx.MockTransport(handler2)
    company = _company(db, ticker="BFX.AS", name="Basic-Fit NV")
    esef = esef_connector.EsefClient(client=httpx.AsyncClient(transport=t2, base_url=esef_connector.ESEF_BASE_URL))
    snap, reason = asyncio.run(esef_live.fetch_live_snapshot(
        company, esef=esef, http=httpx.AsyncClient(transport=t2)))
    assert snap is None and reason.startswith("nombre_ambiguo")


def test_ficha_solo_con_ticker_y_sin_isin_no_busca_por_nombre(db):
    company = _company(db, ticker="ZZZ.PA", name="ZZZ.PA")
    t = httpx.MockTransport(lambda r: httpx.Response(500))
    esef = esef_connector.EsefClient(client=httpx.AsyncClient(transport=t, base_url=esef_connector.ESEF_BASE_URL))
    snap, reason = asyncio.run(esef_live.fetch_live_snapshot(company, esef=esef, http=httpx.AsyncClient(transport=t)))
    assert snap is None and reason.startswith("sin_isin_ni_nombre")


def test_sin_interruptor_el_error_sigue_siendo_honesto(db, monkeypatch):
    monkeypatch.setattr(esef_live, "live_lookup_enabled", lambda: False)
    company = _company(db)
    with pytest.raises(RuntimeError, match="Sin snapshot ESEF local"):
        asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))


# -- Yahoo completo, una sola fuente no oficial -------------------------------

Y25, Y24 = pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")


def _yahoo(name="SAP SE", fin_ccy: str | None = "EUR"):
    def fetch(symbol):
        income = pd.DataFrame({Y25: [34_176e6, 7_300e6, 1_170e6], Y24: [34_176e6 * 0.9, 3_150e6, 1_168e6]},
                              index=["Total Revenue", "Net Income", "Diluted Average Shares"])
        balance = pd.DataFrame({Y25: [9_000e6, 7_000e6], Y24: [10_000e6, 9_600e6]},
                               index=["Cash And Cash Equivalents", "Total Debt"])
        cash = pd.DataFrame({Y25: [7_000e6, -900e6, 6_100e6], Y24: [5_000e6, -800e6, 4_200e6]},
                            index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"])
        return {"name": name, "currency": fin_ccy or "EUR", "financial_currency": fin_ccy,
                "income": income, "balance": balance, "cashflow": cash}
    return fetch


def test_yahoo_completo_etiquetado_una_sola_fuente_no_oficial(db):
    company = _company(db, ticker="SAP.DE", name="SAP SE", exchange="XETRA")
    result = yfs.refresh_full_from_yahoo(db, company, fetcher=_yahoo())
    assert result["single_source"] is True
    assert result["note"] == "una sola fuente, no oficial (Yahoo Finance)"
    facts = _facts(db, company)
    rev = facts[("revenue", 2025)]
    assert rev.source_type == "YAHOO_FUNDAMENTALS" and rev.is_reported is False
    assert rev.unit == "EUR"
    assert facts[("free_cash_flow", 2025)].value == Decimal("6100000000")
    doc = db.get(Document, result["source_document_id"])
    assert doc.title.startswith(yfs.FULL_TITLE_PREFIX)
    assert doc.metadata_["single_source"] is True and doc.metadata_["official"] is False
    assert doc.metadata_["mode"] == "full_unreviewed"
    assert "una sola fuente, no oficial" in doc.metadata_["note"]


def test_yahoo_completo_rechaza_nombre_placeholder_y_divisa_sin_declarar(db):
    stub = _company(db, ticker="SAP.DE", name="SAP.DE", exchange="XETRA")
    with pytest.raises(RuntimeError, match="company_mismatch"):
        yfs.refresh_full_from_yahoo(db, stub, fetcher=_yahoo())
    other = _company(db, ticker="SIE.DE", name="Siemens AG", exchange="XETRA")
    with pytest.raises(RuntimeError, match="company_mismatch"):
        yfs.refresh_full_from_yahoo(db, other, fetcher=_yahoo(name="SAP SE"))
    third = _company(db, ticker="ALV.DE", name="Allianz SE", exchange="XETRA")
    with pytest.raises(RuntimeError, match="currency_unknown"):
        yfs.refresh_full_from_yahoo(db, third, fetcher=_yahoo(name="Allianz SE", fin_ccy=None))
    assert not _facts(db, stub) and not _facts(db, other) and not _facts(db, third)


def test_yahoo_completo_usa_la_divisa_de_los_estados_no_la_de_cotizacion(db):
    company = _company(db, ticker="CGX.L", name="Georgia Example PLC", currency="GBX", exchange="LSE")
    yfs.refresh_full_from_yahoo(db, company, fetcher=_yahoo(name="Georgia Example PLC", fin_ccy="GEL"))
    assert _facts(db, company)[("revenue", 2025)].unit == "GEL"


# -- Tesis y siembra recorren el orden ----------------------------------------

SEC_PENDING = {"status": "pending", "source": "SEC EDGAR companyfacts", "detail": "Sin CIK"}


def test_tesis_emisor_ue_sin_snapshot_usa_esef_en_vivo(db, monkeypatch):
    from app.services.fundamentals_fallback import ESEF_LIVE_LABEL, ingest_with_fallback

    _patch_live(monkeypatch)
    company = _company(db)
    block = ingest_with_fallback(db, company, dict(SEC_PENDING))
    assert block["status"] == "ok" and block["official"] is True
    assert block["source"] == ESEF_LIVE_LABEL and block["lei"] == LEI
    assert [link["source"] for link in block["fallback_chain"]][-1] == ESEF_LIVE_LABEL
    assert _facts(db, company)[("revenue", 2025)].source_type == "ESEF"


def test_tesis_sin_esef_cae_a_yahoo_completo_etiquetado(db, monkeypatch):
    from app.services import fundamentals_fallback as ff

    monkeypatch.setattr(esef_live, "live_lookup_enabled", lambda: True)

    async def no_esef(company, **_):
        return None, "sin_emisor_esef: ningun LEI con filings"

    monkeypatch.setattr(esef_live, "fetch_live_snapshot", no_esef)
    monkeypatch.setattr(yfs, "_fetch_yahoo", _yahoo())
    company = _company(db, ticker="SAP.DE", name="SAP SE", exchange="XETRA")
    block = ff.ingest_with_fallback(db, company, dict(SEC_PENDING))
    assert block["status"] == "ok" and block["official"] is False
    assert block["single_source"] is True and "una sola fuente, no oficial" in block["note"]
    chain = {link["source"]: link["status"] for link in block["fallback_chain"]}
    assert chain[ff.ESEF_LIVE_LABEL] == "error" and chain[ff.YAHOO_FULL_LABEL] == "ok"
    assert _facts(db, company)[("revenue", 2025)].source_type == "YAHOO_FUNDAMENTALS"


def test_tesis_emisor_sec_con_fallo_no_rellena_con_yahoo(db, monkeypatch):
    from app.services.fundamentals_fallback import ingest_with_fallback

    monkeypatch.setattr(esef_live, "live_lookup_enabled", lambda: True)
    monkeypatch.setattr(yfs, "_fetch_yahoo", _yahoo(name="Apple Inc"))
    company = _company(db, ticker="AAPL", name="Apple Inc", cik="0000320193", currency="USD")
    block = ingest_with_fallback(db, company, dict(SEC_PENDING))
    assert block["status"] == "pending" and not _facts(db, company)


def test_siembra_cascada_esef_y_luego_yahoo(db, monkeypatch):
    from app.services.fundamentals_seed_service import seed_company_fundamentals

    monkeypatch.setattr(esef_live, "live_lookup_enabled", lambda: True)

    async def no_esef(company, **_):
        return None, "sin_emisor_esef"

    monkeypatch.setattr(esef_live, "fetch_live_snapshot", no_esef)
    monkeypatch.setattr(yfs, "_fetch_yahoo", _yahoo())
    monkeypatch.setattr("app.services.fundamentals_fallback.fill_bridge_gaps", lambda db, c: {"status": "test"})
    company = _company(db, ticker="SAP.DE", name="SAP SE", exchange="XETRA")
    result = seed_company_fundamentals(db, company)
    assert result["status"] == "sembrado" and result["via"] == "yahoo_no_oficial"
    vias = [(a["via"], a["status"]) for a in result["intentos"]]
    assert vias[0] == ("esef", "error") and vias[-1] == ("yahoo_no_oficial", "ok")


def test_siembra_bfit_entra_por_esef_en_vivo(db, monkeypatch):
    from app.services.fundamentals_seed_service import seed_company_fundamentals

    _patch_live(monkeypatch)
    monkeypatch.setattr("app.services.fundamentals_fallback.fill_bridge_gaps", lambda db, c: {"status": "test"})
    company = _company(db)
    result = seed_company_fundamentals(db, company)
    assert result["status"] == "sembrado" and result["via"] == "esef"
    assert _facts(db, company)[("revenue", 2025)].source_type == "ESEF"


# -- Stub con identidad del listado revisado ----------------------------------


def test_stub_de_listado_revisado_nace_con_isin_bolsa_y_divisa(db, monkeypatch):
    from app.services import company_enrichment_service as ces

    monkeypatch.setattr(ces.CompanyEnrichmentService, "enrich", lambda self, db, c: None)
    monkeypatch.setattr("app.seed.apply_master_taxonomy_to_stubs", lambda db: None)
    company = ces.ensure_company_stub(db, "bfit.as")
    assert (company.isin, company.exchange, company.currency) == (ISIN, "EURONEXT AMSTERDAM", "EUR")
    assert company.name == "Basic-Fit N.V."


def test_ficha_existente_con_huecos_se_completa_sin_pisar(db, monkeypatch):
    from app.services import company_enrichment_service as ces

    company = _company(db)  # como prod: ISIN vacio, UNKNOWN, EUR
    ces.ensure_company_stub(db, "BFIT.AS")
    assert (company.isin, company.exchange) == (ISIN, "EURONEXT AMSTERDAM")
    usd = _company(db, ticker="BFIT", name="BFIT", currency="USD")
    ces.ensure_company_stub(db, "BFIT")
    assert usd.isin is None and usd.exchange == "UNKNOWN"


def test_ficha_homonima_con_el_isin_de_otro_listado_no_recibe_hechos(db, monkeypatch):
    """Prod: «BFIT» (USD, UNKNOWN) lleva el ISIN de Basic-Fit; sus hechos van a BFIT.AS."""
    _patch_live(monkeypatch)
    company = _company(db, ticker="BFIT", name="BFIT", currency="USD", isin=ISIN)
    with pytest.raises(RuntimeError, match="listado_distinto"):
        asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    assert not _facts(db, company)
