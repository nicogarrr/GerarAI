"""Via edgartools: offline-first, throttle, breaker y markdown (hermetico, sin red).

- 403 (caso OCI) degrada al snapshot con estado explicito, jamas reintenta.
- 429 alimenta el breaker (racha 5 en 600 s -> abierto 3600 s) y degrada.
- Throttle propio: cap SEC 10 req/s.
- Flag off por defecto; markdown con seccion + pagina para Fase B1.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services.connectors import edgartools_client as client
from app.services.connectors.edgartools_client import (
    EdgarToolsThrottle,
    RateLimitBreaker,
)
from app.services.connectors.edgartools_markdown import (
    detect_section,
    filing_markdown_blocks,
    html_to_markdown,
    markdown_blocks,
)
from app.services.edgartools_ingestion_service import (
    refresh_13f_from_edgartools,
    refresh_form4_from_edgartools,
    refresh_from_edgartools,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edgartools"


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


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="TSTEDG"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Semiconductors", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_throttle_caps_at_sec_maximum():
    throttle = EdgarToolsThrottle(requests_per_second=100)
    assert throttle.min_interval == pytest.approx(0.1)
    assert EdgarToolsThrottle().min_interval == pytest.approx(1 / 8)


def test_throttle_enforces_minimum_interval():
    throttle = EdgarToolsThrottle(requests_per_second=10)
    throttle.reset_for_tests()
    start = time.monotonic()
    throttle.wait_sync()
    throttle.wait_sync()
    throttle.wait_sync()
    assert time.monotonic() - start >= 0.19


def test_breaker_opens_after_streak_and_reports_state():
    breaker = RateLimitBreaker(window_s=600.0, streak_limit=5, cooldown_s=3600.0)
    assert breaker.is_open() is False
    for _ in range(4):
        assert breaker.record_429() is False
    assert breaker.record_429() is True
    assert breaker.is_open() is True
    # Abierto: mas 429 no lo cierran.
    assert breaker.record_429() is True


def test_breaker_window_resets_stale_streak():
    breaker = RateLimitBreaker(window_s=600.0, streak_limit=2, cooldown_s=3600.0)
    assert breaker.record_429() is False
    # La ventana expiro (racha vieja): vuelve a contar desde 1, no abre.
    breaker._window_start -= 700.0
    assert breaker.record_429() is False
    assert breaker.is_open() is False
    # Dos 429 dentro de la ventana si abren.
    assert breaker.record_429() is True
    assert breaker.is_open() is True


def test_status_extraction_and_sec_block():
    assert client.http_status_from_error(RuntimeError("SEC EDGAR request failed (403 Forbidden)")) == 403
    assert client.http_status_from_error(RuntimeError("Client error '429 Too Many Requests'")) == 429
    assert client.http_status_from_error(RuntimeError("boom sin codigo")) is None
    assert client.is_sec_block(RuntimeError("SEC EDGAR request failed (401 Unauthorized)")) is True
    assert client.is_sec_block(RuntimeError("SEC EDGAR request failed (429 slow down)")) is False


def test_identity_always_carries_contact_email():
    identity = client.resolve_identity()
    assert identity and "@" in identity


def test_ensure_identity_never_raises_without_library(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_edgar(name, *args, **kwargs):
        if name == "edgar" or name.startswith("edgar."):
            raise ImportError("no edgar")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_edgar)
    assert client.is_installed() is False
    assert client.ensure_identity() is None


def test_snapshot_readers_serve_offline_layout():
    assert client.manifest_cik("tstedg", FIXTURES) == "0001234567"
    assert client.manifest_synced_at(FIXTURES) == "2026-09-30T12:00:00+00:00"
    facts = client.read_companyfacts("0001234567", FIXTURES)
    assert facts["entityName"] == "Test Edgar Corp"
    subs = client.read_submissions("0001234567", FIXTURES)
    assert subs["filings"]["recent"]["form"][0] == "10-K"
    assert client.read_companyfacts("0000000000", FIXTURES) is None
    assert client.manifest_cik("NOPE", FIXTURES) is None


def test_403_degrades_to_snapshot_with_explicit_state(db, monkeypatch):
    import app.services.edgartools_ingestion_service as service

    def _blocked(_cik_or_ticker):
        raise RuntimeError("SEC EDGAR request failed (403 Forbidden)")

    monkeypatch.setattr(service, "_fetch_live_entity_facts", _blocked)
    # La via live exige edgartools instalado; sin el pin el test depende del entorno.
    monkeypatch.setattr(client, "is_installed", lambda: True)
    client.default_breaker().reset_for_tests()
    company = _company(db)
    result = refresh_from_edgartools(db, company, force=True, snapshot_root=FIXTURES)
    assert result["status"] == "ingested"
    assert result["transport"] == "snapshot"
    assert result["snapshot_synced_at"] == "2026-09-30T12:00:00+00:00"
    # El 403 NO alimenta el breaker de 429 (es permanente, no rate limit).
    assert client.default_breaker().is_open() is False
    rows = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)).all()
    assert len(rows) == result["facts_imported"] > 0


def test_429_feeds_breaker_and_degrades(db, monkeypatch):
    import app.services.edgartools_ingestion_service as service

    def _limited(_cik_or_ticker):
        raise RuntimeError("Client error '429 Too Many Requests' for url")

    monkeypatch.setattr(service, "_fetch_live_entity_facts", _limited)
    # La via live exige edgartools instalado: sin este pin, en un entorno sin
    # edgar el servicio nunca llama al stub y el breaker no recibe los 429.
    monkeypatch.setattr(client, "is_installed", lambda: True)
    breaker = client.default_breaker()
    breaker.reset_for_tests()
    company = _company(db)
    # CIK almacenado sin payload en el snapshot: fuerza la via live (el 429
    # es lo que alimenta el breaker). Sin CIK, la resolucion por manifest
    # encontraria el snapshot primero y nunca llamaria a live.
    company.cik = "9999999999"
    result = refresh_from_edgartools(db, company, force=True, snapshot_root=FIXTURES)
    assert result["status"] == "ingested" and result["transport"] == "snapshot"
    for _ in range(4):
        refresh_from_edgartools(db, company, force=True, snapshot_root=FIXTURES)
    assert breaker.is_open() is True
    breaker.reset_for_tests()


def test_no_snapshot_without_live_is_honest_unavailable(db, monkeypatch, tmp_path):
    import app.services.edgartools_ingestion_service as service

    def _blocked(_cik_or_ticker):
        raise RuntimeError("SEC EDGAR request failed (403 Forbidden)")

    monkeypatch.setattr(service, "_fetch_live_entity_facts", _blocked)
    company = _company(db, ticker="NOSNAP")
    result = refresh_from_edgartools(db, company, force=True, snapshot_root=tmp_path)
    assert result["status"] == "unavailable"
    assert result["transport"] == "snapshot" and "sin snapshot" in result["reason"]


def test_service_is_behind_flag_by_default(db, monkeypatch):
    import app.services.edgartools_ingestion_service as service

    monkeypatch.setattr(service, "is_enabled", lambda: False)
    company = _company(db)
    assert refresh_from_edgartools(db, company)["status"] == "disabled"
    assert refresh_form4_from_edgartools("TSTEDG")["status"] == "disabled"
    assert refresh_13f_from_edgartools("0001234567")["status"] == "disabled"


def test_markdown_carries_section_and_page():
    markdown = (
        "# TEST EDGAR CORP — 10-K\n\n"
        "## ITEM 1A. Risk Factors\n\nOur business faces risks.\n\n"
        "## ITEM 7. Management's Discussion and Analysis\n\nRevenue grew.\n"
    )
    assert detect_section("## ITEM 1A. Risk Factors") == "Risk Factors"
    assert detect_section("## ITEM 7. Management's Discussion and Analysis") == "MD&A"
    blocks = markdown_blocks(markdown, max_chars=40)
    assert len(blocks) >= 3
    pages = [b.metadata["page"] for b in blocks]
    assert pages == sorted(pages) and pages[0] == 1 and len(set(pages)) == len(pages)
    assert all(b.metadata.get("section") and b.metadata.get("page") for b in blocks)
    assert {b.metadata["section"] for b in blocks} >= {"Risk Factors", "MD&A"}
    # Compatibilidad con ParsedBlock (.text + .metadata dict).
    assert all(hasattr(b, "text") and isinstance(b.metadata, dict) for b in blocks)


def test_html_to_markdown_tables_and_blocks():
    html = (
        "<h2>ITEM 1A. Risk Factors</h2><p>Revenue was <b>strong</b>.</p>"
        "<table><tr><td>2024</td><td>391,035</td></tr></table>"
    )
    markdown = html_to_markdown(html)
    assert "| 2024 | 391,035 |" in markdown
    blocks = filing_markdown_blocks(html, is_html=True)
    assert blocks and blocks[0].metadata["section"] == "Risk Factors"
    assert blocks[0].metadata["page"] == 1


def test_build_script_copies_snapshot_offline(tmp_path):
    src = tmp_path / "sec"
    (src / "companyfacts").mkdir(parents=True)
    payload = json.loads((FIXTURES / "companyfacts" / "CIK0001234567.json").read_text(encoding="utf-8"))
    (src / "companyfacts" / "CIK0001234567.json").write_text(json.dumps(payload), encoding="utf-8")
    (src / "manifest.json").write_text(json.dumps({"tickers": {}, "source": "mirror"}), encoding="utf-8")
    out = tmp_path / "edg"
    spec = importlib.util.spec_from_file_location(
        "build_edgartools_snapshots",
        Path(__file__).resolve().parent.parent / "scripts" / "build_edgartools_snapshots.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = ["build", "--sec-snapshot-dir", str(src), "--out", str(out),
            "--synced-at", "2026-09-30T12:00:00+00:00", "TSTEDG:0001234567"]
    import sys

    old = sys.argv
    sys.argv = argv
    try:
        assert module.main() == 0
    finally:
        sys.argv = old
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tickers"] == {"TSTEDG": "0001234567"}
    assert manifest["synced_at"] == "2026-09-30T12:00:00+00:00"
    assert manifest["edgartools"] == "5.59.1"
    assert json.loads((out / "companyfacts" / "CIK0001234567.json").read_text(encoding="utf-8")) == payload


def test_live_injection_point_is_single_network_site():
    import inspect

    import app.services.edgartools_ingestion_service as service

    src = inspect.getsource(service.refresh_from_edgartools)
    assert "_fetch_live_entity_facts" in src
    # Sin reintento en bucle: un solo try live + degradacion.
    assert src.count("_fetch_live_entity_facts") == 1


def test_company_without_industry_still_ingests(db):
    company = _company(db)
    company.industry = ""
    facts_payload = json.loads((FIXTURES / "companyfacts" / "CIK0001234567.json").read_text(encoding="utf-8"))
    subs = json.loads((FIXTURES / "submissions" / "CIK0001234567.json").read_text(encoding="utf-8"))
    result = refresh_from_edgartools(db, company, force=True, companyfacts=facts_payload, submissions=subs)
    assert result["status"] == "ingested"


def test_pad_cik_never_fabricates_zeros():
    """Lista 11.3: "".zfill(10) == "0000000000" (truthy) fabricaba un CIK."""
    from app.services.edgartools_ingestion_service import _pad_cik

    assert _pad_cik("") is None
    assert _pad_cik(None) is None
    assert _pad_cik("   ") is None
    assert _pad_cik("320193") == "0000320193"
    assert _pad_cik("0000320193") == "0000320193"
    assert _pad_cik(320193) == "0000320193"


def test_refresh_without_company_cik_falls_back_to_manifest(db, monkeypatch):
    """Sin CIK en la compania, refresh debe resolver por ticker via manifest,
    nunca usar el CIK fabricado 0000000000 ni exponerlo en la respuesta."""
    import app.services.edgartools_ingestion_service as service

    company = _company(db)
    facts_payload = json.loads((FIXTURES / "companyfacts" / "CIK0001234567.json").read_text(encoding="utf-8"))
    subs = json.loads((FIXTURES / "submissions" / "CIK0001234567.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(service.client, "manifest_cik", lambda ticker, root=None: "0001234567")

    result = refresh_from_edgartools(db, company, force=True, companyfacts=facts_payload, submissions=subs)
    assert result["status"] == "ingested"
    assert result["cik"] == "0001234567"
    assert result["cik"] != "0000000000"
