"""Tesis v2 de nivel comité: marcadores del código, validador de números libres, caché por huella,
umbrales falsables y la lectura por la API."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.services.expert_team import thesis_v2 as T
from app.services.shareholder_irr_service import run_valuation
from app.valuation import shareholder_irr as E
from app.valuation import shareholder_irr_rules as R


def _ctx() -> T.ThesisContext:
    sp = E.StartingPoint(price=60.0, shares_diluted=180.0, revenue=6400.0, ebitda=1450.0, debt=3000.0,
                         currency="EUR")
    hist = R.History(years=[2021, 2022, 2023, 2024], revenue=[5000.0, 5600.0, 6000.0, 6400.0],
                     earnings=[1100.0, 1250.0, 1300.0, 1450.0], operating_cash_flow=[900.0, 1000.0, 1050.0, 1200.0],
                     capex=[-300.0, -320.0, -330.0, -350.0], dividends=[-100.0, -110.0, -120.0, -130.0],
                     buybacks=[0.0, -200.0, -100.0, -150.0], acquisitions=[-200.0, -250.0, -150.0, -300.0])
    val = run_valuation(sp, hist, peer_multiples=[12.0, 14.0, 16.0], discount_rate=0.09)
    val.update({"status": "ok", "as_of": "2026-11-08", "fingerprint": "f" * 64, "warnings": [], "peers": [],
                "method": {"chosen": "tir_ev_ebitda", "discarded": {"sotp": "solo publica ingresos por segmento"}},
                "citations": {"annual": {}, "price": {"document": "Cierre"}}})
    rows = [{"year": y, "revenue": r, "growth": None if i == 0 else r / hist.revenue[i - 1] - 1,
             "margin": e / r, "conversion": 0.5, "shares": 180.0, "fcf": 600.0, "fcf_per_share": 3.3,
             "ebitda": e, "net_income": None, "dividends": None, "buybacks": None, "acquisitions": None, "roic": None}
            for i, (y, r, e) in enumerate(zip(hist.years, hist.revenue, hist.earnings, strict=True))]
    sw = T.kill_switches(val, rows)
    return T.ThesisContext("TEST", "Test SA", val, rows, [], sw, 0.03, [], {})


def test_marcadores_salen_del_calculo():
    ctx = _ctx()
    m = T.thesis_markers(ctx)
    assert m["punto.precio"] == "60,00 €"
    assert m["esc.base.tir10"].endswith("%")
    base10 = ctx.valuation["scenarios"]["base"]["horizons"]["10"]["irr"]
    assert m["esc.base.tir10"] == T.pct(base10)
    assert m["comparables.mediana"] == "14,0x"


def test_tablas_descomposicion_y_sensibilidad():
    tabs = T.tables(_ctx())
    rows = {r[0]: r for r in tabs["descomposicion"]["rows"]}
    assert "TIR total" in rows and "Recompras" in rows and "Desapalancamiento" in rows
    assert len(tabs["sensibilidad"]["rows"]) == 5 and len(tabs["sensibilidad"]["head"]) == 6
    assert tabs["metodos"]["rows"][0][1] == "elegido"


def test_kill_switches_son_umbrales_con_estado():
    sw = {s["key"]: s for s in _ctx().switches}
    assert {"crecimiento", "margen", "conversion", "apalancamiento", "precio_alto", "precio_bajo"} <= set(sw)
    assert all(s["status"] in ("ok", "saltado") and s["threshold"] for s in sw.values())


def _reply(ctx, number: bool):
    async def reasoner(system, user, max_tokens, task):
        keys = [s["clave"] for s in json.loads(user)["secciones"]]
        text = "El precio de {{punto.precio}} y una TIR base de {{esc.base.tir10}}." + (" Crece un 12 %." if number else "")
        return json.dumps({"sections": dict.fromkeys(keys, text), "probabilidades": "sesgo_bajista",
                           "probabilidades_razon": "riesgo de ejecución"})
    return reasoner


def test_validador_rechaza_numeros_libres_y_los_quita(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 1)
    res = asyncio.run(T.write_thesis(reasoner=_reply(ctx, True), ctx=ctx))
    assert res.status == "stripped"
    assert all("12" not in v for v in res.sections.values())
    assert res.probability_choice == "sesgo_bajista"


def test_texto_valido_y_cache_por_huella():
    ctx = _ctx()
    res = asyncio.run(T.write_thesis(reasoner=_reply(ctx, False), ctx=ctx))
    assert res.status == "ok" and res.llm_calls == 2
    assert {k for k, *_ in T.active_sections(ctx)} == set(res.sections)

    async def boom(*a):  # noqa: ANN002
        raise AssertionError("no debe llamar al modelo")

    again = asyncio.run(T.write_thesis(reasoner=boom, ctx=ctx, cached={"fingerprint": res.fingerprint,
                                                                         "sections": res.sections}))
    assert again.status == "cached" and again.llm_calls == 0
    rendered = T.render(res.sections, T.thesis_markers(ctx))
    assert "{{" not in "".join(rendered.values()) and "60,00 €" in rendered["introduccion"]


def test_secciones_cubren_las_de_referencia():
    keys = {k for k, *_ in T.SECTIONS}
    for k in ("introduccion", "sector_estrategia", "ventaja_competitiva", "directivos_capital", "contabilidad",
              "valoracion", "riesgos", "pre_mortem", "conclusion", "metodo", "que_vigilar", "historial",
              "comparables", "que_descuenta"):
        assert k in keys


def test_crecimiento_implicito_reproduce_la_tasa():
    ctx = _ctx()
    sp = E.StartingPoint(**{k: ctx.valuation["starting_point"][k] for k in E.StartingPoint.__dataclass_fields__})
    d = E.Drivers(**ctx.valuation["scenarios"]["base"]["drivers"])
    g = T.implied_growth(sp, d, 0.09)
    assert g is not None
    dd = E.Drivers(**{**ctx.valuation["scenarios"]["base"]["drivers"], "organic_growth": g, "organic_growth_late": g})
    assert E.evaluate(sp, dd, (10,))[10].irr == pytest.approx(0.09, abs=1e-6)


def test_ruta_registrada():
    import inspect

    from app.api import router as api
    from app.api.routes.thesis_v2 import router

    assert {getattr(r, "path", "") for r in router.routes} >= {"/{ticker}/thesis-v2", "/{ticker}/shareholder-irr"}
    assert 'include_router(thesis_v2.router, prefix="/companies"' in inspect.getsource(api)


def test_nombres_de_normas_no_son_cifras():
    texto = "Bajo IFRS 16 y la NIC 36, según el 10-K y el Form 20-F del Q3 y desde el 1 de enero, crece un 12 %."
    assert T.loose_numbers(texto) == ["12 %"]
    limpio = T.strip_loose(texto)
    assert "IFRS 16" in limpio and "NIC 36" in limpio and "12" not in limpio


def test_valoracion_no_proyectable_da_umbrales_sin_escenarios():
    ctx = _ctx()
    val = {"status": "not_meaningful", "reason": "PER fuera del rango", "starting_point": ctx.valuation["starting_point"],
           "scenarios": {}, "discount_rate": 0.09}
    sw = T.kill_switches(val, ctx.history)
    assert {s["key"] for s in sw} >= {"dilucion", "crecimiento"}
    ctx2 = T.ThesisContext("BN", "Holding", {**ctx.valuation, **val}, ctx.history, [], sw, None, [], {})
    m = T.thesis_markers(ctx2)
    assert m["valoracion.motivo"] == "PER fuera del rango" and "esc.base.tir10" not in m
    assert T.tables(ctx2)["escenarios"]["rows"] == [["PER fuera del rango"]]


def test_eleccion_de_probabilidades_anidada_en_sections():
    ctx = _ctx()

    async def reasoner(system, user, max_tokens, task):
        keys = [s["clave"] for s in json.loads(user)["secciones"]]
        sec: dict[str, str] = dict.fromkeys(keys, "Texto con {{punto.precio}}.")
        if task.endswith("_b"):
            sec |= {"probabilidades": "uniforme", "probabilidades_razon": "sin sesgo"}
        return json.dumps({"sections": sec})

    res = asyncio.run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert res.probability_choice == "uniforme" and res.probability_reason == "sin sesgo"
    assert "probabilidades" not in res.sections


def test_reintento_solo_pide_lo_pendiente_y_no_borra_lo_valido(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 2)
    seen: list[list[str]] = []

    async def reasoner(system, user, max_tokens, task):
        keys = [s["clave"] for s in json.loads(user)["secciones"]]
        seen.append(keys)
        if len(seen) == 1:  # primer intento de la parte a: una sección con número libre
            sec = dict.fromkeys(keys, "Bien: {{punto.precio}}.") | {"historial": "Crece un 12 %."}
        elif len(seen) == 2:  # reintento perezoso: vacía lo demás
            sec = dict.fromkeys(keys, "") | {"historial": "Crece {{historico.crecimiento}}."}
        else:
            sec = dict.fromkeys(keys, "Bien: {{punto.precio}}.")
        return json.dumps({"sections": sec})

    res = asyncio.run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert seen[1] == ["historial"]
    assert res.status == "ok" and res.sections["historial"] == "Crece {{historico.crecimiento}}."
    assert res.sections["introduccion"] == "Bien: {{punto.precio}}."


def test_parrafos_con_saltos_de_linea_literales():
    sections, _ = T._parse('{"sections": {"introduccion": "Uno.\n\nDos {{punto.precio}}."}}', ["introduccion"])
    assert sections == {"introduccion": "Uno.\n\nDos {{punto.precio}}."}


def test_nombre_sin_sufijo_de_edgar():
    assert T.display_name("BROOKFIELD Corp /ON/") == "BROOKFIELD Corp"
    assert T.display_name("Eurofins Scientific SE") == "Eurofins Scientific SE"


def test_prosa_sin_operador_ni_veces_duplicado():
    ctx = _ctx()
    m = T.thesis_markers(ctx)
    assert not m["vigilar.1.umbral"].startswith(("<", ">", "≤", "≥"))
    assert T.tables(ctx)["vigilar"]["rows"][0][1].startswith("<")
    out = T.render({"a": "cotiza a {{punto.multiplo}} veces el EBITDA"}, {"punto.multiplo": "15,8x"})
    assert out["a"] == "cotiza a 15,8x el EBITDA"


def test_enlace_de_un_clic_al_filing():
    cite = {"source_type": "SEC", "accession": "0001628280-26-003942", "url": "https://www.sec.gov/cgi-bin/browse-edgar?x"}
    assert T.source_link(cite, "1326801") == "https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/"
    assert T.source_link({"source_type": "ESEF", "url": None}, None) is None
    assert T.source_link({"url": "https://filings.xbrl.org/x.zip"}, None) == "https://filings.xbrl.org/x.zip"


def test_supuestos_con_fuente_y_confianza_y_percentil():
    ctx = _ctx()
    tabs = T.tables(ctx)
    rows = {r[0]: r for r in tabs["supuestos"]["rows"]}
    assert rows["Margen objetivo"][-1] in ("alta", "media", "baja")
    assert "tasa base" in rows["Crecimiento orgánico años 1–5"][4]
    assert len(tabs["partida"]["links"]) == len(tabs["partida"]["rows"])
    assert T.implied_percentile(0.03, {"p25": 0.01, "p50": 0.04, "p75": 0.08}) == "entre los percentiles 25 y 50"
    assert tabs["descuenta"]["rows"][0][1] == T.pct(0.03)


def test_kill_switch_sobre_la_guia():
    g = [{"metric": "revenue", "period": "fy2026", "unit": "USD", "low": 9e9, "base": 9.5e9, "high": 1e10},
         {"metric": "eps", "period": "fy2026", "unit": "USD/share", "low": None, "base": 10.0, "high": None},
         {"metric": "capex", "period": "fy2026", "unit": "USD", "low": 1e9, "base": 1e9, "high": 1e9}]
    sw = T.estimate_switches(g, "USD")
    assert [s["key"] for s in sw] == ["guia.revenue.fy2026", "guia.eps.fy2026"]
    assert sw[0]["threshold"] == "< 9.000 M$" and sw[1]["threshold"] == "< 9,50 $"


def test_guia_inverosimil_no_crea_kill_switch():
    g = [{"metric": "operating_income", "period": "fy2026", "unit": "USD", "low": None, "base": 18.5e9, "high": None}]
    annual = {"operating_income": {"2025": {"value": 83e9}}}
    assert T.estimate_switches(g, "USD", annual) == []
    assert T.plausible_guidance({**g[0], "base": 90e9}, annual)
