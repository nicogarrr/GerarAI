"""Tesis de la watchlist sin «datos insuficientes» evitables (owner 3-nov-2026).

- Quema de caja en el DCF estandar (IBG, RED): senda a rentabilidad con un
  margen objetivo inferido y validado, siempre orientativa; sin objetivo, N/D.
- Motor sectorial sin sus datos (CB, CPT, BN, KKR, CGEO.L): respaldo
  orientativo por multiplos de comparables, etiquetado; sin cifra, el N/D
  original intacto.
- Antes de generar: WACC recalculado y margen objetivo inferido por el modelo
  solo cuando hace falta; cualquier fallo deja el N/D honesto.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base as CoreBase  # noqa: F401  (registra listeners)
from app.models.entities import Base, Company
from app.services import thesis_input_inference as tii
from app.services import valuation_service as vs
from app.services.inferred_input_service import InferredInputService
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.standard_dcf import StandardDCFEngine
from tests.test_inferred_global_coherent_wiring import _Snap

BASE = "Dado el margen FCF medio de pares de redes eléctricas reguladas con fuentes, inferimos 0,12"
URLS = ["https://www.ree.es/es/accionistas-e-inversores/informacion-financiera"]
VALUES = {
    "revenue": 2_000_000_000.0,
    "free_cash_flow": -400_000_000.0,
    "revenue_growth": 0.05,
    "shares_diluted": 540_000_000.0,
    "net_debt": 500_000_000.0,
}


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.info["tenant_id"] = 2
        yield session
    eng.dispose()


def _company(db, ticker="RED"):
    c = Company(ticker=ticker, name="Redeia Corporacion", exchange="BME", currency="EUR", sector="S",
                industry="I", company_type="research_candidate", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _dcf(db, company):
    ctx = ValuationContext(db=db, company=company, snapshot=_Snap(VALUES), current_price=15.0,
                           engine_key="standard_dcf")
    return StandardDCFEngine().value(ctx)


def test_dcf_estandar_con_quema_de_caja_sin_objetivo_sigue_sin_cifra(db):
    out = _dcf(db, _company(db))
    assert out["status"] == "insufficient_data"
    assert "non_negative_fcf_margin" in out["missing_inputs"]


def test_dcf_estandar_con_quema_de_caja_y_objetivo_inferido_da_senda_orientativa(db):
    company = _company(db)
    InferredInputService().create(db, company, input_key="fcf_margin", value=Decimal("0.12"),
                                  base=BASE, source_urls=URLS)
    db.commit()
    out = _dcf(db, company)
    assert out["status"] != "insufficient_data"
    assert out["publishable"] is False
    assert "inferred_fcf_margin_target" in (out.get("publication_blockers") or [])
    assert out["status"] == "partial", {k: out.get(k) for k in ("status", "base_value", "expected_value")}
    assert any(out.get(k) is not None for k in ("base_value", "expected_value", "bear_value")), (
        {k: v for k, v in out.items() if k.endswith("value")}, (out.get("trace") or {}).get("value_notes"))


def _insufficient():
    return {"status": "insufficient_data", "publishable": False, "missing_inputs": ["cost_of_equity", "combined_ratio"],
            "base_value": None, "expected_value": None,
            "trace": {"engine": "insurer", "reason": "Insurer valuation requires ..."}}


def test_respaldo_sectorial_por_multiplos_es_orientativo_y_etiquetado(monkeypatch, db):
    cross = {"status": "ok", "base_value": 410.0, "expected_value": 405.0, "bear_value": 350.0,
             "bull_value": 470.0, "margin_of_safety": 0.09, "headline_multiple": "pb", "peer_median": 1.9}
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: dict(cross))
    out = vs._sector_fallback(db, _company(db, "CB"), object(), _insufficient(), to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out["status"] == "partial" and out["publishable"] is False
    assert out["expected_value"] == 405.0
    assert out["publication_blockers"] == ["sector_engine_fallback"]
    fb = out["trace"]["sector_engine_fallback"]
    assert fb["sector_engine"] == "insurer" and fb["sector_missing_inputs"] == ["cost_of_equity", "combined_ratio"]
    motor = [i for i in out["estimated_inputs"] if i["metric"] == "motor"][0]
    assert "orientativo" in motor["method"] and "insurer" in motor["note"]


def test_respaldo_sectorial_sin_cifra_devuelve_el_nd_original(monkeypatch, db):
    original = _insufficient()
    monkeypatch.setattr(vs, "_relative_multiples_cross_check",
                        lambda *a, **k: {"status": "insufficient_data", "missing_inputs": ["peers"]})
    assert vs._sector_fallback(db, _company(db, "CB"), object(), original, to_listing=None,
                               price_currency="USD", reporting_currency="USD") is original
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: None)
    assert vs._sector_fallback(db, _company(db, "CPT"), object(), original, to_listing=None,
                               price_currency="USD", reporting_currency="USD") is original


class _FakeValuation:
    def __init__(self, result):
        self.result = result

    def value_company(self, db, company):
        return self.result


def test_prepara_objetivo_inferido_solo_si_hace_falta(monkeypatch, db):
    company = _company(db)
    calls = []

    async def fake_infer(db, ticker, *, input_key, **kwargs):
        calls.append((ticker, input_key))
        return InferredInputService().create(db, company, input_key="fcf_margin", value=Decimal("0.12"),
                                             base=BASE, source_urls=URLS)

    import app.services.inferred_input_llm_service as llm
    import app.valuation.engines.base as base

    monkeypatch.setattr(llm, "infer_input", fake_infer)
    monkeypatch.setattr(base, "traceable_wacc", lambda db, company, **k: 0.08)
    monkeypatch.setattr(tii, "refresh_fmp_for_cross_check", lambda db, company: "sin_clave")
    monkeypatch.setattr(tii, "_prepare_sector_inputs", lambda db, company, valuation: "no_aplica")
    monkeypatch.setattr(vs, "ValuationService", lambda: _FakeValuation(
        {"status": "insufficient_data", "missing_inputs": ["non_negative_fcf_margin"]}))
    out = tii.prepare_missing_inputs(db, company)
    assert calls == [("RED", "fcf_margin")]
    assert out["fcf_margin_target"]["status"] == "inferido"
    # segunda vez: ya hay objetivo valido, no se gasta otra llamada
    again = tii.prepare_missing_inputs(db, company)
    assert again["fcf_margin_target"] == "ya_inferido" and len(calls) == 1


def test_prepara_no_llama_al_modelo_si_no_falta_el_margen(monkeypatch, db):
    company = _company(db)
    import app.services.inferred_input_llm_service as llm
    import app.valuation.engines.base as base

    async def boom(*a, **k):
        raise AssertionError("no debe llamarse")

    monkeypatch.setattr(llm, "infer_input", boom)
    monkeypatch.setattr(base, "traceable_wacc", lambda db, company, **k: 0.08)
    monkeypatch.setattr(tii, "refresh_fmp_for_cross_check", lambda db, company: "sin_clave")
    monkeypatch.setattr(tii, "_prepare_sector_inputs", lambda db, company, valuation: "no_aplica")
    monkeypatch.setattr(vs, "ValuationService", lambda: _FakeValuation(
        {"status": "insufficient_data", "missing_inputs": ["net_debt"]}))
    assert tii.prepare_missing_inputs(db, company)["fcf_margin_target"] == "no_aplica"


def test_prepara_traga_cuota_o_sin_extractos(monkeypatch, db):
    company = _company(db)
    import app.services.inferred_input_llm_service as llm
    import app.valuation.engines.base as base

    async def rejected(*a, **k):
        raise llm.InferenceRejected("sin_fuentes")

    monkeypatch.setattr(llm, "infer_input", rejected)
    monkeypatch.setattr(base, "traceable_wacc", lambda db, company, **k: 0.08)
    monkeypatch.setattr(tii, "refresh_fmp_for_cross_check", lambda db, company: "sin_clave")
    monkeypatch.setattr(tii, "_prepare_sector_inputs", lambda db, company, valuation: "no_aplica")
    monkeypatch.setattr(vs, "ValuationService", lambda: _FakeValuation(
        {"status": "insufficient_data", "missing_inputs": ["non_negative_fcf_margin"]}))
    assert tii.prepare_missing_inputs(db, company)["fcf_margin_target"] == "omitido:sin_fuentes"


def test_empresa_nueva_sin_precios_encola_su_historial(monkeypatch, db):
    """BFIT.AS (3-nov-2026): la ficha nace en el job de tesis; sin precio no hay valor justo."""
    import app.services.market_close_sync as mcs
    from app.services import thesis_job_service as tjs

    company = _company(db, "BFIT.AS")
    calls = []
    monkeypatch.setattr(mcs, "enqueue_price_backfills",
                        lambda db, ids, tenant_id, user_id: calls.append((ids, tenant_id, user_id)) or 1)
    tjs._ensure_price_history(db, company, 2, "u1")
    assert calls == [([company.id], 2, "u1")]
    tjs._ensure_price_history(db, company, None, None)  # sin tenant/usuario: nada
    assert len(calls) == 1


def test_inputs_sectoriales_se_piden_con_la_misma_valoracion(monkeypatch, db):
    import importlib
    import types

    company = _company(db, "CPT")
    seen = []
    fake = types.SimpleNamespace(prepare_sector_inputs=lambda db, c, v: seen.append(v) or {"status": "ok"})
    monkeypatch.setattr(importlib, "import_module", lambda name: fake)
    valuation = {"status": "insufficient_data", "missing_inputs": ["cap_rate"]}
    assert tii._prepare_sector_inputs(db, company, valuation) == {"status": "ok"}
    assert seen == [valuation]

    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", boom)
    assert tii._prepare_sector_inputs(db, company, valuation) == "no_disponible"
