"""Las citas literales de una respuesta JSON no cuentan como «inglés» del modelo.

Antes (8-nov-2026, POOL con el modelo de la app): el Recopilador devolvió su inventario con las citas del
10-K en inglés en ``source_quote``; el guardia lo rechazó dos veces por inglés y el inventario se perdió.
"""
import json

from app.services.llm_output_guard import REASON_ENGLISH, inspect_response_text

QUOTE = ("We are the world's largest wholesale distributor of swimming pool supplies, equipment and related "
         "leisure products and we expect sales to grow in the coming years as the installed base ages.")


def test_citas_literales_en_ingles_no_rechazan_un_json_en_espanol():
    body = {"drivers": [{"name": "Base instalada de piscinas", "description": "La base instalada envejece y "
                         "eso sostiene la demanda de reposición durante los próximos años.",
                         "source_quote": QUOTE, "citations": [{"cita": QUOTE}]}]}
    assert REASON_ENGLISH not in inspect_response_text(json.dumps(body, ensure_ascii=False))


def test_la_prosa_en_ingles_del_modelo_sigue_rechazada():
    body = {"drivers": [{"name": "Installed base", "description": QUOTE, "source_quote": QUOTE}]}
    assert REASON_ENGLISH in inspect_response_text(json.dumps(body))
