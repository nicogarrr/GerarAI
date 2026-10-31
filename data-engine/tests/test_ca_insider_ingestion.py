"""Insiders Canada (Yahoo quoteSummary): mapping fail-closed e ingesta (grabado)."""

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, InsiderFiling, InsiderTransaction, Tenant
from app.services.ca_insider_ingestion import ingest_ca_insiders
from app.services.connectors.ca_insider_yahoo import (
    CA_TICKERS,
    SEDI_URL,
    map_transaction,
    map_transaction_code,
    yahoo_insider_url,
)

# Respuestas grabadas de quoteSummary?modules=insiderTransactions (20/10/2026).
RECORDED_BN = [
    {"maxAge": 1, "shares": {"raw": 675000, "fmt": "675k", "longFmt": "675,000"},
     "value": {"raw": 9061200, "fmt": "9.06M", "longFmt": "9,061,200"}, "filerUrl": "",
     "transactionText": "Exercise of options at price 13.42 per share.",
     "filerName": "Kingston (Brian William)", "filerRelation": "Senior Officer of Issuer",
     "moneyText": "", "startDate": {"raw": 1790726400, "fmt": "2026-09-30"}, "ownership": "D"},
]
RECORDED_KRKNF = [
    {"maxAge": 1, "shares": {"raw": 12000, "fmt": "12k", "longFmt": "12,000"},
     "value": {"raw": 53244, "fmt": "53.24k", "longFmt": "53,244"}, "filerUrl": "",
     "transactionText": "Acquisition in the public market at price 4.44 per share.",
     "filerName": "MacKay (Duane Joseph Alexander)", "filerRelation": "Senior Officer of Issuer",
     "moneyText": "", "startDate": {"raw": 1784073600, "fmt": "2026-07-15"}, "ownership": "D"},
    {"filerName": "", "transactionText": "", "startDate": {}},
]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.add_all([
            Company(id=1, ticker="BN", name="Brookfield Corporation", exchange="NYSE",
                    company_type="large_cap", valuation_model="dcf"),
            Company(id=2, ticker="KRKNF", name="Kraken Robotics", exchange="OTC",
                    company_type="small_cap", valuation_model="dcf"),
        ])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _ingest(db, monkeypatch):
    responses = {"BN": RECORDED_BN, "KRKNF": RECORDED_KRKNF}
    monkeypatch.setattr("app.services.ca_insider_ingestion.fetch_insider_transactions",
                        lambda symbol, client, crumb: responses[symbol])
    monkeypatch.setattr("app.services.ca_insider_ingestion.yahoo_session",
                        lambda client=None: (client, "crumb"))
    monkeypatch.setattr("app.services.ca_insider_ingestion.asyncio.sleep", _no_sleep)
    return asyncio.run(ingest_ca_insiders(db, 1, client=None, crumb="crumb"))


async def _no_sleep(*a, **k):
    return None


def test_map_transaction_code_fail_closed():
    assert map_transaction_code("Exercise of options at price 13.42 per share.") is None
    assert map_transaction_code("Acquisition in the public market at price 4.44 per share.") == "P"
    assert map_transaction_code("Disposition in the public market") == "S"
    assert map_transaction_code("Grant of deferred share units") is None
    assert map_transaction_code("Conversion and sale of shares") is None
    assert map_transaction_code(None) is None and map_transaction_code("") is None


def test_map_transaction_never_declares_currency():
    mapped = map_transaction("KRKNF", RECORDED_KRKNF[0])
    assert mapped["code"] == "P" and mapped["price"] == 4.44
    assert mapped["currency"] is None  # Yahoo no la declara: N/D, nunca CAD/USD asumido
    assert mapped["shares"] == 12000.0 and mapped["source_url"] == yahoo_insider_url("KRKNF")
    assert map_transaction("BN", RECORDED_KRKNF[1]) is None  # incompleto: sin dato con causa


def test_ingest_saves_once_with_unofficial_label(db, monkeypatch):
    result = _ingest(db, monkeypatch)
    assert result["saved"] == 2  # exercise de BN tambien se guarda: code=None, no senal
    assert result["tickers"]["KRKNF"]["received"] == 2 and result["skipped_incomplete"] == 1
    tx = db.scalar(select(InsiderTransaction).where(InsiderTransaction.issuer_ticker == "KRKNF"))
    assert tx.code == "P" and tx.form == "CA-INSIDER"
    assert tx.data_quality["unofficial"] is True and tx.data_quality["official_source"] == SEDI_URL
    assert tx.data_quality["currency"] is None
    filing = db.scalar(select(InsiderFiling).where(InsiderFiling.id == tx.filing_id))
    assert filing.form == "CA-INSIDER" and filing.source_url == yahoo_insider_url("KRKNF")
    assert tx.source_url == filing.source_url
    bn_tx = db.scalar(select(InsiderTransaction).where(InsiderTransaction.issuer_ticker == "BN"))
    assert bn_tx.code is None  # exercise de opciones: guardado pero no senal de compra
    assert _ingest(db, monkeypatch)["saved"] == 0  # idempotente


def test_missing_company_is_reported_not_invented(db, monkeypatch):
    monkeypatch.setattr("app.services.ca_insider_ingestion.CA_TICKERS", {"BN": "BN", "OTRO": "OTRO"})
    result = _ingest(db, monkeypatch)
    assert result["missing_companies"] == ["OTRO"]


def test_ca_tickers_match_plan():
    assert set(CA_TICKERS) == {"BN", "KRKNF"}


def test_actor_and_scheduler(monkeypatch):
    from app.workers import dramatiq_app
    from app.workers import scheduler as scheduler_module

    async def fake_ingest(db, tenant, **kw):
        return {"saved": 1, "tickers": {"BN": {"received": 1, "saved": 1}}}

    class _Db:
        info = {"tenant_id": 1}

        def close(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: _Db())
    monkeypatch.setattr("app.services.ca_insider_ingestion.ingest_ca_insiders", fake_ingest)
    result = dramatiq_app.ingest_ca_insider_yahoo(tenant_id=1, user_id="owner")
    assert result["status"] == "ok" and result["saved"] == 1
    job = scheduler_module.build_scheduler().get_job("ca_insider_yahoo")
    assert job is not None and job.trigger.interval.total_seconds() == 21600


def test_feed_and_operations_keep_ca_out_of_usd_sums(db, monkeypatch):
    """CA-INSIDER entra en el feed con currency None; NUNCA en la suma USD de operations."""
    from app.models import InsiderFiling
    from app.services import insider_operations
    from app.services.insider_feed import _tx_dict
    from tests.test_insider_operations import _seed_portfolio_and_watchlist

    _seed_portfolio_and_watchlist(db)
    _ingest(db, monkeypatch)
    tx = db.scalar(select(InsiderTransaction).where(InsiderTransaction.form == "CA-INSIDER"))
    filing = db.scalar(select(InsiderFiling).where(InsiderFiling.id == tx.filing_id))
    assert _tx_dict(tx, filing, 1)["currency"] is None
    ops = insider_operations.insider_operations(db, days=365)
    # Aunque KRKNF/BN estuvieran seguidos, sus movimientos CA-INSIDER no
    # entran en el agregado (solo Form 4): nada que sumar en USD.
    assert all(c["ticker"] not in {"KRKNF", "BN"} for c in ops.get("companies", []))


def test_build_feed_final_contract_keeps_ca_out_of_usd_totals_and_signals(db, monkeypatch):
    from app.services.insider_feed import build_feed

    _ingest(db, monkeypatch)
    feed = build_feed(db, days=365, today=date(2026, 10, 20))
    assert feed["count"] == 1
    tx = feed["transactions"][0]
    assert tx["ticker"] == "KRKNF" and tx["form"] == "CA-INSIDER"
    assert "currency" in tx and tx["currency"] is None
    assert tx["value"] == 53244.0
    assert tx["source_url"] == yahoo_insider_url("KRKNF")
    assert feed["totals"]["buy_value"] == 0
    assert feed["totals"]["sell_value"] == 0
    assert feed["c_suite_buys"] == feed["clusters"] == feed["big_buys"] == []

    # Even a large CEO acquisition cannot become a USD signal or total.
    stored = db.scalar(select(InsiderTransaction).where(InsiderTransaction.code == "P"))
    stored.value = 2_000_000
    stored.role = "CEO"
    stored.officer_title = "Chief Executive Officer"
    db.commit()
    feed = build_feed(db, days=365, today=date(2026, 10, 20))
    assert feed["totals"]["buy_value"] == 0
    assert feed["c_suite_buys"] == feed["clusters"] == feed["big_buys"] == []


def test_desktop_and_mobile_preserve_source_and_missing_currency_labels():
    root = Path(__file__).resolve().parents[2]
    source = (root / "components/insider/InsiderFeed.tsx").read_text(encoding="utf-8")
    desktop = source.split("<table", 1)[1].split("</table>", 1)[0]
    mobile = source.split("function OperationCard", 1)[1].split("export", 1)[0]
    for layout in (desktop, mobile):
        assert "tx.form === 'CA-INSIDER'" in layout
        assert "insider.feed.canadaBadge" in layout
        assert "tx.source_url" in layout
        assert "Divisa no informada" in layout or "insider.feed.currencyMissing" in layout
    assert "insider.feed.totalsNote" in source

    # Las cadenas visibles viven en i18n: la semántica debe sobrevivir allí.
    feed = json.loads((root / "lib/i18n/messages/es/insider.json").read_text(encoding="utf-8"))["feed"]
    assert "fuente no oficial (Yahoo)" in feed["canadaBadge"]
    assert feed["currencyMissing"] == "Divisa no informada"
    assert "Totales y señales: solo Form 4" in feed["totalsNote"]
