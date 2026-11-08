"""Citas literales en la tesis v2: en el idioma original y con la traducción al lado.

Antes (8-nov-2026): 15 de 37 citas atribuidas no estaban literales en los documentos; 11 eran traducciones
al español presentadas como cita.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from app.services.expert_team import quote_check as Q
from app.services.expert_team import thesis_v2 as T
from tests.test_thesis_v2 import _ctx

TEXT = "We expect our wholesale agreements to generate recurring revenue beginning in fiscal 2026."
PASSAGE = {"group": "guia", "document": "10-K 2025", "url": "https://sec.gov/x", "date": "2026-02-20",
           "text": "Outlook. " + TEXT + " Other risks apply to the business."}


def test_cita_literal_en_ingles_con_traduccion_al_lado_pasa():
    body = f"Según el 10-K, «{TEXT}» (traducción: «esperamos que los acuerdos mayoristas generen ingresos recurrentes»)."
    assert Q.non_literal(body, [PASSAGE["text"]]) == []


def test_traduccion_presentada_como_cita_se_rechaza():
    body = "Según el 10-K, «esperamos que los acuerdos mayoristas generen ingresos recurrentes desde 2026»."
    assert len(Q.non_literal(body, [PASSAGE["text"]])) == 1


def test_elipsis_y_mayusculas_no_rompen_la_cita_literal():
    body = "La empresa dice: «we expect our wholesale agreements … beginning in fiscal 2026»."
    assert Q.non_literal(body, [PASSAGE["text"]]) == []


def test_ultimo_recurso_quita_las_comillas_y_lo_registra():
    body = "Según el 10-K, «esperamos que los acuerdos mayoristas generen ingresos recurrentes»."
    out, touched = Q.unquote_non_literal(body, [PASSAGE["text"]])
    assert "«" not in out and "esperamos que los acuerdos" in out and len(touched) == 1


def _reply(texts):
    calls = {"n": 0}

    async def reasoner(system, user, max_tokens, task):
        payload = json.loads(user)
        keys = [s["clave"] for s in payload["secciones"]]
        text = texts[min(calls["n"], len(texts) - 1)]
        calls["n"] += 1
        return json.dumps({"sections": dict.fromkeys(keys, text), "probabilidades": "sesgo_bajista",
                           "probabilidades_razon": "riesgo"})
    return reasoner, calls


def test_write_thesis_pide_reintento_por_cita_traducida_y_acepta_la_literal():
    ctx = replace(_ctx(), passages=[PASSAGE])
    bad = "Según el 10-K, «esperamos que los acuerdos mayoristas generen ingresos recurrentes»."
    good = f"Según el 10-K, «{TEXT}» (traducción: «esperamos ingresos recurrentes de los acuerdos»)."
    reasoner, calls = _reply([bad, good, good, good])
    res = asyncio.run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert res.status == "ok" and calls["n"] == 3  # a: mala y buena; b: buena
    assert any("citas que no están literales" in p for p in res.problems)
    assert all(TEXT in v for v in res.sections.values())
    assert res.guard["citas_no_literales"] == 0
    assert "CITAS" in T.PROMPT


def test_si_no_se_arregla_deja_de_ser_cita_y_se_ve_en_avisos(monkeypatch):
    ctx = replace(_ctx(), passages=[PASSAGE])
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 1)
    bad = "Según el 10-K, «esperamos que los acuerdos mayoristas generen ingresos recurrentes»."
    reasoner, _ = _reply([bad])
    res = asyncio.run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert all("«" not in v for v in res.sections.values())
    assert res.guard["citas_no_literales"] == len(res.sections)
    shown = T.present(ctx, {"sections": res.sections, "guard": res.guard}, T.thesis_markers(ctx))
    assert any("estilo indirecto" in w for w in shown["warnings"])


def test_pregunta_retorica_entre_comillas_no_es_una_cita():
    """Antes (8-nov-2026, AMZN): «¿qué tiene que ocurrir para que rentabilice el coste del capital?» se trataba
    como cita no literal, se pedía reintento y acababa contada como cita quitada."""
    from app.services.expert_team import quote_check as Q

    text = "La pregunta es «¿qué tiene que ocurrir para que rentabilice el coste del capital?» y la respuesta…"
    assert Q.quotes(text) == []
    assert Q.non_literal(text, ["otra cosa"]) == []
