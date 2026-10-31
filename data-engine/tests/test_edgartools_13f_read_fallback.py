"""Fallback de lectura 13F: snapshot edgartools cuando no hay sync en vivo.

Contrato:
- Sin filas persistidas para el CIK, ``latest_holdings`` intenta el snapshot
  edgartools y, si responde ok, sirve status="snapshot" (nunca "ok": el
  snapshot no contrasta totales contra el filing) con el MISMO contrato de
  claves por holding que la via persistida.
- Con filas persistidas, el fallback NO se consulta.
- Si el snapshot no esta disponible (o la via esta apagada por kill switch),
  se devuelve el "unavailable" de siempre.
Hermetico: cero red (guardian de socket) y fixtures XML locales.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services import edgartools_ingestion_service
from app.services.edgartools_ingestion_service import refresh_13f_from_edgartools
from app.services.manager_holding_ingestion_service import (
    ManagerHoldingIngestionService,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edgartools"
SUBMISSIONS = json.loads((FIXTURES / "submissions" / "CIK0001234567.json").read_text(encoding="utf-8"))
INFOTABLE_XML = (FIXTURES / "filings" / "00012345670001" / "infotable.xml").read_text(encoding="utf-8")
CIK = "0001234567"

PERSISTED_ROW_KEYS = [
    "accession_number",
    "is_amendment",
    "name_of_issuer",
    "name_of_issuer_filed",
    "title_of_class",
    "cusip",
    "value_usd_thousands",
    "shares",
    "share_type",
    "put_call",
    "investment_discretion",
    "filing_url",
]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import socket

    _real_connect = socket.socket.connect

    def _blocked(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return _real_connect(self, address, *args, **kwargs)
        raise AssertionError(f"network access forbidden ({host})")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _real_snapshot_refresh(cik: str, **_kwargs):
    """La funcion real contra los fixtures, sin red ni flag."""
    return refresh_13f_from_edgartools(
        cik,
        force=True,
        submissions=SUBMISSIONS,
        infotable_xml={"0001234567-24-000005": INFOTABLE_XML},
    )


def test_latest_holdings_falls_back_to_snapshot_with_persisted_contract(db, monkeypatch):
    monkeypatch.setattr(
        edgartools_ingestion_service, "refresh_13f_from_edgartools", _real_snapshot_refresh
    )
    out = ManagerHoldingIngestionService().latest_holdings(db, cik=CIK)
    assert out["status"] == "snapshot"
    assert out["verification"] == "snapshot_unverified"
    assert out["transport"] == "snapshot"
    assert out["report_date"] == "2024-03-31"
    assert out["cik"] == CIK
    assert len(out["holdings"]) == 2
    for row in out["holdings"]:
        assert list(row.keys()) == PERSISTED_ROW_KEYS
    first = next(r for r in out["holdings"] if r["cusip"] == "123456789")
    assert first["name_of_issuer"] == "TEST EDGAR CORP"
    assert first["value_usd_thousands"] == 1500000.0
    assert first["shares"] == 10000.0
    assert first["accession_number"] is None
    assert first["filing_url"] is None


def test_latest_holdings_persisted_rows_skip_fallback(db, monkeypatch):
    def _forbidden(cik: str, **_kwargs):
        raise AssertionError("fallback must not run when persisted rows exist")

    monkeypatch.setattr(edgartools_ingestion_service, "refresh_13f_from_edgartools", _forbidden)

    from datetime import date, datetime

    from app.models.entities import FundManager, ManagerHolding

    manager = FundManager(cik=CIK, name="Fixture Manager", last_report_date=date(2024, 3, 31))
    manager.coverage = "ok"
    manager.synced_at = datetime(2024, 5, 1)
    db.add(manager)
    db.flush()
    db.add(
        ManagerHolding(
            manager_id=manager.id,
            report_date=date(2024, 3, 31),
            accession_number="0001234567-24-000005",
            is_amendment=False,
            name_of_issuer="APPLE INC",
            title_of_class="COM",
            cusip="037833100",
            value_usd_thousands=75000000,
            shares=300000000,
        )
    )
    db.commit()

    out = ManagerHoldingIngestionService().latest_holdings(db, cik=CIK)
    assert out["status"] == "ok"
    assert out["holdings"][0]["accession_number"] == "0001234567-24-000005"


def test_latest_holdings_unavailable_when_snapshot_missing(db, monkeypatch):
    def _unavailable(cik: str, **_kwargs):
        return {"cik": cik, "status": "unavailable", "holdings": []}

    monkeypatch.setattr(edgartools_ingestion_service, "refresh_13f_from_edgartools", _unavailable)
    out = ManagerHoldingIngestionService().latest_holdings(db, cik=CIK)
    assert out["status"] == "unavailable"
    assert out["holdings"] == []
    assert out["provenance"]["coverage"] == "unavailable"


def test_edgartools_enabled_default_is_on_with_kill_switch():
    from app.core.config import Settings

    assert Settings().edgartools_enabled is True
