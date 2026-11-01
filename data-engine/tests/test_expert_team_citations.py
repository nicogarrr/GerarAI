"""Validador de citas: cada cifra debe estar en la evidencia citada de ESTA corrida."""

from __future__ import annotations

import asyncio
import json

from app.services.expert_team import (
    Claim,
    EvidenceLedger,
    ExpertSpec,
    ExpertTeam,
    RunContext,
    ToolOutput,
    ToolSpec,
)
from app.services.expert_team.citations import MARK_PREFIX, citation_validator

SPEC = ExpertSpec(name="valuation", prompt_name="expert_valuation", tools=("valuation_engine", "news_events"))


def _ledger() -> tuple[EvidenceLedger, str, str]:
    ledger = EvidenceLedger()
    val = ledger.add(
        expert="valuation",
        tool="valuation_engine",
        source={"table": "valuation_engine", "date": "2026-10-31"},
        data={"base_value": 450.0, "margin_of_safety": 0.11, "revenue": 1234.5, "change_pct": -5.2},
    )
    news = ledger.add(
        expert="valuation", tool="news_events", source={"table": "news_events", "date": "2026-10-20"},
        data={"title": "Microsoft sube el dividendo a 0,83 USD"},
    )
    return ledger, val.id, news.id


def _check(claim: Claim, **kw) -> str:
    ledger, _, _ = _ledger()
    return citation_validator(**kw)(claim, ledger, SPEC)


def test_number_present_in_cited_data_passes():
    ledger, val, _ = _ledger()
    claim = Claim(text="El valor base es 450 USD", numbers=(450.0,), citations=(val,))
    assert citation_validator()(claim, ledger, SPEC) == ""


def test_invented_number_is_dropped():
    _, val, _ = _ledger()
    assert _check(Claim(text="valor base", numbers=(470.0,), citations=(val,))) == "number_not_in_evidence"


def test_number_written_only_in_text_is_checked_too():
    _, val, _ = _ledger()
    assert _check(Claim(text="El valor base es 520 USD", citations=(val,))) == "number_not_in_evidence"
    assert _check(Claim(text="El valor base es 450 USD", citations=(val,))) == ""


def test_number_from_uncited_evidence_does_not_count():
    _, _, news = _ledger()
    assert _check(Claim(text="valor base 450", citations=(news,))) == "number_not_in_evidence"


def test_percent_rounding_sign_and_spanish_format():
    _, val, news = _ledger()
    assert _check(Claim(text="margen de seguridad del 11 %", citations=(val,))) == ""
    assert _check(Claim(text="ingresos de 1.234,5 millones", citations=(val,))) == ""
    assert _check(Claim(text="ingresos de 1,234.5 millones", citations=(val,))) == ""
    assert _check(Claim(text="la acción cae un 5,2 %", citations=(val,))) == ""
    assert _check(Claim(text="valor base de 450,3", citations=(val,))) == ""  # redondeo
    assert _check(Claim(text="dividendo de 0,83 USD", citations=(news,))) == ""


def test_dates_of_cited_source_and_small_counts_are_not_figures():
    _, _, news = _ledger()
    assert _check(Claim(text="Noticia del 20 de octubre de 2026 con 3 claves", citations=(news,))) == ""


def test_evidence_ids_in_text_are_not_figures():
    ledger = EvidenceLedger()
    ids = [ledger.add(expert="valuation", tool="news_events", source={}, data={"x": "texto"}).id for _ in range(12)]
    claim = Claim(text=f"según {ids[-1]}", citations=(ids[-1],))
    assert citation_validator()(claim, ledger, SPEC) == ""


def test_basic_rules_still_apply():
    ledger, val, _ = _ledger()
    validator = citation_validator()
    assert validator(Claim(text="sin cita"), ledger, SPEC) == "uncited"
    assert validator(Claim(text="x", citations=("ev-99",)), ledger, SPEC) == "unknown_citation"
    other = ledger.add(expert="risk", tool="risk_events", source={}, data={"v": 450.0})
    assert validator(Claim(text="450", citations=(other.id,)), ledger, SPEC) == "foreign_citation"


def test_mark_mode_keeps_claim_flagged():
    _, val, _ = _ledger()
    assert _check(Claim(text="valor base 999", citations=(val,)), mode="mark") == MARK_PREFIX + "number_not_in_evidence"


def _team(reply: dict, **kw) -> ExpertTeam:
    tool = ToolSpec(
        name="valuation_engine",
        fn=lambda ctx: ToolOutput(source={"table": "valuation_engine", "date": "2026-10-31"}, data={"base_value": 450.0}),
    )

    async def reason(system, user, max_tokens, task):
        ev = json.loads(user)["evidence"][0]["id"]
        for claim in reply["claims"]:
            claim["citations"] = [ev]
        return json.dumps(reply)

    spec = ExpertSpec(name="valuation", prompt_name="expert_valuation", tools=("valuation_engine",))
    return ExpertTeam([spec], {"valuation_engine": tool}, reason, **kw)


REPLY = {
    "summary": "",
    "stance": "neutral",
    "claims": [{"text": "valor base 450", "numbers": [450]}, {"text": "objetivo 600", "numbers": [600]}],
}


def test_team_uses_strict_validator_by_default():
    result = asyncio.run(_team(json.loads(json.dumps(REPLY))).run(RunContext(tenant_id=1, ticker="X")))
    report = result.reports[0]
    assert [c.text for c in report.claims] == ["valor base 450"]
    assert [(c.text, c.reason) for c in report.dropped] == [("objetivo 600", "number_not_in_evidence")]


def test_team_mark_mode_keeps_flagged_claims_out_of_sources():
    team = _team(json.loads(json.dumps(REPLY)), validator=citation_validator(mode="mark"))
    report = asyncio.run(team.run(RunContext(tenant_id=1, ticker="X"))).reports[0]
    assert [c.text for c in report.claims] == ["valor base 450", "objetivo 600"]
    assert report.claims[1].reason == MARK_PREFIX + "number_not_in_evidence"
    assert report.dropped == []
