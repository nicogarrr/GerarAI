"""El escéptico corre en el pipeline de la tesis y sus juicios etiquetan el contraste con el consenso."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import thesis_service as thesis
from app.services.expert_team import analyst_blend, esceptico, recopilador, roster, service
from app.services.expert_team.esceptico import DriverBelief


def _stage(status="ok"):
    return SimpleNamespace(as_dict=lambda: {"status": status})


def test_pipeline_runs_esceptico_after_blend_and_keeps_its_labels(monkeypatch):
    assert [s.name for s in roster.pipeline_experts()] == ["recopilador", "mezcla_analistas", "esceptico"]
    monkeypatch.setattr(service, "run_context", lambda *a, **kw: object())
    monkeypatch.setattr(service, "provider_reasoner", lambda **kw: object())
    order = []

    async def reco(db, **kw):
        order.append("recopilador")
        return _stage("stored")

    async def blend(db, **kw):
        order.append("mezcla")
        assert len(kw["extra_sources"]) == 1  # notas de analista verificadas
        return _stage("full_data")

    belief = DriverBelief(driver_key="att_contract", must_believe="que se firme", posture="abierta",
                          closing_data="ingresos en el próximo 10-Q", inputs=("revenue_growth",),
                          source_url="https://sec.gov/x", source_quote="definitive agreement")

    async def skeptic(db, **kw):
        order.append("esceptico")
        assert len(kw["extra_sources"]) == 1
        return SimpleNamespace(beliefs=[belief], as_dict=lambda: {"status": "ok", "beliefs": [belief.as_dict()]})

    monkeypatch.setattr(recopilador, "run_recopilador", reco)
    monkeypatch.setattr(analyst_blend, "run_analyst_blend", blend)
    monkeypatch.setattr(esceptico, "run_esceptico", skeptic)
    from app.services.analyst_history_service import analyst_history_service
    monkeypatch.setattr(analyst_history_service, "get", AsyncMock(
        return_value=SimpleNamespace(consensus=SimpleNamespace(mean=100.0), source_url="src")))
    out = asyncio.run(thesis._run_thesis_experts(None, "ASTS"))
    assert order == ["recopilador", "mezcla", "esceptico"]
    assert out["stages"][2]["beliefs"][0]["postura"] == "abierta"
    labels = out[thesis._SKEPTIC_LABELS]
    assert labels["revenue_growth"].label == "abierta"

    # Las etiquetas llegan al contraste y no se guardan en la traza.
    seen = {}
    from app.valuation import consensus_sanity

    real = consensus_sanity.consensus_sanity_for_dcf

    def spy(valuation, **kw):
        seen["labels"] = kw.get("labels")
        return real(valuation, **kw)

    monkeypatch.setattr(consensus_sanity, "consensus_sanity_for_dcf", spy)
    valuation = {"base_value": 50.0, "trace": {}}
    thesis._apply_thesis_consensus(valuation, out)
    assert seen["labels"]["revenue_growth"].label == "abierta"
    assert thesis._SKEPTIC_LABELS not in valuation["trace"]["expert_pipeline"]
