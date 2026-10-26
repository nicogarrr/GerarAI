"""Replay OPCIONAL de las respuestas reales del ensayo run1 (26-oct, scratch).

Las capturas son artefactos privados fuera del repo. Para activar el replay:
    THESIS_RUN1_REPLAY_JSON=/ruta/a/live_run1_raw_responses.json pytest tests/test_offline_run1_replay.py
Sin la variable (o si el artefacto no existe) estos tests se omiten. Limites:
fixtures de pack/titulares sinteticas; no prueban aceptacion del pack real
ni anclaje de cifras de run1 (el request deep capturado se perdio).
"""
import json
import os
from pathlib import Path

import pytest

from app.services.thesis_deep_narrative import _NUMBER_RE, _norm_number, _validate_sections
from app.services.thesis_news_narrative import validate_output


@pytest.fixture(scope="module")
def run1_capture():
    raw = os.environ.get("THESIS_RUN1_REPLAY_JSON")
    if not raw or not Path(raw).exists():
        pytest.skip("replay run1 no disponible (define THESIS_RUN1_REPLAY_JSON)")
    items = json.loads(Path(raw).read_text())
    return json.loads(items[0]["text"]), json.loads(items[1]["text"])


def _headlines():
    ids = ["news:225356", "news:222453", "news:222457", "news:224746",
           "news:225357", "news:222455", "news:222456", "news:222454"]  # ids reales observados
    return [
        {"id": nid, "titulo": f"Titular sintetico {nid}", "tipo": "titular original",
         "medio": "waterford-news.ie" if i % 2 == 0 else "Yahoo Finance",
         "fecha": f"2026-10-{20 - i:02d}T08:00:00+00:00",
         "origen_fecha": "source", "url": f"https://example-medio-{i}.test/pieza",
         "pendiente_actualizacion": False}
        for i, nid in enumerate(ids)
    ]


def _facts_sinteticas(deep_raw):
    """Fixture SINTETICA para ejercitar la regla URL sobre la prosa real."""
    numeros = set()
    for sec in deep_raw["secciones"]:
        for p in sec["parrafos"]:
            numeros.update(_NUMBER_RE.findall(p))
    tokens = sorted(t for t in numeros if _norm_number(t) is not None)
    ids = [f"f{chr(ord('A') + i)}" for i in range(23)]
    facts = [{"id": fid, "texto": "Dato registrado: " + " ".join(tokens[i::23]) + " .",
              "fuente": "Motor de valoracion interno (seccion 13 del memo)."}
             for i, fid in enumerate(ids)]
    facts += [
        {"id": "fX", "texto": 'Yahoo Finance publicó el 11 de octubre de 2026 "T A".',
         "fuente": "https://finance.yahoo.com/news/a"},
        {"id": "fY", "texto": 'Yahoo Finance publicó el 20 de octubre de 2026 "T B".',
         "fuente": "https://finance.yahoo.com/news/b"},
        {"id": "fZ", "texto": 'waterford-news ie publicó "T C", visto en GDELT el 13 de julio de 2026.',
         "fuente": "https://waterford-news.ie/c"},
        {"id": "fAA", "texto": 'Yahoo Finance publicó el 9 de octubre de 2026 "T D".',
         "fuente": "https://finance.yahoo.com/news/d"},
        {"id": "fAB", "texto": 'Yahoo Finance publicó el 9 de octubre de 2026 "T E".',
         "fuente": "https://finance.yahoo.com/news/e"},
    ]
    return facts


def test_replay_regla_cantidades_sobre_texto_news_real(run1_capture):
    """La regla de cantidades solo depende de la prosa: el texto news real
    («un tercero» sustantivo) ya no se rechaza. Titulares: fixture sintetica."""
    news_raw, _ = run1_capture
    sections = validate_output(news_raw, _headlines())
    assert "Alcance" in [s["titulo"] for s in sections]


def test_replay_regla_url_intacta_respuesta_deep_real_sigue_rechazada(run1_capture):
    """La prosa deep real contiene «waterford-news.ie» y SIGUE rechazada:
    el correctivo actua en la presentacion del pack, no en el validador."""
    _, deep_raw = run1_capture
    sections, rule = _validate_sections(deep_raw, _facts_sinteticas(deep_raw))
    assert sections is None and rule == "url_detectada"


def test_replay_prosa_con_nombre_normalizado_pasa_regla_url(run1_capture):
    """Variante de la prosa real con el medio ya normalizado
    («waterford-news ie», tal como lo veria el modelo tras el fix): la regla
    URL no se dispara. Alcance: solo la regla URL con fixture sintetica."""
    _, deep_raw = run1_capture
    raw = json.loads(json.dumps(deep_raw))
    for sec in raw["secciones"]:
        sec["parrafos"] = [p.replace("waterford-news.ie", "waterford-news ie")
                           for p in sec["parrafos"]]
    sections, rule = _validate_sections(raw, _facts_sinteticas(deep_raw))
    assert rule is None
