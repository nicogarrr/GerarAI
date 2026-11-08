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
    assert Q.non_literal(body, Q.evidence_sources([PASSAGE])) == []


def test_traduccion_presentada_como_cita_se_rechaza():
    body = "Según el 10-K, «esperamos que los acuerdos mayoristas generen ingresos recurrentes desde 2026»."
    assert len(Q.non_literal(body, Q.evidence_sources([PASSAGE]))) == 1


def test_elipsis_y_mayusculas_no_rompen_la_cita_literal():
    body = "La empresa dice: «we expect our wholesale agreements … beginning in fiscal 2026»."
    assert Q.non_literal(body, Q.evidence_sources([PASSAGE])) == []


def test_ultimo_recurso_quita_las_comillas_y_lo_registra():
    body = "Según el 10-K, «esperamos que los acuerdos mayoristas generen ingresos recurrentes»."
    out, touched = Q.unquote_non_literal(body, Q.evidence_sources([PASSAGE]))
    assert "«" not in out and "esperamos que los acuerdos" in out and len(touched) == 1


OTHER = {"group": "riesgos", "document": "Q3 2026 earnings release", "url": "https://ir.example.com/q3",
         "date": "2026-10-30", "text": "Margins improved on lower freight costs. Demand remained resilient in Europe."}


def test_elipsis_que_junta_documentos_distintos_se_rechaza():
    """Antes (#4863, medido por el auditor): con la evidencia aplanada, un trozo del 10-K + «…» + un trozo de la
    nota de resultados pasaba como cita literal."""
    ev = Q.evidence_sources([PASSAGE, OTHER])
    body = "La empresa dice: «we expect our wholesale agreements … demand remained resilient in Europe»."
    assert Q.non_literal(body, ev) != []
    assert Q.literal_problems(body, ev)[0][1] == "junta trozos de documentos distintos"
    # Cada trozo por separado sí está, cada uno en su documento:
    assert Q.non_literal("Según el 10-K, «we expect our wholesale agreements to generate recurring revenue».", ev) == []
    assert Q.non_literal("La nota de resultados dice «demand remained resilient in Europe».", ev) == []


def test_elipsis_con_trozos_en_orden_invertido_se_rechaza():
    ev = Q.evidence_sources([PASSAGE])
    body = "Según el 10-K, «beginning in fiscal 2026 … we expect our wholesale agreements»."
    assert Q.literal_problems(body, ev) == [(
        "beginning in fiscal 2026 … we expect our wholesale agreements",
        "los trozos no están en el orden del documento o se solapan")]
    assert Q.non_literal("Según el 10-K, «we expect our wholesale agreements … beginning in fiscal 2026».", ev) == []


def test_elipsis_con_trozos_solapados_se_rechaza():
    ev = Q.evidence_sources([PASSAGE])
    # «wholesale agreements to generate» y «to generate recurring» se solapan en el documento: no son dos trozos.
    body = "Según el 10-K, «we expect our wholesale agreements to generate … to generate recurring revenue»."
    assert Q.non_literal(body, ev) != []


def test_la_cita_se_busca_en_el_documento_atribuido_no_en_otro():
    ev = Q.evidence_sources([PASSAGE, OTHER])
    # Está literal, pero en la nota de resultados, no en el 10-K al que se atribuye.
    body = "Según el 10-K, «margins improved on lower freight costs»."
    assert Q.non_literal(body, ev) == ["margins improved on lower freight costs"]


def test_cita_atribuida_a_un_documento_que_no_esta_en_la_evidencia_se_rechaza():
    ev = Q.evidence_sources([PASSAGE])
    body = "Según el 10-Q del tercer trimestre, «we expect our wholesale agreements to generate recurring revenue»."
    assert Q.literal_problems(body, ev) == [("we expect our wholesale agreements to generate recurring revenue",
                                             "el documento al que se atribuye no está en la evidencia")]
    out, touched = Q.unquote_non_literal(body, ev)
    assert "«" not in out and len(touched) == 1


def test_el_informe_anual_es_el_10k_y_el_titulo_tambien_atribuye():
    ev = Q.evidence_sources([PASSAGE, OTHER])
    assert Q.non_literal(f"El informe anual dice «{TEXT}»", ev) == []
    assert Q.non_literal("En la Q3 2026 earnings release: «margins improved on lower freight costs».", ev) == []


def test_la_traduccion_detras_no_cuenta_como_atribucion():
    ev = Q.evidence_sources([PASSAGE])
    body = f"Según el 10-K, «{TEXT}» (traducción: «según el informe trimestral, esperamos ingresos»)."
    assert Q.non_literal(body, ev) == []


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
