"""Cobertura de ramas de class_filer_eps_service: salidas tempranas y bordes
que las suites de comportamiento no ejercitan (fetch reales via opener
endurecido, sin instancia, sin hechos, portada, suma no positiva).

Sin red: los fetchers son fakes y el opener se sustituye por uno capturado.
Cada test afirma el comportamiento de la rama, no solo la ejecuta.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, FinancialFact, Tenant
from app.services import class_filer_eps_service as svc


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, Company.__table__, Document.__table__, FinancialFact.__table__],
    )
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "META", cik: str | None = "0001") -> Company:
    row = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="operating",
        valuation_model="standard_dcf", cik=cik,
    )
    db.add(row)
    db.flush()
    return row


class _FakeResponse:
    def __init__(self, data: bytes, encoding: str | None = None):
        self._data = data
        self.headers = {}
        if encoding:
            self.headers["Content-Encoding"] = encoding

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _capture_opener(monkeypatch, payload: bytes, encoding: str | None = None):
    calls = []

    def fake_open(request, timeout):
        calls.append((request, timeout))
        return _FakeResponse(payload, encoding)

    monkeypatch.setattr(svc._OPENER, "open", fake_open)
    return calls


def test_fetch_json_y_bytes_abren_con_el_opener_endurecido(monkeypatch):
    payload = json.dumps({"ok": True}).encode()
    calls = _capture_opener(monkeypatch, payload)
    assert svc._fetch_json("https://data.sec.gov/x") == {"ok": True}
    assert svc._fetch_bytes("https://www.sec.gov/y") == payload
    # Los timeouts del servicio (30s JSON, 60s binario) y la URL pedida.
    assert [timeout for _, timeout in calls] == [30, 60]
    assert [request.full_url for request, _ in calls] == [
        "https://data.sec.gov/x",
        "https://www.sec.gov/y",
    ]


def test_fetch_bytes_descomprime_gzip(monkeypatch):
    raw = b"contenido-edgar"
    _capture_opener(monkeypatch, gzip.compress(raw), encoding="gzip")
    assert svc._fetch_bytes("https://www.sec.gov/x") == raw


def _submissions(forms, accessions):
    return {"filings": {"recent": {"form": forms, "accessionNumber": accessions}}}


def test_10k_url_none_sin_formulario_10k():
    # Solo 10-Q: la rama `form != "10-K"` continua y agota el bucle.
    fetch_json = lambda url: _submissions(["10-Q"], ["0001-25-000001"])  # noqa: E731
    assert svc._latest_10k_instance_url("1", fetch_json) is None


def test_10k_url_none_sin_instancia_htm_en_el_indice():
    def fetch_json(url):
        if "submissions" in url:
            return _submissions(["10-K"], ["0001-25-000001"])
        return {"directory": {"item": [{"name": "informe.htm"}, {"name": "notas.xml"}]}}

    assert svc._latest_10k_instance_url("1", fetch_json) is None


def test_eps_backfill_sin_instancia_no_escribe_nada(db):
    company = _company(db)
    fetch_json = lambda url: _submissions([], [])  # noqa: E731
    result = svc.backfill_class_based_eps(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=lambda url: b""
    )
    assert result.skipped_reason == "sin instancia 10-K"
    assert result.facts_written == 0 and result.member_used is None
    assert db.query(FinancialFact).count() == 0


def test_eps_backfill_sin_hechos_dimensionados_no_escribe_nada(db):
    company = _company(db)

    def fetch_json(url):
        if "submissions" in url:
            return _submissions(["10-K"], ["0001-25-000001"])
        return {"directory": {"item": [{"name": "x-20250930_htm.xml"}]}}

    empty_xbrl = b'<?xml version="1.0"?><xbrl xmlns="http://www.xbrl.org/2003/instance"></xbrl>'
    result = svc.backfill_class_based_eps(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=lambda url: empty_xbrl
    )
    assert result.skipped_reason == "sin hechos dimensionados"
    assert result.facts_written == 0
    assert db.query(FinancialFact).count() == 0


def test_class_cover_candidates_excluye_portada_fresca_y_sin_cik(db):
    stale = _company(db, "ASTALE", "0002")
    fresh = _company(db, "BFRESH", "0003")
    _company(db, "CNOSIN", None)  # sin CIK: nunca candidata
    _company(db, "DSINHECHOS", "0004")
    db.add(FinancialFact(
        company_id=fresh.id, metric="shares_outstanding", value=Decimal("100"),
        unit="shares", period="2026-11-01:DEI", fiscal_year=2026,
        fiscal_quarter="Q4", source_type="SEC", is_reported=True,
    ))
    db.add(FinancialFact(
        company_id=stale.id, metric="shares_outstanding", value=Decimal("100"),
        unit="shares", period="2020-01-01:DEI", fiscal_year=2019,
        fiscal_quarter="Q4", source_type="SEC", is_reported=True,
    ))
    db.flush()
    tickers = [c.ticker for c in svc.class_cover_candidates(db, today=date(2026, 11, 18))]
    # Orden por ticker; BFRESH (portada al dia) y CNOSIN (sin CIK) fuera.
    assert tickers == ["ASTALE", "DSINHECHOS"]


def test_latest_instance_url_none_sin_formulario_listado():
    fetch_json = lambda url: _submissions(["8-K"], ["0001-25-000001"])  # noqa: E731
    assert svc._latest_instance_url("1", fetch_json) is None


def test_latest_instance_url_none_sin_htm_en_el_indice():
    def fetch_json(url):
        if "submissions" in url:
            return _submissions(["10-Q"], ["0001-25-000001"])
        return {"directory": {"item": [{"name": "q3.htm"}]}}

    assert svc._latest_instance_url("1", fetch_json) is None


def test_shares_backfill_sin_instancia_no_escribe_nada(db):
    company = _company(db)
    fetch_json = lambda url: _submissions([], [])  # noqa: E731
    result = svc.backfill_class_shares_outstanding(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=lambda url: b""
    )
    assert result.skipped_reason == "sin instancia 10-K/10-Q"
    assert db.query(FinancialFact).count() == 0


ECSO_CERO_XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:dei="http://xbrl.sec.gov/dei/2023" xmlns:m="http://www.example.com/m">
  <unit id="ushares"><measure>xbrli:shares</measure></unit>
  <context id="iA"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="m:StatementClassOfStockAxis">m:ClassACommonStockMember</explicitMember></segment></entity>
    <period><instant>2025-10-24</instant></period></context>
  <context id="iB"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="m:StatementClassOfStockAxis">m:ClassBCommonStockMember</explicitMember></segment></entity>
    <period><instant>2025-10-24</instant></period></context>
  <dei:EntityCommonStockSharesOutstanding contextRef="iA" unitRef="ushares">0</dei:EntityCommonStockSharesOutstanding>
  <dei:EntityCommonStockSharesOutstanding contextRef="iB" unitRef="ushares">0</dei:EntityCommonStockSharesOutstanding>
</xbrl>
"""


def test_shares_backfill_suma_no_positiva_no_escribe_nada(db):
    company = _company(db, "META")

    def fetch_json(url):
        if "submissions" in url:
            return _submissions(["10-K"], ["0001-25-000001"])
        return {"directory": {"item": [{"name": "x-20250930_htm.xml"}]}}

    result = svc.backfill_class_shares_outstanding(
        db, company, cik="1", fetch_json=fetch_json,
        fetch_bytes=lambda url: ECSO_CERO_XML.encode(),
    )
    # Una suma de clases en cero es un dato roto: se senala, no se publica.
    assert result.skipped_reason == "suma de clases no positiva"
    assert db.query(FinancialFact).count() == 0
