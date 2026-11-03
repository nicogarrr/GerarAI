"""Owner 3-nov-2026: «siempre miramos todas las fuentes, no? Yahoo y FMP? que no
sea solo ahora porque te lo he pedido».

El cruce de fuentes es el camino POR DEFECTO de cada snapshot (cada tesis y
cada valoracion, cualquier tenant), sin que nadie lo pida a mano:
- deuda, caja, deuda neta, acciones y FCF elegidos se comparan con las demas
  fuentes del MISMO cierre: confirmado o discrepancia (manda lo oficial);
- un cero de una sola fuente no se acepta;
- Yahoo se trae en cada tesis aunque no falte nada, y FMP con clave.
"""

from types import SimpleNamespace

import pytest

from app.services import fundamentals_fallback as ff
from app.services import thesis_input_inference as tii
from app.valuation.engines.base import snapshot_trace
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.test_tesis_huecos_puente import _anchor, _company, _fact, db  # noqa: F401


def _sec_company(db):
    company = _company(db, ticker="ACME", name="Acme Corp.", exchange="NYSE", currency="USD")
    _anchor(db, company, source="SEC", unit="USD", period="2025-12-31:FY")
    _fact(db, company, "shares_diluted", 1.0e9, "2025-12-31:FY", source="SEC", unit="shares")
    _fact(db, company, "cash_and_equivalents", 2.0e9, "2025-12-31:FY", source="SEC", unit="USD")
    return company


def test_sin_peticion_manual_el_snapshot_confirma_con_segunda_fuente(db):
    company = _sec_company(db)
    _fact(db, company, "total_debt", 5.0e9, "2025-12-31:FY", source="SEC", unit="USD")
    _fact(db, company, "total_debt", 5.05e9, "2025-12-31:FY", source="FMP", unit="USD")
    _fact(db, company, "shares_diluted", 1.0e9, "2025-12-31:FY", source="YAHOO_FUNDAMENTALS", unit="shares")
    snap = FinancialSnapshotBuilder().build(db, company)
    check = snap.source_checks["total_debt"]
    assert check["status"] == "confirmed" and check["estimated"] is False
    assert snap.source_checks["shares_diluted"]["status"] == "confirmed"
    # va a la traza de cada valoracion, no a «inputs estimados»
    assert snapshot_trace(snap)["source_checks"]["total_debt"]["status"] == "confirmed"
    assert "total_debt" not in snap.bridge_provenance


def test_discrepancia_manda_el_oficial_y_queda_marcada(db):
    company = _sec_company(db)
    _fact(db, company, "total_debt", 5.0e9, "2025-12-31:FY", source="SEC", unit="USD")
    _fact(db, company, "total_debt", 8.0e9, "2025-12-31:FY", source="YAHOO_FUNDAMENTALS", unit="USD")
    snap = FinancialSnapshotBuilder().build(db, company)
    check = snap.source_checks["total_debt"]
    assert check["status"] == "discrepancy"
    assert float(snap.facts["total_debt"].value) == pytest.approx(5.0e9)
    assert any("discrepancia" in w for w in snap.warnings)


def test_cero_de_una_sola_fuente_no_se_acepta(db):
    company = _sec_company(db)
    _fact(db, company, "total_debt", 0, "2025-12-31:FY", source="SEC", unit="USD")
    snap = FinancialSnapshotBuilder().build(db, company)
    assert "total_debt" not in snap.facts or float(snap.facts["total_debt"].value) != 0
    assert any("0 de una sola fuente" in w for w in snap.warnings)


def test_cero_confirmado_por_dos_fuentes_se_acepta(db):
    company = _sec_company(db)
    _fact(db, company, "total_debt", 0, "2025-12-31:FY", source="SEC", unit="USD")
    _fact(db, company, "total_debt", 0, "2025-12-31:FY", source="YAHOO_FUNDAMENTALS", unit="USD")
    snap = FinancialSnapshotBuilder().build(db, company)
    assert float(snap.facts["total_debt"].value) == 0
    assert snap.source_checks["total_debt"]["status"] == "confirmed"


def test_yahoo_se_trae_en_cada_tesis_aunque_no_falte_nada(db):
    company = _sec_company(db)
    _fact(db, company, "total_debt", 5.0e9, "2025-12-31:FY", source="SEC", unit="USD")
    _fact(db, company, "net_debt", 3.0e9, "2025-12-31:FY", source="SEC", unit="USD")
    calls = []

    def fake_refresh(db, company, commit):
        calls.append(company.ticker)
        return {"facts_imported": 4, "symbol": "ACME"}

    out = ff.fill_bridge_gaps(db, company, refresh=fake_refresh)
    assert calls == ["ACME"]
    assert out["status"] == "ok" and out["mode"] == "cruce" and out["wanted"] == []


def test_fmp_segunda_fuente_por_defecto(monkeypatch, db):
    company = _sec_company(db)
    settings = SimpleNamespace(fmp_api_key=None)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    assert tii.refresh_fmp_for_cross_check(db, company) == "sin_clave"

    settings.fmp_api_key = "k"
    calls = []

    async def ok(self, db, company, **kwargs):
        calls.append(company.ticker)
        return {"status": "ok"}

    import app.services.financial_ingestion_service as fis

    monkeypatch.setattr(fis.FinancialIngestionService, "refresh_from_fmp", ok)
    assert tii.refresh_fmp_for_cross_check(db, company) == "ok" and calls == ["ACME"]

    class _Resp:
        status_code = 402

    class _PlanError(Exception):
        response = _Resp()

    async def plan(self, db, company, **kwargs):
        raise _PlanError("https://financialmodelingprep.com/?apikey=SECRETO")

    monkeypatch.setattr(fis.FinancialIngestionService, "refresh_from_fmp", plan)
    out = tii.refresh_fmp_for_cross_check(db, company)
    assert out == "plan_no_cubre" and "SECRETO" not in out


def test_fmp_reciente_no_gasta_cuota(monkeypatch, db):
    company = _sec_company(db)
    _fact(db, company, "total_debt", 5.0e9, "2025-12-31:FY", source="FMP", unit="USD")
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(fmp_api_key="k"))
    assert tii.refresh_fmp_for_cross_check(db, company) == "reciente"
