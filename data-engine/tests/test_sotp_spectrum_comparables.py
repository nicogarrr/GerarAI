"""Espectro valorado por transacciones comparables citadas (fuentes-1, 8-nov-2026).

Caso real: el desglose de ASTS daba +0,02 $ al espectro porque solo copiaba la cifra de
las acciones emitidas por derechos de prioridad (14,2 M$). El acuerdo con Ligado da
derechos sobre «up to 45 MHz» de banda L; con la venta SpaceX–EchoStar de AWS-4 + H-block
(17.000 M$ por 50 MHz nacionales, 8-sep-2025) la regla fija da 45 × 340 = 15.300 M$ de hoy,
antes de la probabilidad por estado regulatorio.
"""

from __future__ import annotations

import pytest

from app.services.expert_team import sotp_rules
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.sotp_valuer import SOTP_VALUER_NAME, parse_proposal
from tests.test_sotp_agents import ANCHORS, _good

LIGADO = ("AST entered into an agreement with Ligado for usage rights to up to 45 MHz of L-band spectrum, "
          "subject to FCC approval.")


def _ledger() -> EvidenceLedger:
    ledger = EvidenceLedger()
    ledger.add(expert=SOTP_VALUER_NAME, tool="sotp_anchors", source={"table": "financial_facts"}, data={})
    ledger.add(expert=SOTP_VALUER_NAME, tool="value_drivers",
               source={"table": "value_drivers", "title": "8-K", "url": "https://example.com/8k", "date": "2026-05-01"},
               data={"text": "Definitive agreement with Operator A: contracted backlog of $1.2 billion over 6 years. "
                             "12,000,000 Class B shares are exchangeable. " + LIGADO})
    return ledger


def test_regla_de_espectro_por_comparables():
    low, base, high, formula, sources = sotp_rules.spectrum_value(45, "mss")
    assert (round(low), round(base), round(high)) == (15_300, 15_300, 20_700)
    assert "SpaceX–EchoStar" in formula and "AT&T–EchoStar" in formula
    assert {s["url"] for s in sources} == {c["url"] for c in sotp_rules.SPECTRUM_COMPARABLES}
    assert round(sotp_rules.spectrum_value(30, "terrestre")[1]) == 13_800  # 30 MHz × 460 M/MHz
    assert round(sotp_rules.spectrum_value(10, "otra")[1]) == 3_400  # banda desconocida -> «mss»


def test_el_espectro_con_mhz_citados_se_valora_por_comparables_y_probabilidad():
    proposal = _good()
    proposal["assets"] = [{"name": "Espectro banda L (Ligado)", "status": "contratado", "value_millions": None,
                           "mhz": 45, "band": "mss", "quote": "usage rights to up to 45 MHz of L-band spectrum",
                           "citation": "ev-2", "why": "acuerdo pendiente de la FCC"}]
    model, problems = parse_proposal(proposal, _ledger(), ANCHORS)
    assert problems == [] and model is not None
    spectrum = next(p for p in model["parts"] if p["name"].startswith("Espectro"))
    assert spectrum["value"] == pytest.approx(15_300) and spectrum["probability"] == 0.6
    assert "espectro por comparables" in spectrum["why"]["value"] and "45 MHz" in spectrum["why"]["value"]
    assert any("echostar" in (s.get("url") or "") for s in spectrum["sources"])


def test_mhz_que_no_estan_en_la_cita_no_se_inventan():
    proposal = _good()
    proposal["assets"] = [{"name": "Espectro", "status": "contratado", "mhz": 60, "band": "mss",
                           "quote": "up to 60 MHz", "citation": "ev-2"}]
    model, problems = parse_proposal(proposal, _ledger(), ANCHORS)
    assert problems == [] and model is not None
    assert not any(p["name"] == "Espectro" for p in model["parts"])
    assert any(u["name"] == "Espectro" for u in model["unvalued"])
