"""Regeneración SIN MODELO de la propuesta SOTP de los agentes (carril regen, 9-nov-2026).

La clasificación la puso el modelo y se guardó; las cifras las pone el código. Cuando cambian
las anclas (acciones vigentes, caja + inversiones a corto, precio) o las reglas, la propuesta
guardada se rehace con su clasificación y 0 llamadas al modelo.
"""

from __future__ import annotations

import json

import pytest

from app.services.expert_team import sotp_valuer
from app.services.expert_team.sotp_valuer import recompute_saved_proposal
from app.services.user_sotp_service import AGENTS_SEGMENT, UserSotpService
from tests.test_sotp_agents import ANCHORS, T1, _company, _generate, _good_for_tools, db  # noqa: F401


def _history(db, company):  # noqa: F811
    return UserSotpService().inputs.history(db, company_id=company.id, tenant_id=T1,
                                            input_key="sotp_user_model", segment_key=AGENTS_SEGMENT)


def _no_model(*_a, **_k):
    raise AssertionError("el recálculo no puede llamar al modelo")


def test_recompute_uses_saved_classification_and_new_anchors_without_the_model(db, monkeypatch):  # noqa: F811
    company = _company(db)
    first = _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())])
    assert first.status == "stored"
    before = _history(db, company)[-1]
    # Antes: 300 M acciones y caja − deuda 600 M. Hoy la portada dice 450 M acciones (otras clases).
    monkeypatch.setattr(sotp_valuer, "sotp_anchors",
                        lambda db, company, today=None: dict(ANCHORS, ticker=company.ticker, shares_current_millions=450.0))
    monkeypatch.setattr(sotp_valuer, "run_sotp_valuer", _no_model)
    out = recompute_saved_proposal(db, company)
    assert out["status"] == "stored", out
    assert out["new_value_per_share"] < out["old_value_per_share"]
    rows = _history(db, company)
    assert len(rows) == 2
    meta = rows[-1].metadata_
    assert meta["trigger"] == "recompute" and meta["llm_calls"] == 0
    assert meta["classification"] == before.metadata_["classification"]
    assert meta["fingerprint"] == before.metadata_["fingerprint"]  # la caché por huella sigue sirviendo
    assert meta["model"]["shares_current"] == 450.0
    assert float(rows[-1].base) == pytest.approx(out["new_value_per_share"], rel=1e-6)
    # El cambio viene de los datos, no de otra lectura del modelo: no se marca «inestable».
    shown = UserSotpService().read(db, company, T1)
    assert shown["agents_stability"]["same_classification"] is True
    assert shown["agents_stability"]["unstable"] is False
    assert any("sin modelo" in c for c in shown["agents"]["changed_by"])


def test_recompute_is_idempotent_and_dry_run_writes_nothing(db, monkeypatch):  # noqa: F811
    company = _company(db)
    _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())])
    assert recompute_saved_proposal(db, company)["status"] == "unchanged"  # mismas anclas → nada nuevo
    monkeypatch.setattr(sotp_valuer, "sotp_anchors",
                        lambda db, company, today=None: dict(ANCHORS, ticker=company.ticker, cash_millions=2000.0))
    assert recompute_saved_proposal(db, company, dry_run=True)["status"] == "would_store"
    assert len(_history(db, company)) == 1
    assert recompute_saved_proposal(db, company)["status"] == "stored"
    assert recompute_saved_proposal(db, company)["status"] == "unchanged"
    assert len(_history(db, company)) == 2


def test_recompute_never_saves_what_todays_rules_reject(db, monkeypatch):  # noqa: F811
    company = _company(db)
    _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())])
    monkeypatch.setattr(sotp_valuer, "build_model", lambda classification, anchors: (None, ["falta la divisa del ancla"]))
    out = recompute_saved_proposal(db, company)
    assert out["status"] == "rejected_by_rules" and out["problems"] == ["falta la divisa del ancla"]
    assert len(_history(db, company)) == 1


def test_no_proposal_and_no_tenant(db):  # noqa: F811
    company = _company(db, "NADA")
    assert recompute_saved_proposal(db, company)["status"] == "no_proposal"
    db.info["tenant_id"] = None
    assert recompute_saved_proposal(db, company)["status"] == "no_tenant"



def test_stale_consensus_keys_flags_old_52_53_week_keys():
    import importlib.util
    from datetime import date
    from pathlib import Path
    from types import SimpleNamespace

    path = Path(__file__).resolve().parent.parent / "scripts" / "regenerar_sin_modelo.py"
    spec = importlib.util.spec_from_file_location("regenerar_sin_modelo", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # FY que cierra el 2026-03-01 (52/53 semanas): antes se congelaba como fy2026, hoy es fy2025.
    old = SimpleNamespace(id=1, input_key="estimate.revenue.fy2026", metadata_={"period_end": "2026-03-01"},
                          as_of=date(2026, 1, 5))
    fine = SimpleNamespace(id=2, input_key="estimate.revenue.fy2026", metadata_={"period_end": "2027-02-28"},
                           as_of=date(2026, 6, 1))
    other = SimpleNamespace(id=3, input_key="guidance.revenue.fy2026", metadata_={"period_end": "2026-03-01"}, as_of=None)
    cells = [{"metric": "revenue", "key": "estimate.revenue.fy2025", "period_end": "2026-03-01"},
             {"metric": "revenue", "key": "estimate.revenue.fy2026", "period_end": "2027-02-28"}]
    out = mod.stale_consensus_keys([old, fine, other], cells)
    assert out == [{"row_id": 1, "key": "estimate.revenue.fy2026", "period_end": "2026-03-01",
                    "current_key": "estimate.revenue.fy2025", "as_of": "2026-01-05"}]


def _cargar_regen():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "regenerar_sin_modelo.py"
    spec = importlib.util.spec_from_file_location("regenerar_sin_modelo", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _preparar_filiales_uk(mod, monkeypatch):
    """API key presente, una empresa resuelta y espía en la ruta que recoge/encola."""
    from types import SimpleNamespace

    from app.core import config as app_config
    from app.services.thesis_evidence_service import ThesisEvidenceService

    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(companies_house_api_key="k"))
    company = SimpleNamespace(ticker="MSFT")
    monkeypatch.setattr(mod, "_companies", lambda db, tickers: [company])
    llamadas = []
    monkeypatch.setattr(
        ThesisEvidenceService, "_uk_subsidiary_reports", lambda self, db, c: llamadas.append(c) or []
    )
    return company, llamadas


def test_filiales_uk_dry_run_no_recoge_ni_encola(monkeypatch):
    """--dry-run lista lo que se haría sin llamar a la ruta que recoge y encola."""
    from types import SimpleNamespace

    mod = _cargar_regen()
    _company, llamadas = _preparar_filiales_uk(mod, monkeypatch)
    out = mod.run_filiales_uk(SimpleNamespace(info={}), ["MSFT"], None, True)
    assert llamadas == []
    assert out == {
        "MSFT": {
            "status": "dry_run",
            "accion": "se recogerian las cuentas de las filiales UK y se encolaria su lectura"
            " (con --dry-run no se recoge ni se encola nada)",
        }
    }


def test_filiales_uk_sin_dry_run_si_recoge(monkeypatch):
    """Sin --dry-run la ruta se llama una vez por empresa (el flag sí llega)."""
    from types import SimpleNamespace

    mod = _cargar_regen()
    company, llamadas = _preparar_filiales_uk(mod, monkeypatch)
    out = mod.run_filiales_uk(SimpleNamespace(info={}), ["MSFT"], None, False)
    assert llamadas == [company]
    assert out == {"MSFT": []}


def test_main_filiales_uk_dry_run_no_llama_la_ruta(monkeypatch, capsys):
    """El probe del auditor: main(['filiales-uk','--dry-run','MSFT']) no llama a la ruta."""
    from types import SimpleNamespace

    mod = _cargar_regen()
    _company, llamadas = _preparar_filiales_uk(mod, monkeypatch)
    monkeypatch.setattr(mod, "SessionLocal", lambda: SimpleNamespace(info={}, close=lambda: None))
    mod.main(["filiales-uk", "--dry-run", "MSFT"])
    assert llamadas == []
    salida = json.loads(capsys.readouterr().out)
    assert salida["dry_run"] is True
    assert salida["result"]["MSFT"]["status"] == "dry_run"
