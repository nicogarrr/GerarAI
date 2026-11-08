"""SOTP con la divisa de cada cifra (hallazgo del auditor, «Fórmulas: monedas en SOTP»).

Antes: las anclas no llevaban divisa; un backlog en CAD se sumaba tal cual a un modelo en USD y la
etiqueta decía siempre «$/acción». Ahora cada ancla guarda la divisa de su cita, la fórmula de
ingresos la enseña, una cifra en otra divisa se aparta con su motivo (no se mezclan monedas) y la
etiqueta por acción lleva la divisa del modelo."""
from __future__ import annotations

import json

from app.services.expert_team.sotp_valuer import parse_proposal
from tests.test_sotp_agents import ANCHORS, _good, _ledger


def _with_currency(ccy: str | None) -> dict:
    raw = json.loads(json.dumps(_good()))
    raw["segments"][0]["anchor"]["currency"] = ccy
    return raw


def test_ancla_en_la_divisa_del_modelo_lo_dice_en_la_formula() -> None:
    model, problems = parse_proposal(_with_currency("USD"), _ledger(), ANCHORS)
    assert problems == []
    assert "Divisa: USD (la de la cita)" in model["parts"][0]["why"]["revenue"]


def test_ancla_sin_divisa_dice_de_donde_sale() -> None:
    model, _ = parse_proposal(_with_currency(None), _ledger(), ANCHORS)
    assert "la cita no la dice; se toma la de los informes" in model["parts"][0]["why"]["revenue"]


def test_ancla_en_otra_divisa_no_se_suma_y_se_ve_por_que() -> None:
    model, _ = parse_proposal(_with_currency("CAD"), _ledger(), ANCHORS)
    names = [p["name"] for p in (model or {}).get("parts") or []]
    assert "Operadora A (EE. UU.)" not in names
    reasons = {u["name"]: u["reason"] for u in (model or {}).get("unvalued") or []}
    assert "CAD" in reasons.get("Operadora A (EE. UU.)", "") and "USD" in reasons["Operadora A (EE. UU.)"]
