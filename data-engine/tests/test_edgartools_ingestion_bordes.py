"""edgartools_ingestion_service: flag, gates, payload de snapshot, degradacion
live y aristas de Form 4. Hermetico: guardian de red como en
test_edgartools_offline.py; las funciones de ``client`` (manifest, lecturas de
snapshot, salud) y los parsers de facts/ownership se doblan por monkeypatch.

SQLite real en memoria para el camino que persiste (refresh con exito live).

No se prueba aqui: parseo real de facts/ownership/13F (cubierto en
test_edgartools_facts.py, test_edgartools_ownership.py y
test_edgartools_13f_read_fallback.py), throttle/breaker reales
(test_edgartools_offline.py) ni la libreria edgar real (sin red).
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.edgartools_ingestion_service as eis
from app.models.entities import Base, Company, Document
from app.services.connectors import edgartools_client as client
from app.services.financial_ingestion_service import BANK_REVENUE_TICKERS


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Guardian hermetico: marca los intentos de red no-loopback.

    Ojo: la degradacion del servicio puede absorber el AssertionError, asi
    que NO es un contador externo de cero intentos de red.
    """
    _real_connect = socket.socket.connect

    def _blocked(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return _real_connect(self, address, *args, **kwargs)
        raise AssertionError(f"network access forbidden ({host})")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(autouse=True)
def _identidad_doblada(monkeypatch):
    """refresh llama client.ensure_identity(): si fuera real ejecutaria
    edgar.set_identity y cambiaria EDGAR_IDENTITY global sin restaurarlo.
    Doblada: devuelve una identidad fija y monkeypatch restaura el wrapper."""
    monkeypatch.setattr(
        client, "ensure_identity", lambda: "GerarAI research contact@gerarai.local"
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


def _company(db, ticker="TSTEDG"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Semiconductors", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


# -- Flag y gates -----------------------------------------------------------------


def test_is_enabled_segun_settings(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(edgartools_enabled=False),
    )
    assert eis.is_enabled() is False
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(edgartools_enabled=True),
    )
    assert eis.is_enabled() is True


def test_disabled_payload():
    out = eis._disabled("aapl")
    assert out["status"] == "disabled"
    assert out["ticker"] == "AAPL"
    assert "EDGARTOOLS_ENABLED=false" in out["reason"]


def test_is_bank_like_reglas():
    assert eis._is_bank_like(SimpleNamespace(industry="Capital Markets", ticker="X")) is True
    assert eis._is_bank_like(SimpleNamespace(industry="Regional Banks", ticker="Y")) is True
    ticker_banca = sorted(BANK_REVENUE_TICKERS)[0]
    assert eis._is_bank_like(SimpleNamespace(industry="Software", ticker=ticker_banca)) is True
    assert eis._is_bank_like(SimpleNamespace(industry="Software", ticker="MSFT")) is False
    assert eis._is_bank_like(SimpleNamespace(industry=None, ticker=None)) is False


def test_tenant_filter_ambas_rutas(db):
    db.info.pop("tenant_id", None)
    expr_sin = eis._tenant_filter(db, Document)
    assert "IS NULL" in str(expr_sin.compile(compile_kwargs={"literal_binds": True}))
    db.info["tenant_id"] = 42
    expr_con = eis._tenant_filter(db, Document)
    assert "tenant_id = 42" in str(expr_con.compile(compile_kwargs={"literal_binds": True}))


def test_fetch_live_entity_facts_devuelve_facts_y_cik(monkeypatch):
    import edgar

    sentinel = object()
    llamadas = {}

    class _EdgarCompanyFalsa:
        def __init__(self, key):
            llamadas["key"] = key
            self.cik = "320193"

        def get_facts(self):
            return sentinel

    monkeypatch.setattr(edgar, "Company", _EdgarCompanyFalsa)
    monkeypatch.setattr(client, "throttle_sync", lambda: llamadas.setdefault("throttle", True))
    facts, cik = eis._fetch_live_entity_facts("TSTEDG")
    assert facts is sentinel
    assert cik == "0000320193"
    assert llamadas == {"key": "TSTEDG", "throttle": True}


# -- Snapshot payloads -------------------------------------------------------------


def test_snapshot_payloads_ramas(monkeypatch):
    monkeypatch.setattr(client, "manifest_cik", lambda ticker, root=None: None)
    assert eis._snapshot_payloads("X") == (None, None, None, None)

    monkeypatch.setattr(client, "manifest_cik", lambda ticker, root=None: "0000320193")
    monkeypatch.setattr(client, "read_companyfacts", lambda cik, root=None: None)
    assert eis._snapshot_payloads("X") == (None, None, None, None)

    facts = {"facts": {}}
    subs = {"filings": {"recent": {}}}
    monkeypatch.setattr(client, "read_companyfacts", lambda cik, root=None: facts)
    monkeypatch.setattr(client, "read_submissions", lambda cik, root=None: subs)
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: "2026-01-01T00:00:00Z")
    assert eis._snapshot_payloads("X") == ("0000320193", facts, subs, "2026-01-01T00:00:00Z")


# -- refresh: degradaciones ---------------------------------------------------------


def _sin_snapshot(monkeypatch):
    monkeypatch.setattr(client, "manifest_cik", lambda ticker, root=None: None)
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)


def test_refresh_sin_instalar_degrada_a_unavailable(db, monkeypatch):
    company = _company(db)
    _sin_snapshot(monkeypatch)
    monkeypatch.setattr(client, "is_installed", lambda: False)
    out = eis.refresh_from_edgartools(db, company, force=True)
    assert out["status"] == "unavailable"
    assert out["reason"] == "edgartools no instalado y sin snapshot local para TSTEDG"
    assert out["transport"] == "snapshot"
    assert out["snapshot_synced_at"] is None


def test_refresh_live_error_desconocido_degrada(db, monkeypatch):
    company = _company(db)
    _sin_snapshot(monkeypatch)
    monkeypatch.setattr(client, "is_installed", lambda: True)
    salud = []
    monkeypatch.setattr(client, "report_sec_failure_to_health", lambda status: salud.append(status))

    def _live_que_falla(cik_o_ticker):
        raise RuntimeError("boom sin codigo")

    monkeypatch.setattr(eis, "_fetch_live_entity_facts", _live_que_falla)
    out = eis.refresh_from_edgartools(db, company, force=True)
    assert out["status"] == "unavailable"
    assert out["reason"] == (
        "live no disponible (RuntimeError); snapshot: sin snapshot local para TSTEDG"
    )
    assert salud == [None]


# -- refresh: exito live y companyfacts inyectados -----------------------------------


def _breaker_espia():
    return SimpleNamespace(
        record_success=lambda: None,
        record_429=lambda: None,
    )


def test_refresh_live_exito_registra_salud_y_usa_anchors(db, monkeypatch):
    company = _company(db)
    _sin_snapshot(monkeypatch)
    monkeypatch.setattr(client, "is_installed", lambda: True)
    breaker = _breaker_espia()
    llamadas = {"record_success": 0, "salud_ok": 0}
    breaker.record_success = lambda: llamadas.__setitem__("record_success", llamadas["record_success"] + 1)
    monkeypatch.setattr(client, "default_breaker", lambda: breaker)
    monkeypatch.setattr(
        client, "report_sec_success_to_health",
        lambda: llamadas.__setitem__("salud_ok", llamadas["salud_ok"] + 1),
    )
    sentinel_facts = object()
    monkeypatch.setattr(
        eis, "_fetch_live_entity_facts", lambda cik_o_ticker: (sentinel_facts, "0000320193")
    )
    subs = {"filings": {"recent": {}}}
    captura = {}
    def _anchors(s):
        captura["anchors_in"] = s
        return {"FY2025": "2025-09-27"}

    monkeypatch.setattr(eis, "anchors_from_submissions", _anchors)

    def _facts_entity(facts_obj, *, bank_like, annual_anchors):
        captura["facts_obj"] = facts_obj
        captura["bank_like"] = bank_like
        captura["anchors"] = annual_anchors
        return [], {}

    monkeypatch.setattr(eis, "facts_from_edgartools_entity", _facts_entity)
    out = eis.refresh_from_edgartools(db, company, force=True, submissions=subs)
    assert out["status"] == "ingested"
    assert out["facts_imported"] == 0
    assert out["cik"] == "0000320193"
    assert out["transport"] == "live"
    assert llamadas == {"record_success": 1, "salud_ok": 1}
    assert captura["facts_obj"] is sentinel_facts
    assert captura["anchors_in"] is subs
    assert captura["anchors"] == {"FY2025": "2025-09-27"}
    assert captura["bank_like"] is False


def test_refresh_companyfacts_inyectados_transport_live(db, monkeypatch):
    company = _company(db)
    captura = {}

    def _facts_cf(payload, *, bank_like, annual_anchors, submissions):
        captura.update(
            payload=payload, bank_like=bank_like,
            annual_anchors=annual_anchors, submissions=submissions,
        )
        return [], {}

    monkeypatch.setattr(eis, "facts_from_companyfacts", _facts_cf)
    payload = {"facts": {"us-gaap": {}}}
    out = eis.refresh_from_edgartools(db, company, force=True, companyfacts=payload)
    assert out["status"] == "ingested"
    assert out["facts_imported"] == 0
    assert out["transport"] == "live"
    assert out["snapshot_synced_at"] is None
    assert captura["payload"] is payload
    assert captura["bank_like"] is False


def test_refresh_live_exito_sin_facts_cae_en_sin_companyfacts(db, monkeypatch):
    company = _company(db)
    _sin_snapshot(monkeypatch)
    monkeypatch.setattr(client, "is_installed", lambda: True)
    monkeypatch.setattr(client, "default_breaker", _breaker_espia)
    monkeypatch.setattr(client, "report_sec_success_to_health", lambda: None)
    monkeypatch.setattr(
        eis, "_fetch_live_entity_facts", lambda cik_o_ticker: (None, "0000320193")
    )
    out = eis.refresh_from_edgartools(db, company, force=True)
    assert out["status"] == "unavailable"
    assert out["reason"] == "sin companyfacts para TSTEDG"
    assert out["transport"] == "live"


# -- Form 4 aristas --------------------------------------------------------------------

_SUBS_FORM4 = {
    "filings": {"recent": {
        "accessionNumber": ["0001234567-26-000001", "0001234567-26-000002"],
        "form": ["4", "4"],
        "primaryDocument": ["a.xml", "b.xml"],
        "filingDate": ["2026-01-10", "2026-02-10"],
        "reportDate": ["2026-01-09", "2026-02-09"],
    }}
}


def test_form4_no_es_filer(monkeypatch):
    _sin_snapshot(monkeypatch)
    out = eis.refresh_form4_from_edgartools("TSTEDG", force=True)
    assert out["status"] == "unavailable"
    assert out["reason"] == "not a US SEC filer"
    assert out["transactions"] == []


def test_form4_sin_submissions_snapshot(monkeypatch):
    monkeypatch.setattr(client, "read_submissions", lambda cik, root=None: None)
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)
    out = eis.refresh_form4_from_edgartools("TSTEDG", force=True, cik="320193")
    assert out["status"] == "unavailable"
    assert out["reason"] == "sin submissions (snapshot) para TSTEDG"
    assert out["cik"] == "0000320193"


def test_form4_filings_corta_al_limite():
    items = eis._form4_filings_from_submissions(_SUBS_FORM4, cik="0000320193", limit=1)
    assert len(items) == 1
    assert items[0]["accession_number"] == "0001234567-26-000001"
    assert items[0]["form"] == "4"


def test_form4_xml_ausente_en_snapshot(monkeypatch):
    monkeypatch.setattr(client, "read_filing_xml", lambda acc, name, root=None: None)
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)
    out = eis.refresh_form4_from_edgartools(
        "TSTEDG", force=True, cik="320193", submissions=_SUBS_FORM4
    )
    assert out["status"] == "degraded"
    assert out["transactions"] == []
    assert out["filing_errors"] == [
        "0001234567-26-000001: sin XML en snapshot",
        "0001234567-26-000002: sin XML en snapshot",
    ]


def test_form4_xml_parse_error_agregado(monkeypatch):
    monkeypatch.setattr(client, "read_filing_xml", lambda acc, name, root=None: "<xml>malo</xml>")
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)

    def _parse_que_falla(xml):
        raise ValueError("xml corrupto")

    monkeypatch.setattr(eis, "ownership_transactions", _parse_que_falla)
    subs = {"filings": {"recent": {
        "accessionNumber": ["0001234567-26-000001"],
        "form": ["4"],
        "primaryDocument": ["a.xml"],
        "filingDate": ["2026-01-10"],
        "reportDate": ["2026-01-09"],
    }}}
    out = eis.refresh_form4_from_edgartools(
        "TSTEDG", force=True, cik="320193", submissions=subs
    )
    assert out["status"] == "degraded"
    assert out["transactions"] == []
    assert out["filing_errors"] == ["0001234567-26-000001: form4_xml_parse_error"]


# -- 13F aristas -------------------------------------------------------------------------

_SUBS_13F = {
    "filings": {"recent": {
        "accessionNumber": ["0001234567-26-000001", "0001234567-26-000002"],
        "form": ["13F-HR", "13F-HR/A"],
        "primaryDocument": ["a.xml", "b.xml"],
        "filingDate": ["2026-02-14", "2026-02-15"],
        "reportDate": ["2025-12-31", "2025-12-31"],
    }}
}


def test_13f_filings_corta_al_limite():
    items = eis._thirteenf_filings_from_submissions(_SUBS_13F, limit=1)
    assert len(items) == 1
    assert items[0] == {
        "accession_number": "0001234567-26-000001",
        "form": "13F-HR",
        "is_amendment": False,
        "report_date": "2025-12-31",
        "filing_date": "2026-02-14",
        "primary_document": "a.xml",
    }


def test_13f_sin_submissions_snapshot(monkeypatch):
    monkeypatch.setattr(client, "read_submissions", lambda cik, root=None: None)
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)
    out = eis.refresh_13f_from_edgartools("320193", force=True)
    assert out["status"] == "unavailable"
    assert out["reason"] == "sin submissions (snapshot) para 0000320193"
    assert out["holdings"] == []


def test_13f_sin_filings_13fhr(monkeypatch):
    subs = {"filings": {"recent": {
        "accessionNumber": ["0001234567-26-000009"],
        "form": ["10-Q"],
        "primaryDocument": ["q.htm"],
        "filingDate": ["2026-02-14"],
        "reportDate": ["2025-12-31"],
    }}}
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)
    out = eis.refresh_13f_from_edgartools("320193", force=True, submissions=subs)
    assert out["status"] == "unavailable"
    assert out["reason"] == "no 13F-HR filings found"
    assert out["holdings"] == []


def test_13f_errores_xml_agregados_por_filing(monkeypatch):
    def _xml_falso(accession, name, root=None):
        return None if accession.endswith("000001") else "<xml>malo</xml>"

    monkeypatch.setattr(client, "read_filing_xml", _xml_falso)
    monkeypatch.setattr(client, "manifest_synced_at", lambda root=None: None)

    def _infotable_que_falla(xml):
        raise ValueError("tabla corrupta")

    monkeypatch.setattr(eis, "infotable_holdings", _infotable_que_falla)
    out = eis.refresh_13f_from_edgartools("320193", force=True, submissions=_SUBS_13F)
    assert out["status"] == "ok"
    assert out["holdings"] == []
    assert out["errors"] == [
        {"accession": "0001234567-26-000001", "error": "information_table_not_found"},
        {"accession": "0001234567-26-000002", "error": "information_table_parse_error"},
    ]
