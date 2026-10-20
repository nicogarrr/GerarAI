"""Conector PDMR UK (tracefour): mapping, divisa e ingesta (respuestas grabadas)."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, InsiderFiling, InsiderTransaction, Tenant
from app.services.connectors.uk_pdmr_tracefour import map_entry, map_transaction_code, normalize_price
from app.services.uk_pdmr_ingestion import ingest_uk_pdmr

# Respuesta grabada de GET https://tracefour.com/v1/eu/uk (20/10/2026),
# reducida a tres movimientos reales + uno de la empresa seguida (CGEO.L).
RECORDED = {
    "data": [
        {
            "filingId": "cgeo-1|1",
            "publicationAt": "2026-10-19T15:53:00Z",
            "issuerName": "CGEO HOLDINGS",
            "pdmrName": "Jane Director",
            "capacity": "CEO",
            "transactionNature": "Acquisition of shares",
            "isin": "GB00CGEO0001",
            "transactionDate": "2026-10-18",
            "volume": 1000,
            "pricePerShare": 152.0125,
            "currency": "GBP",
            "totalValue": 152012.5,
            "rawArtefactUrl": "https://data.fca.org.uk/artefacts/NSM/RNS/cgeo-1.html",
            "valueUnknown": False,
        },
        {
            "filingId": "pence-1|1",
            "publicationAt": "2026-10-19T06:00:08Z",
            "issuerName": "PENNYSAVER PLC",
            "pdmrName": "John Seller",
            "capacity": "CFO",
            "transactionNature": "Disposal of shares",
            "isin": "GB00CGEO0001",
            "transactionDate": "2026-10-15",
            "volume": 5567,
            "pricePerShare": 890,
            "currency": "GBX",
            "totalValue": 4954630,
            "rawArtefactUrl": "https://data.fca.org.uk/artefacts/NSM/RNS/pence-1.html",
            "valueUnknown": False,
        },
        {
            "filingId": "otra-1|1",
            "publicationAt": "2026-10-16T17:00:00Z",
            "issuerName": "TESCO PLC",
            "pdmrName": "Emma Taylor",
            "capacity": "Chief People Officer",
            "transactionNature": "Sale of Ordinary shares",
            "isin": "GB00BLGZ9862",
            "transactionDate": "2026-10-15",
            "volume": 141116,
            "pricePerShare": 5.326514,
            "currency": "GBP",
            "totalValue": 751656.35,
            "rawArtefactUrl": "https://data.fca.org.uk/artefacts/NSM/RNS/otra-1.html",
            "valueUnknown": False,
        },
        {"filingId": "", "isin": ""},
    ]
}


class FakeClient:
    def __init__(self):
        self.get = AsyncMock(return_value=FakeResponse())


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return RECORDED


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.add(
            Company(
                id=1,
                ticker="CGEO.L",
                name="CGEO",
                exchange="LSE",
                company_type="small_cap",
                valuation_model="dcf",
                isin="GB00CGEO0001",
            )
        )
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_transaction_code_mapping():
    assert map_transaction_code("Acquisition of shares") == "P"
    assert map_transaction_code("Disposal of shares") == "S"
    assert map_transaction_code("Sale of Ordinary shares") == "S"
    assert map_transaction_code("Something unclear") is None
    assert map_transaction_code(None) is None


def test_price_currency_never_assumed():
    assert normalize_price(152.0125, "GBP") == (152.0125, "GBP", False)
    assert normalize_price(890, "GBX") == (8.9, "GBP", True)
    assert normalize_price(None, "GBP") == (None, "GBP", False)
    assert normalize_price(10.0, None) == (10.0, None, False)


def test_map_entry_requires_identity():
    assert map_entry({"filingId": "", "isin": ""}) is None
    entry = map_entry(RECORDED["data"][0])
    assert entry["code"] == "P" and entry["currency"] == "GBP"
    assert entry["source_url"].startswith("https://data.fca.org.uk/")


def test_ingest_saves_known_isin_once_with_currency(db):
    first = asyncio.run(ingest_uk_pdmr(db, 1, client=FakeClient()))
    assert first["received"] == 4
    assert first["saved"] == 2  # los dos de CGEO.L; TESCO no esta en companies
    assert first["skipped_unknown_isin"] == 1 and first["skipped_incomplete"] == 1
    filing = db.scalar(select(InsiderFiling).where(InsiderFiling.accession_number == "cgeo-1|1"))
    assert filing.form == "PDMR" and filing.issuer_ticker == "CGEO.L"
    assert filing.filing_date == "2026-10-19"
    assert filing.source_url == "https://data.fca.org.uk/artefacts/NSM/RNS/cgeo-1.html"
    tx = db.scalar(select(InsiderTransaction).where(InsiderTransaction.accession_number == "pence-1|1"))
    assert tx.code == "S" and tx.price == 8.9
    assert tx.data_quality["currency"] == "GBP" and tx.data_quality["price_from_pence"] is True
    assert tx.data_quality["source"] == "tracefour" and tx.data_quality["licence"] == "CC BY 4.0"
    # Idempotente: la segunda pasada no duplica.
    second = asyncio.run(ingest_uk_pdmr(db, 1, client=FakeClient()))
    assert second["saved"] == 0 and second["skipped_known"] == 2
    assert len(list(db.scalars(select(InsiderTransaction)))) == 2


def test_scheduler_registers_uk_pdmr_job():
    from app.workers import scheduler as scheduler_module

    job = scheduler_module.build_scheduler().get_job("uk_pdmr_filings")
    assert job is not None and job.trigger.interval.total_seconds() == 21600


def test_actor_runs_and_reports(monkeypatch):
    from app.workers import dramatiq_app

    async def fake_ingest(db, tenant, **kw):
        return {
            "received": 3,
            "saved": 2,
            "skipped_known": 0,
            "skipped_unknown_isin": 1,
            "skipped_incomplete": 0,
        }

    class _Db:
        info = {"tenant_id": 1}

        def close(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: _Db())
    monkeypatch.setattr("app.services.uk_pdmr_ingestion.ingest_uk_pdmr", fake_ingest)
    result = dramatiq_app.ingest_uk_pdmr_filings(tenant_id=1, user_id="owner")
    assert result["status"] == "ok" and result["saved"] == 2


def test_transaction_code_fail_closed_with_real_feed_cases():
    """Casos REALES del feed tracefour (20/10/2026): flujos mecanicos nunca son senal."""
    real_cases = {
        "Purchase of Ordinary Shares": "P",
        "Purchase of Ordinary Shares with Dividend Proceeds": None,
        "Direct subscription for new ordinary shares in Softcat plc": None,
        "Subscription for Placing Shares": None,
        "Purchase - Equity Issue Subscription": None,
        "Sale and purchase (Bed & ISA": None,
        "Sale of ordinary shares of 5 pence each as part of a 'bed & ISA' transfer between own accounts": None,
        "Sale of shares Purchase of shares into ISA": None,
        "Purchase and sale of shares by Robert Ware and sale of shares by Deborah Ware": None,
        "Participation in Tender Offer (sale of shares) and Share Capital Restructuring": None,
        "Non-discretionary purchase of shares through the Bunzl Employee Stock Purchase Plan (U.S": None,
        "SALE OF 10,000 SHARES UNDER EMPLOYEE STOCK PURCHASE PLAN AT GBP 46.15383 PER SHARE": None,
        "Acquisition of notional ADS within Ms Martinez-Davis's GSK Executive Supplemental Savings Plan account": None,
        "Acquisition of Shares/units via the DCSP": None,
        "Disposal of shares": "S",
        "Open market sale": "S",
        "APURCHASE OF 350,000 ORDINARY SHARES OF £0.01 EACH IN GREENCORE GROUP PLC": "P",
        "On 30 September 2026, Wendy Sarah Shapland, spouse of Darren Shapland, purchased 10,000 ordinary shares of the Company at a price of 574.864 pence per share": "P",
        "Market sale of 150,000 Ordinary Shares of 0.02p each": "S",
    }
    for nature, expected in real_cases.items():
        assert map_transaction_code(nature) == expected, nature


def test_gbx_value_never_divided_unverified():
    """GBX sin verificar: el precio se convierte con marca, totalValue NO se divide."""
    entry = {
        "filingId": "gbx-1|1", "publicationAt": "2026-10-19T06:00:08Z",
        "issuerName": "PENNYSAVER PLC", "pdmrName": "John Seller", "capacity": "CFO",
        "transactionNature": "Disposal of shares", "isin": "GB00CGEO0001",
        "transactionDate": "2026-10-15", "volume": 5567, "pricePerShare": 890,
        "currency": "GBX", "totalValue": 4954630,
        "rawArtefactUrl": "https://data.fca.org.uk/artefacts/NSM/RNS/gbx-1.html",
        "valueUnknown": False,
    }
    mapped = map_entry(entry)
    assert mapped["price"] == 8.9 and mapped["price_from_pence"] is True
    assert mapped["value"] is None and mapped["value_raw"] == 4954630
    assert mapped["value_unknown"] is True


def _client_with(entries):
    from unittest.mock import AsyncMock as AM

    return type("C", (), {"get": AM(return_value=type(
        "R", (), {"status_code": 200, "raise_for_status": lambda self: None,
                  "json": lambda self: {"data": entries}})())})()


_NO_CURRENCY_ENTRY = {
    "filingId": "nocur-1|1", "publicationAt": "2026-10-19T06:00:08Z",
    "issuerName": "CGEO HOLDINGS", "pdmrName": "Jane Director", "capacity": "CEO",
    "transactionNature": "Acquisition of shares", "isin": "GB00CGEO0001",
    "transactionDate": "2026-10-18", "volume": 100, "pricePerShare": 1.5,
    "currency": None, "totalValue": 150.0,
    "rawArtefactUrl": "https://data.fca.org.uk/artefacts/NSM/RNS/nocur-1.html",
    "valueUnknown": False,
}


def test_ingest_keeps_missing_currency_as_none(db):
    """Sin divisa informada (93/307 en el feed real): None, nunca USD/GBP asumido."""
    assert asyncio.run(ingest_uk_pdmr(db, 1, client=_client_with([_NO_CURRENCY_ENTRY])))["saved"] == 1
    tx = db.scalar(select(InsiderTransaction).where(InsiderTransaction.accession_number == "nocur-1|1"))
    assert tx.data_quality["currency"] is None


def test_feed_currency_defaults_only_for_form4(db):
    """_tx_dict: USD solo en Form 4/4A; PDMR sin divisa queda None."""
    from app.models import InsiderFiling
    from app.services.insider_feed import _tx_dict

    assert asyncio.run(ingest_uk_pdmr(db, 1, client=_client_with([_NO_CURRENCY_ENTRY])))["saved"] == 1
    tx = db.scalar(select(InsiderTransaction).where(InsiderTransaction.accession_number == "nocur-1|1"))
    filing = db.scalar(select(InsiderFiling).where(InsiderFiling.accession_number == "nocur-1|1"))
    assert _tx_dict(tx, filing, 1)["currency"] is None
    tx.form = "4"
    assert _tx_dict(tx, filing, 1)["currency"] == "USD"
