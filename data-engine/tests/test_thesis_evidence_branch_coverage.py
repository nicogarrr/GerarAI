"""Cobertura dirigida de ramas de thesis_evidence_service (gate fix13).

La union de suites de Release (131 + 74) dejaba 166/200 ramas; estos tests
cubren las ramas que faltan en caminos deterministicos (sin red ni LLM):
divisa de reporte, guarda hermetica, dedupe de noticias, stubs de red,
guardas de _ingest_fundamentals (CIK, taxonomia IFRS, sin metricas), bucle
de insercion (valor no numerico, filed invalido, todo pendiente),
_is_annual_duration con fechas no parseables y los filtros de
_prefer_lessor_revenue (fix13).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services import thesis_evidence_service as tes
from app.services.thesis_evidence_service import SEC_IFRS_EVIDENCE_TAGS, ThesisEvidenceService

ACCN = "0000906345-26-000001"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="", exchange="", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _e(val, end, accn=ACCN, start="2025-01-01", form="10-K", filed="2026-02-06"):
    entry = {"form": form, "val": val, "end": end, "fy": 2025, "fp": "FY", "filed": filed, "accn": accn}
    if start:
        entry["start"] = start
    return entry


# -- _facts_reporting_currency (ramas del doble bucle) -------------------------

def test_divisa_detectada_aunque_venga_en_minusculas():
    facts = {"Revenue": {"units": {"eur": [{"val": 1}]}}}
    assert tes._facts_reporting_currency(facts) == "EUR"


def test_divisa_por_defecto_usd_sin_units():
    assert tes._facts_reporting_currency({}) == "USD"
    assert tes._facts_reporting_currency({"Revenue": {}}) == "USD"


def test_divisa_salta_claves_no_iso_y_sigue_con_el_siguiente_tag():
    facts = {
        "Revenue": {"units": {"shares1": [{"val": 1}]}},  # clave no ISO de 3 letras
        "Assets": {"units": {"GBP": [{"val": 2}]}},
    }
    assert tes._facts_reporting_currency(facts) == "GBP"


# -- _await_sync (guarda hermetica: rama no-pytest) ----------------------------

def test_await_sync_ejecuta_fuera_de_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    async def _cuarenta_y_dos():
        return 42

    assert tes._await_sync(lambda: _cuarenta_y_dos()) == 42


# -- _dedupe_news_rows (fila sin clave) ----------------------------------------

def test_dedupe_conserva_filas_sin_clave():
    rows = [SimpleNamespace(title=None), SimpleNamespace(title=None)]
    assert tes._dedupe_news_rows(rows, 5, None) == rows


# -- _filing_published_at (datetime ya construido) ------------------------------

def test_filing_published_at_acepta_datetime_con_y_sin_tz():
    aware = datetime(2026, 5, 4, tzinfo=UTC)
    assert tes._filing_published_at(aware) is aware
    naive = datetime(2026, 5, 4)
    assert tes._filing_published_at(naive) == naive.replace(tzinfo=UTC)


# -- stubs de red: bajo pytest la red esta vetada --------------------------------

def test_stubs_de_red_explotan_hermeticos_en_pytest():
    service = ThesisEvidenceService()
    with pytest.raises(RuntimeError):
        service._fetch_cik("AAPL")
    with pytest.raises(RuntimeError):
        service._fetch_company_facts("0000320193")
    with pytest.raises(RuntimeError):
        service._fetch_filings("0000320193")
    with pytest.raises(RuntimeError):
        service._fetch_non_sec_reports(SimpleNamespace(ticker="AAPL"))


def test_enqueue_report_envia_con_metadata(monkeypatch, db):
    from app.workers import dramatiq_app

    enviado = {}
    monkeypatch.setattr(
        dramatiq_app, "process_document",
        SimpleNamespace(send=lambda *a, **k: enviado.update(args=a, kwargs=k)),
    )
    company = _company(db)
    link = SimpleNamespace(kind="annual", title="10-K", url="https://x", source="issuer", date="2026-01-01")
    ThesisEvidenceService()._enqueue_report(db, company, link, "2026-01-01")
    assert enviado["args"][:4] == ("AAPL", "10-K", "https://x", "annual_report")
    assert enviado["kwargs"]["filing_metadata"]["report_date_hint"] == "2026-01-01"


# -- _ingest_fundamentals: guardas de identidad y taxonomia ---------------------

def test_ingest_sin_cik_pendiente(db):
    out = ThesisEvidenceService()._ingest_fundamentals(db, _company(db), None)
    assert out["status"] == "pending"
    assert "CIK" in out["detail"]


def test_ingest_cik_devuelto_distinto_no_importa(db, monkeypatch):
    service = ThesisEvidenceService()
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: {"cik": 999999, "facts": {}})
    out = service._ingest_fundamentals(db, _company(db), "0000320193")
    assert out["status"] == "pending"
    assert "no es el solicitado" in out["detail"]


def test_ingest_cik_no_coincide_con_la_ficha(db, monkeypatch):
    service = ThesisEvidenceService()
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: {"cik": "000123", "facts": {}})
    company = _company(db)
    company.cik = "000555"
    out = service._ingest_fundamentals(db, company, "123")
    assert out["status"] == "pending"
    assert "no coincide con el de la ficha" in out["detail"]


def test_ingest_ifrs_con_divisa_del_payload(db, monkeypatch):
    service = ThesisEvidenceService()
    payload = {"cik": "000123", "facts": {"ifrs-full": {
        "Revenue": {"units": {"EUR": [_e(1_000_000, "2025-12-31")]}},
    }}}
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: payload)
    out = service._ingest_fundamentals(db, _company(db), "123")
    assert out["status"] == "ok"
    assert out["facts_imported"] >= 1


def test_ingest_sin_metricas_aprovechables(db, monkeypatch):
    service = ThesisEvidenceService()
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: {"cik": "000123", "facts": {}})
    out = service._ingest_fundamentals(db, _company(db), "123")
    assert out["status"] == "pending"
    assert "sin métricas" in out["detail"]


# -- bucle de insercion: valor no numerico, filed invalido, todo pendiente ------

def test_insercion_filed_invalido_se_guarda_como_none(db, monkeypatch):
    service = ThesisEvidenceService()
    payload = {"cik": "000123", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_e(100, "2025-12-31", filed="sin-fecha")]}},
    }}}
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: payload)
    out = service._ingest_fundamentals(db, _company(db), "123")
    assert out["status"] == "ok" and out["facts_imported"] == 1
    from app.models.entities import FinancialFact

    (fact,) = db.query(FinancialFact).all()
    assert fact.filed is None


def test_insercion_todo_valor_no_numerico_es_pendiente(db, monkeypatch):
    service = ThesisEvidenceService()
    payload = {"cik": "000123", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_e("no-numerico", "2025-12-31")]}},
    }}}
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: payload)
    out = service._ingest_fundamentals(db, _company(db), "123")
    assert out["status"] == "pending"
    assert "sin valor numerico" in out["detail"]


# -- _is_annual_duration y extraction edge cases ---------------------------------

def test_duracion_anual_con_fechas_no_parseables_es_falso():
    assert ThesisEvidenceService._is_annual_duration(
        {"start": "n/a", "end": "2025-12-31"}, "revenue"
    ) is False


def test_extract_salta_entradas_no_dict_o_sin_val():
    us_gaap = {
        "Revenues": {"units": {"USD": [
            "basura",
            {"val": None, "end": "2025-12-31", "form": "10-K"},
            _e(100, "2025-12-31"),
        ]}},
    }
    out = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert out["revenue"][0]["value"] == 100


def test_extract_fiscal_year_none_con_end_no_numerico():
    """Instantanea (sin start): un end no fechado pasa la duracion pero no el año."""
    us_gaap = {"Assets": {"units": {"USD": [
        {"form": "10-K", "val": 5, "end": "ABCD-12-31", "filed": "2026-02-06"},
    ]}}}
    out = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert out["total_assets"][0]["fiscal_year"] is None
    assert out["total_assets"][0]["value"] == 5


def test_extract_ifrs_con_divisa_y_fallback_legado():
    """tags_map/currency (ruta IFRS): la unidad USD marcador se cambia por la
    divisa del payload; sin anual valido cae al legado (ultimo trimestre)."""
    ifrs = {"Revenue": {"units": {"EUR": [_e(250, "2026-03-31", start="2026-01-01", form="20-F", filed="2026-05-01")]}}}
    out = ThesisEvidenceService()._extract_recent_annuals(
        ifrs, tags_map=SEC_IFRS_EVIDENCE_TAGS, currency="EUR"
    )
    assert out["revenue"][0]["value"] == 250
    assert out["revenue"][0]["unit"] == "EUR"


# -- _prefer_lessor_revenue: filtros del pool arrendador (fix13) -----------------

def test_lessor_filtra_basura_form_no_anual_y_duracion_corta():
    """Las entradas arrendador invalidas se descartan una a una; a igual
    periodo+accn gana el mayor y un empate menor no reemplaza."""
    us_gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _e(12_970_000, "2025-12-31"),
        ]}},
        "OperatingLeaseLeaseIncome": {"units": {"USD": [
            "basura",  # no dict
            {"val": None, "end": "2025-12-31", "form": "10-K", "accn": ACCN},  # sin valor
            _e(100, "2025-12-31", form="10-Q"),  # form no anual
            _e(100, "2025-03-31", start="2025-01-01"),  # duracion trimestral
            _e(500_000_000, "2025-12-31"),
            _e(400_000_000, "2025-12-31"),  # mismo periodo+accn, menor: no reemplaza
            _e(1_573_500_000, "2025-12-31"),  # mayor: reemplaza y gana
        ]}},
    }
    out = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert out["revenue"][0]["value"] == 1_573_500_000
    assert out["revenue"][0]["concept"] == "OperatingLeaseLeaseIncome"
