"""Via edgartools: Form 4 y 13F con el MISMO shape que los servicios actuales.

Equivalencia de shape (contrato, no valores inventados):
- Form 4: claves de ``form4.parse_form4_xml`` (las que lee ``insider_service``).
- 13F: claves de ``form13f.parse_information_table`` (las que persiste
  ``manager_holding_ingestion_service``).
Hermetico: fixtures XML locales + DataFrames construidos a mano con las
columnas exactas de edgartools 5.59.1. Cero red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.services.connectors import form4 as form4_connector
from app.services.connectors import form13f as form13f_connector
from app.services.connectors.edgartools_ownership import (
    FORM4_TX_KEYS,
    enrich_like_insider_service,
    is_open_market_buy,
    ownership_transactions,
    transactions_from_edgartools_dataframe,
)
from app.services.connectors.edgartools_thirteenf import (
    THIRTEENF_ROW_KEYS,
    holdings_from_edgartools_dataframe,
    infotable_holdings,
)
from app.services.edgartools_ingestion_service import (
    refresh_13f_from_edgartools,
    refresh_form4_from_edgartools,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edgartools"
FORM4_XML = (FIXTURES / "filings" / "00012345670001" / "form4.xml").read_text(encoding="utf-8")
INFOTABLE_XML = (FIXTURES / "filings" / "00012345670001" / "infotable.xml").read_text(encoding="utf-8")
SUBMISSIONS = json.loads((FIXTURES / "submissions" / "CIK0001234567.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Guardian hermetico: cualquier intento de red falla el test."""
    import socket

    _real_connect = socket.socket.connect

    def _blocked(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        # Loopback permitido: asyncio (self-pipe en Windows) y SQLite no son red.
        if host in ("127.0.0.1", "::1", "localhost"):
            return _real_connect(self, address, *args, **kwargs)
        raise AssertionError(f"network access forbidden in hermetic edgartools tests ({host})")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_form4_xml_keeps_connector_shape_by_construction():
    parsed = ownership_transactions(FORM4_XML)
    assert tuple(parsed) == ("ticker", "issuer_name", "issuer_cik", "period_of_report", "reporters", "transactions")
    expected = form4_connector.parse_form4_xml(FORM4_XML)["transactions"]
    assert len(parsed["transactions"]) == 2 == len(expected)
    for tx, want in zip(parsed["transactions"], expected):
        assert tuple(tx) == FORM4_TX_KEYS == tuple(want)
        assert tx == want
        assert tx["alignment_10b5_1"] is None


def test_form4_values_match_fixture():
    txs = ownership_transactions(FORM4_XML)["transactions"]
    buy, sell = txs
    assert (buy["ticker"], buy["insider"]) == ("TSTEDG", "DOE JANE")
    assert (buy["type"], buy["acquired_disposed"]) == ("P", "A")
    assert (buy["shares"], buy["price"], buy["value"]) == (10000.0, 150.25, 1502500.0)
    assert buy["role"] == "officer (Chief Financial Officer)" and buy["is_officer"] is True
    assert buy["is_derivative"] is False and buy["date"] == "2024-06-10"
    assert (sell["type"], sell["acquired_disposed"], sell["shares"]) == ("S", "D", 2000.0)
    assert is_open_market_buy(buy) is True and is_open_market_buy(sell) is False
    assert form4_connector.is_open_market_buy(buy) == is_open_market_buy(buy)


def test_form4_dataframe_normalizes_to_same_keys():
    df = pd.DataFrame([
        {"Transaction Type": "Purchase", "Code": "P", "Description": "Open Market Purchase",
         "Shares": 10000, "Price": 150.25, "Value": 1502500.0, "Date": pd.Timestamp("2024-06-10"),
         "Form": "Form 4", "Issuer": "TEST EDGAR CORP", "Ticker": "TSTEDG",
         "Insider": "DOE JANE", "Position": "Chief Financial Officer", "Remaining Shares": 50000},
        {"Transaction Type": "Sale", "Code": "S", "Description": "Open Market Sale",
         "Shares": 2000, "Price": 151.0, "Value": 302000.0, "Date": pd.Timestamp("2024-06-11"),
         "Form": "Form 4", "Issuer": "TEST EDGAR CORP", "Ticker": "TSTEDG",
         "Insider": "DOE JANE", "Position": "Chief Financial Officer", "Remaining Shares": 48000},
    ])

    class _Ownership:
        def to_dataframe(self):
            return df

    parsed = ownership_transactions(_Ownership(), ticker="TSTEDG")
    assert len(parsed["transactions"]) == 2
    for tx in parsed["transactions"]:
        assert tuple(tx) == FORM4_TX_KEYS
        assert tx["alignment_10b5_1"] is None
        assert tx["rule_10b5_1"] is None
    buy, sell = parsed["transactions"]
    assert (buy["type"], buy["acquired_disposed"], buy["value"]) == ("P", "A", 1502500.0)
    assert (sell["type"], sell["acquired_disposed"]) == ("S", "D")
    assert buy["date"] == "2024-06-10" and buy["is_derivative"] is False

    direct = transactions_from_edgartools_dataframe(df, ticker="TSTEDG")
    assert [tuple(tx) for tx in direct["transactions"]] == [FORM4_TX_KEYS] * 2


def test_form4_enrichment_matches_insider_service_fields():
    txs = ownership_transactions(FORM4_XML)["transactions"]
    filing = {"accession_number": "0001234567-24-000007", "filing_date": "2024-06-15",
              "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000007/form4.xml",
              "form": "4", "ticker": "TSTEDG"}
    enriched = enrich_like_insider_service(txs, filing)
    first = enriched[0]
    assert (first["accession_number"], first["tx_line"]) == ("0001234567-24-000007", 0)
    assert enriched[1]["tx_line"] == 1
    assert first["source_url"] == filing["document_url"] and first["form"] == "4"
    assert first["filing_date"] == "2024-06-15"


def test_13f_xml_keeps_connector_shape_by_construction():
    rows = infotable_holdings(INFOTABLE_XML)
    expected = form13f_connector.parse_information_table(INFOTABLE_XML)
    assert len(rows) == 2 == len(expected)
    for row, want in zip(rows, expected):
        assert tuple(row) == THIRTEENF_ROW_KEYS == tuple(want)
        assert row == want


def test_13f_values_match_fixture():
    first, second = infotable_holdings(INFOTABLE_XML)
    assert first["name_of_issuer"] == "TEST EDGAR CORP" and first["cusip"] == "123456789"
    assert first["value_usd_thousands"] == "1500000" and first["ssh_prnamt"] == "10000"
    assert first["ssh_prnamt_type"] == "SH" and first["put_call"] is None
    assert (first["voting_sole"], first["voting_shared"], first["voting_none"]) == ("10000", "0", "0")
    assert second["put_call"] == "Call" and second["investment_discretion"] == "DFND"
    assert all(isinstance(value, str) or value is None for value in first.values())


def test_13f_dataframe_normalizes_to_same_keys_and_never_tickers():
    df = pd.DataFrame([
        {"Issuer": "TEST EDGAR CORP", "Class": "COM", "Cusip": "123456789", "Value": 1500000,
         "PutCall": "", "InvestmentDiscretion": "SOLE", "OtherManager": "",
         "SharesPrnAmount": 10000, "Type": "Shares",
         "SoleVoting": 10000, "SharedVoting": 0, "NonVoting": 0, "Ticker": "TSTEDG"},
    ])

    class _ThirteenF:
        def to_dataframe(self):
            return df

    rows = infotable_holdings(_ThirteenF())
    assert [tuple(row) for row in rows] == [THIRTEENF_ROW_KEYS]
    assert rows[0]["ssh_prnamt_type"] == "SH" and rows[0]["put_call"] is None
    assert "ticker" not in rows[0] and "Ticker" not in rows[0]

    direct = holdings_from_edgartools_dataframe(df)
    assert direct == rows


def test_service_form4_shape_matches_insider_pipeline():
    result = refresh_form4_from_edgartools(
        "TSTEDG", force=True, cik="0001234567", submissions=SUBMISSIONS,
        filing_xml={"0001234567-24-000007": FORM4_XML},
    )
    assert result["status"] == "ok" and result["transport"] == "snapshot"
    assert result["filings_scanned"] == 1 and len(result["transactions"]) == 2
    tx = result["transactions"][0]
    assert tuple(tx)[: len(FORM4_TX_KEYS)] == FORM4_TX_KEYS
    for extra in ("accession_number", "tx_line", "filing_date", "source_url", "form"):
        assert extra in tx
    assert tx["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/1234567/")
    assert result["provenance"]["source_kind"] == "official"


def test_service_13f_shape_matches_manager_pipeline():
    result = refresh_13f_from_edgartools(
        "0001234567", force=True, submissions=SUBMISSIONS,
        infotable_xml={"0001234567-24-000005": INFOTABLE_XML},
    )
    assert result["status"] == "ok" and result["transport"] == "snapshot"
    assert result["report_date"] == "2024-03-31"
    assert [tuple(row) for row in result["holdings"]] == [THIRTEENF_ROW_KEYS] * 2
    assert result["limitations"] and result["snapshot_synced_at"] is None
    assert result["provenance"]["source_kind"] == "official"



def test_form4_alignment_field_has_exact_position_and_unknown_dataframe_value():
    assert len(FORM4_TX_KEYS) == 24
    assert FORM4_TX_KEYS[19:] == (
        "security_title", "rule_10b5_1", "alignment_10b5_1", "shares_owned_after", "direct_indirect",
    )
    # Neither a provider hint nor a legacy flag is transaction XML evidence.
    frame = pd.DataFrame([{"Code": "S", "Transaction Type": "Sale", "Shares": 1,
                           "Price": 2, "rule_10b5_1": True, "alignment_10b5_1": True}])
    row = transactions_from_edgartools_dataframe(frame)["transactions"][0]
    assert tuple(row) == FORM4_TX_KEYS
    assert row["alignment_10b5_1"] is None and row["rule_10b5_1"] is None
