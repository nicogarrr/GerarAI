"""WaccInputService contract tests.

WACC assumptions are valuation-critical inputs: the service must attach
dated, sourced risk-free observations from FRED, persist the policy
premiums with explicit lower confidence, stay idempotent across
refreshes, and honestly report which WACC inputs remain missing.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import wacc_input_service
from app.services.wacc_input_service import WaccInputService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _StubFred:
    """Stands in for FREDClient: configured flag + canned series payload."""

    observations = [{"date": "2026-09-21", "value": "4.25"}]
    csv_observations: list[dict] = []

    def __init__(self, configured: bool = True):
        self._configured = configured

    async def series_csv(self, series_id, limit=10):
        # Sin clave, el stub simula fredgraph.csv inalcanzable/vacio:
        # el estado honesto es "sin dato", nunca un valor inventado.
        return {"observations": list(self.csv_observations)}

    def configured(self) -> bool:
        return self._configured

    async def series(self, series_id: str, limit: int = 10) -> dict:
        return {"observations": list(self.observations)}


def _patch_no_yfinance(monkeypatch):
    """Sin red: los tests existentes no esperan inputs de mercado."""

    async def _empty(self, ticker):
        return {}

    monkeypatch.setattr(WaccInputService, "_yfinance_market_inputs", _empty)

    async def _no_damodaran(self, as_of):
        return None

    # Sin red: el ERP queda en el valor de settings (ver test_damodaran_erp.py).
    monkeypatch.setattr(WaccInputService, "_damodaran_implied_erp", _no_damodaran)


def _patch_fred(monkeypatch, stub):
    monkeypatch.setattr(
        wacc_input_service, "FREDClient", lambda *args, **kwargs: stub
    )


def _run(coro):
    return asyncio.run(coro)


def test_refresh_stores_sourced_risk_free_and_policy_facts(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    result = _run(WaccInputService().refresh(db, company))

    assert result["status"] == "refreshed"
    assert result["ticker"] == "AAPL"
    assert result["currency"] == "USD"

    risk_free = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    )
    assert risk_free is not None
    # FRED yields percent; the service stores the decimal rate.
    assert risk_free.value == Decimal("0.0425")
    assert risk_free.period == "2026-09-21"
    assert risk_free.source_type == "FRED"
    assert risk_free.confidence == Decimal("0.98")
    assert risk_free.source_id is not None

    for metric in ("equity_risk_premium", "country_risk_premium"):
        fact = db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
            )
        )
        assert fact is not None, metric
        assert fact.source_type == "wacc_policy"
        assert fact.confidence == Decimal("0.70")

    # FRED document carries the series + date provenance.
    fred_doc = db.scalar(
        select(Document).where(
            Document.company_id == company.id, Document.source_type == "FRED"
        )
    )
    assert fred_doc is not None
    assert fred_doc.metadata_["date"] == "2026-09-21"

    # beta and market_cap were never ingested: reported missing, never filled.
    assert set(result["missing"]) == {"beta", "market_cap"}
    assert sorted(result["source_document_ids"]) == result["source_document_ids"]


def _crp_fact(db, company):
    return db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "country_risk_premium",
        )
    )


def _policy_doc(db, company):
    return db.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.source_type == "wacc_policy",
        )
    )


def test_crp_comes_from_damodaran_table_for_spanish_company(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    company.domicile_country = "ES"
    db.commit()
    _run(WaccInputService().refresh(db, company))

    crp = _crp_fact(db, company)
    assert crp is not None
    assert crp.value == Decimal("0.0155")
    assert crp.source_type == "wacc_policy"
    doc = _policy_doc(db, company)
    assert doc.metadata_["country"] == "ES"
    assert doc.metadata_["country_risk_premium_source"] == "damodaran_ctryprem"
    reference = doc.metadata_["country_risk_premium_reference"]
    assert reference["vintage"] == "2026-01-05"
    assert reference["source_url"].startswith("https://pages.stern.nyu.edu/")


def test_crp_resolves_country_from_isin_prefix(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    asml = _company(db)
    asml.ticker = "ASML"
    asml.exchange = "EURONEXT AMSTERDAM"
    asml.currency = "EUR"
    asml.isin = "NL0010273215"
    db.commit()
    _run(WaccInputService().refresh(db, asml))

    crp = _crp_fact(db, asml)
    assert crp is not None
    assert crp.value == Decimal("0.0")
    doc = _policy_doc(db, asml)
    assert doc.metadata_["country"] == "NL"
    assert doc.metadata_["country_risk_premium_source"] == "damodaran_ctryprem"


def test_crp_falls_back_to_settings_default_without_country(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    _run(WaccInputService().refresh(db, company))

    crp = _crp_fact(db, company)
    assert crp is not None
    doc = _policy_doc(db, company)
    assert doc.metadata_["country_risk_premium_source"] == "settings_default"
    assert "country_risk_premium_reference" not in doc.metadata_


def test_refresh_without_fred_key_and_empty_csv_keeps_honest_missing_state(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=False))
    company = _company(db)
    result = _run(WaccInputService().refresh(db, company))

    assert db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    ) is None
    # Policy premiums still land, sourced by the wacc_policy document.
    assert db.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.source_type == "wacc_policy",
        )
    ) == 2
    assert "risk_free_rate" in result["missing"]


def test_refresh_is_idempotent_across_runs(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    first = _run(WaccInputService().refresh(db, company))
    second = _run(WaccInputService().refresh(db, company))

    assert db.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(FinancialFact.company_id == company.id)
    ) == 3
    assert db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.company_id == company.id)
    ) == 2
    assert first["fact_ids"] == second["fact_ids"]


def test_refresh_skips_unparseable_fred_values(db, monkeypatch):
    _patch_no_yfinance(monkeypatch)
    stub = _StubFred(configured=True)
    stub.observations = [
        {"date": "2026-09-22", "value": "."},  # FRED's missing-value marker
        {"date": "2026-09-21", "value": "not-a-number"},
    ]
    _patch_fred(monkeypatch, stub)
    company = _company(db)
    result = _run(WaccInputService().refresh(db, company))

    # Every observation was unusable: no risk-free fact, no FRED document.
    assert db.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    ) == 0
    assert db.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.company_id == company.id, Document.source_type == "FRED"
        )
    ) == 0
    assert "risk_free_rate" in result["missing"]


def test_decimal_parses_numbers_and_rejects_garbage():
    service = WaccInputService()
    assert service._decimal("4.25") == Decimal("4.25")
    assert service._decimal(0.0433) == Decimal("0.0433")
    assert service._decimal("not-a-number") is None
    assert service._decimal(None) is None


def test_series_csv_parses_public_fredgraph_payload():
    """fredgraph.csv (sin clave): mismo shape que la API, mas reciente primero."""
    from app.services.connectors.fred import FREDClient

    class _CsvResp:
        text = "DATE,DGS10\n2026-09-21,4.20\n2026-09-22,4.25\n2026-09-23,.\n"

        def raise_for_status(self):
            return None

    class _Client:
        async def get(self, url, headers=None):
            assert "fredgraph.csv?id=DGS10" in url
            return _CsvResp()

    payload = asyncio.run(FREDClient(client=_Client()).series_csv("DGS10", limit=10))
    observations = payload["observations"]
    assert observations[0] == {"date": "2026-09-23", "value": "."}
    assert observations[-1] == {"date": "2026-09-21", "value": "4.20"}


def test_refresh_without_key_uses_csv_fallback(db, monkeypatch):
    """Sin FRED_API_KEY, la via publica CSV alimenta risk_free_rate igualmente."""

    class _CsvFred:
        def configured(self):
            return False

        async def series_csv(self, series_id, limit=10):
            return {"observations": [{"date": "2026-09-23", "value": "4.25"}]}

    _patch_no_yfinance(monkeypatch)
    monkeypatch.setattr(wacc_input_service, "FREDClient", lambda: _CsvFred())
    company = _company(db)
    result = _run(WaccInputService().refresh(db, company))
    assert "risk_free_rate" not in result["missing"]
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    )
    assert fact is not None and fact.value == Decimal("0.0425")


def test_refresh_stores_yfinance_beta_and_market_cap(db, monkeypatch):
    """Beta y market_cap de Yahoo se persisten con fuente declarada."""

    async def _market(self, ticker):
        assert ticker == "AAPL"
        return {"beta": Decimal("1.24"), "market_cap": Decimal("3000000000000")}

    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    monkeypatch.setattr(WaccInputService, "_yfinance_market_inputs", _market)
    company = _company(db)
    result = _run(WaccInputService().refresh(db, company))
    assert result["missing"] == []
    for metric, expected in [("beta", "1.24"), ("market_cap", "3000000000000")]:
        fact = db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
            )
        )
        assert fact is not None
        assert fact.value == Decimal(expected)
        assert fact.source_type == "yfinance"


def test_yahoo_symbol_adds_mc_suffix_for_spanish_exchanges():
    bme = Company(ticker="TEF", exchange="BME")
    bolsa = Company(ticker="SAN", exchange="BOLSA DE MADRID")
    assert WaccInputService._yahoo_symbol(bme) == "TEF.MC"
    assert WaccInputService._yahoo_symbol(bolsa) == "SAN.MC"


def test_yahoo_symbol_adds_as_suffix_for_euronext_amsterdam():
    asml = Company(ticker="ASML", exchange="EURONEXT AMSTERDAM")
    finnhub = Company(ticker="ASML", exchange="NYSE EURONEXT - AMSTERDAM")
    assert WaccInputService._yahoo_symbol(asml) == "ASML.AS"
    assert WaccInputService._yahoo_symbol(finnhub) == "ASML.AS"


def test_yahoo_symbol_keeps_us_and_already_suffixed_tickers():
    us = Company(ticker="AAPL", exchange="NASDAQ NMS - GLOBAL MARKET")
    already = Company(ticker="TEF.MC", exchange="BME")
    unknown = Company(ticker="XYZ", exchange=None)
    assert WaccInputService._yahoo_symbol(us) == "AAPL"
    assert WaccInputService._yahoo_symbol(already) == "TEF.MC"
    assert WaccInputService._yahoo_symbol(unknown) == "XYZ"


def test_non_usd_company_does_not_get_us_treasury_risk_free(db, monkeypatch):
    """EUR: nunca DGS10 (bono USD); la libre de riesgo es el Bund aleman,
    benchmark sin default del euro, con la serie declarada."""
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    company.currency = "EUR"
    db.commit()
    result = _run(WaccInputService().refresh(db, company))

    assert result["risk_free_unavailable_for_currency"] is None
    assert "risk_free_rate" not in result["missing"]
    risk_free = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    )
    assert risk_free is not None
    fred_doc = db.scalar(
        select(Document).where(
            Document.company_id == company.id, Document.source_type == "FRED"
        )
    )
    assert fred_doc.metadata_["series"] == "IRLTLT01DEM156N"
    assert fred_doc.metadata_["currency"] == "EUR"


def test_eur_company_gets_bund_risk_free(db, monkeypatch):
    """EUR: la libre de riesgo es el Bund aleman (IRLTLT01DEM156N), no
    DGS10 ni un proxy inventado; la serie queda declarada en el documento."""
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    company.currency = "EUR"
    db.commit()
    result = _run(WaccInputService().refresh(db, company))

    risk_free = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    )
    assert risk_free is not None
    assert risk_free.value == Decimal("0.0425")
    doc = db.scalar(
        select(Document).where(
            Document.company_id == company.id, Document.source_type == "FRED"
        )
    )
    assert doc.metadata_["series"] == "IRLTLT01DEM156N"
    assert doc.metadata_["currency"] == "EUR"
    assert "risk_free_rate" not in result["missing"]
    assert result["risk_free_unavailable_for_currency"] is None


def test_unsupported_currency_keeps_honest_missing(db, monkeypatch):
    """GBP (sin rail configurado): sin hecho, declarado no disponible."""
    _patch_no_yfinance(monkeypatch)
    _patch_fred(monkeypatch, _StubFred(configured=True))
    company = _company(db)
    company.currency = "GBP"
    db.commit()
    result = _run(WaccInputService().refresh(db, company))

    assert db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "risk_free_rate",
        )
    ) is None
    assert "risk_free_rate" in result["missing"]
    assert result["risk_free_unavailable_for_currency"] == "GBP"


def test_upsert_refreshes_legacy_monetary_unit_without_new_row(db):
    company = _company(db)
    source = Document(company_id=company.id, title="Yahoo dated market inputs", source_type="yfinance")
    db.add(source)
    db.flush()
    service = WaccInputService()
    legacy = service._upsert_fact(db, company, metric="market_cap", value=Decimal("11492166656"),
        period="2026-09-25", source=source, source_type="yfinance", confidence=Decimal("0.75"))
    assert legacy.unit == "decimal"
    original_id = legacy.id
    refreshed = service._upsert_fact(db, company, metric="market_cap", value=Decimal("11492166656"),
        period="2026-09-25", source=source, source_type="yfinance", confidence=Decimal("0.75"), unit="EUR")
    db.flush()
    assert refreshed.id == original_id
    assert refreshed.unit == "EUR"
    assert refreshed.value == Decimal("11492166656")
    assert refreshed.source_id == source.id
    assert db.scalar(select(func.count()).select_from(FinancialFact).where(FinancialFact.metric == "market_cap")) == 1
