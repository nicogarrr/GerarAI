"""Guardia de cifras de la tesis v2: que no se pierda ningún dato.

Antes (8-nov-2026, 22 tesis de tesis-3): 14 salían «stripped» y la guardia borraba en silencio 194 cifras,
también las que estaban en los documentos o eran el valor de un marcador; en 12 tesis eran falsos positivos
de «plan 10b5-1» o «EX-99.1» (nombres de reglas y anexos, no cifras).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from app.services.expert_team import thesis_v2 as T
from tests.test_thesis_v2 import _ctx

PASSAGE = {"group": "negocio", "document": "Informe anual 2025", "url": "https://example.com/ar2025.pdf",
           "date": "2026-03-01", "text": "Recurring revenue reached 90% of total sales, up from 1,234.5 million."}


def _with_passages(ctx):
    return replace(ctx, passages=[PASSAGE])


def test_nombres_de_reglas_y_anexos_no_son_cifras():
    for text in ("vendió con un plan 10b5-1 y lo comunicó en el Form 4",
                 "lo anunció en el EX-99.1 del 8-K y en el Exhibit 10.2",
                 "según la Rule 10b-5, la Section 16 y el Schedule 13D/A del DEF 14A y el S-3"):
        assert T.loose_numbers(text) == [], text


def test_cifra_igual_a_un_marcador_se_convierte_en_ese_marcador():
    ctx = _ctx()
    markers = T.thesis_markers(ctx)
    g = T.FigureGuard()
    out = T.recover_figures("Cotiza a 60,00 € por acción.", markers, [], {}, g)
    assert out == "Cotiza a {{punto.precio}} por acción."
    assert g.to_markers == [{"cifra": "60,00 €", "marcador": "punto.precio"}]


def test_cifra_literal_de_un_pasaje_queda_con_su_documento():
    extra: dict[str, str] = {}
    g = T.FigureGuard()
    out = T.recover_figures("Los ingresos recurrentes son el 90 % del total, frente a 1.234,5 M.", {},
                            [PASSAGE], extra, g)
    assert T.loose_numbers(out) == []
    assert sorted(extra.values()) == ["1.234,5 M", "90 %"]
    assert {s["documento"] for s in g.to_sources} == {"Informe anual 2025"}
    assert T.render({"x": out}, extra)["x"] == "Los ingresos recurrentes son el 90 % del total, frente a 1.234,5 M."


def test_cifra_sin_fuente_se_quita_y_queda_contada():
    g = T.FigureGuard()
    out = T.recover_figures("Crece un 12 % y vale 7 veces.", {}, [PASSAGE], {}, g)
    assert T.loose_numbers(out) == ["12 %", "7 veces"]  # sin fuente: la guardia la verá
    assert g.to_sources == [] and g.to_markers == []


def _reply(text):
    async def reasoner(system, user, max_tokens, task):
        keys = [s["clave"] for s in json.loads(user)["secciones"]]
        return json.dumps({"sections": dict.fromkeys(keys, text), "probabilidades": "sesgo_bajista",
                           "probabilidades_razon": "riesgo"})
    return reasoner


def test_write_thesis_acepta_cifras_con_fuente_a_la_primera_y_no_las_borra():
    ctx = _with_passages(_ctx())
    text = "El precio de 60,00 € y un 90 % de ingresos recurrentes, plan 10b5-1 incluido."
    res = asyncio.run(T.write_thesis(reasoner=_reply(text), ctx=ctx))
    assert res.status == "ok" and res.llm_calls == 2  # sin reintentos
    rendered = T.render(res.sections, {**T.thesis_markers(ctx), **res.figure_markers})
    assert all("60,00 €" in v and "90 %" in v and "10b5-1" in v for v in rendered.values())
    assert res.guard["quitadas"] == 0 and res.guard["a_documento"] == 1
    assert res.guard["detalle_documento"][0]["documento"] == "Informe anual 2025"


def test_las_quitadas_se_registran_y_se_ven_en_los_avisos(monkeypatch):
    ctx = _with_passages(_ctx())
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 1)
    res = asyncio.run(T.write_thesis(reasoner=_reply("Un 90 % recurrente y crece un 12 %."), ctx=ctx))
    assert res.status == "stripped"
    assert res.guard["quitadas"] == len(res.sections) and all(r.endswith("12 %") for r in res.guard["detalle_quitadas"])
    doc = {"sections": res.sections, "figure_markers": res.figure_markers, "guard": res.guard}
    shown = T.present(ctx, doc, T.thesis_markers(ctx))
    assert any(w.startswith("Guardia de cifras:") and "12 %" in w for w in shown["warnings"])
    assert all("90 %" in s["text"] for s in shown["sections"])


def test_tesis_stripped_de_la_guardia_anterior_se_rehace():
    ctx = _ctx()
    fp = T.thesis_fingerprint(ctx)
    secs = {k: "texto {{punto.precio}}" for k, *_ in T.active_sections(ctx)}
    calls = {"n": 0}

    async def count(system, user, max_tokens, task):
        calls["n"] += 1
        return await _reply("texto {{punto.precio}}")(system, user, max_tokens, task)

    res = asyncio.run(T.write_thesis(reasoner=count, ctx=ctx,
                                     cached={"fingerprint": fp, "sections": secs, "status": "stripped"}))
    assert res.status == "ok" and calls["n"] == 2
    again = asyncio.run(T.write_thesis(reasoner=count, ctx=ctx, cached={
        "fingerprint": fp, "sections": secs, "status": "stripped", "guard": {"quitadas": 1}}))
    assert again.status == "cached" and calls["n"] == 2
