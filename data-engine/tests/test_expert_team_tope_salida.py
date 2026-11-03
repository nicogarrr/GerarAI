"""Equipo de expertos: tope de salida que cabe el razonamiento del modelo.

Prueba real 2026-11-03 (cerebro-real-2, OpenCode Go, deepseek-v4.1-flash con
razonamiento): con ``max_tokens=900`` (que el chat sube a su mínimo de 2.600)
el experto fiscal acabó con finish_reason=length a los 2.600 tokens y el
fundamental devolvió un mensaje vacío (todo el tope se fue en razonar): en
la respuesta salían «sin datos suficientes» y «no disponible». En la tesis
(proveedor sin ese mínimo) el tope de 900 es aún más corto. Los tokens de una
respuesta cortada se pagan y se tiran; con un tope mayor solo se gasta lo que
el modelo necesita (las respuestas completas medidas usan 360–2.130).
"""

from app.core.config import get_settings
from app.services.expert_team.experts import ExpertSpec
from app.services.expert_team.roster import default_experts


def test_every_expert_has_room_beyond_the_chat_floor():
    floor = get_settings().chat_go_min_output_tokens
    for spec in default_experts():
        assert spec.max_tokens >= floor + 1000, spec.name


def test_default_cap_covers_a_reasoning_model():
    assert ExpertSpec(name="x", prompt_name="expert_fundamental", tools=()).max_tokens >= 3600
