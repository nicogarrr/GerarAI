"""Narrativa extensa de tesis redactada por el modelo (OpenCode Go).

El modelo SI escribe, pero anclado al paquete determinista de hechos: cualquier
cifra fuera del paquete, URL, veredicto de compra/venta, seccion obligatoria
ausente o JSON invalido rechaza la salida y deja la narrativa base intacta.
Sin red ni BD real: proveedor y presupuesto falsos.
"""

import json
from types import SimpleNamespace

from app.services import thesis_deep_narrative as svc


def _company():
    return SimpleNamespace(ticker="META", name="Meta Platforms", currency="USD")


def _valuation():
    return {
        "status": "ok",
        "current_price": 733.12,
        "base_value": 800.0,
        "bear_value": 600.0,
        "bull_value": 950.0,
        "expected_value": 810.0,
        "margin_of_safety": 0.091,
        "missing_inputs": ["daily_active_people"],
        "reverse_dcf": {"required_revenue_growth": 0.125},
    }


def _long_term_model():
    return {
        "framework": {
            "key": "advertising_platform",
            "label": "Advertising / attention platform",
            "primary_question": "Can ad impressions, price per ad and daily engagement compound advertising revenue without eroding the user experience?",
        },
        "missing_mandatory_drivers": [],
    }


NEWS = [{
    "id": 17,
    "source_headline": "Meta eleva el capex de IA y el mercado se lo cuestiona",
    "date": "2026-10-08T10:00:00+00:00",
    "source": "Medio",
    "date_source": "source",
    "url": "https://example.org/news/123",
}]


def _facts():
    return svc.fact_pack(_company(), _valuation(), _long_term_model(), "La publicidad sigue monetizando.", NEWS)


def _model_output(facts, **overrides):
    ids = [f["id"] for f in facts]
    out = {
        "secciones": [
            {"id": "que_sabemos", "titulo": "Lo que sabemos",
             "parrafos": ["Meta Platforms cotiza a 733.12 USD frente a un escenario base del modelo de 800.00 USD por accion, con un rango que va del escenario pesimista de 600.00 USD al optimista de 950.00 USD y un valor esperado de 810.00 USD. Ese cruce deja un margen de seguridad del 9,1 % respecto del valor esperado registrado en esta tesis, siempre con los supuestos del motor interno."],
             "fact_ids": ids[:7]},
            {"id": "como_se_construye", "titulo": "Como se construye la valoracion",
             "parrafos": ["Con los supuestos de este DCF inverso, el precio actual exigiria un crecimiento de ingresos del 12,5 % anual; esa exigencia se interpreta dentro del marco Advertising / attention platform, que ordena los drivers de impresiones publicitarias, precio por anuncio y audiencia diaria en lugar de metricas de pagos."],
             "fact_ids": ids[7:10]},
            {"id": "fuentes_y_anclaje", "titulo": "Fuentes y anclaje",
             "parrafos": ["Las cifras de valoracion salen del motor interno de la seccion 13 del memo y el titular citado lo publico Medio el 8 de octubre de 2026; un titular acredita su publicacion, no que sea cierto, y la disponibilidad de un filing no implica la verificacion de su contenido."],
             "fact_ids": ids[:2] + ids[-1:]},
            {"id": "lo_que_no_sabemos", "titulo": "Lo que aun no sabemos",
             "parrafos": ["Falta el input daily_active_people: mientras no este, la valoracion queda provisional y no debe leerse como veredicto publicable, y la hipotesis registrada sobre la monetizacion publicitaria sigue siendo una interpretacion pendiente de contraste con el proximo filing."],
             "fact_ids": ids[8:11]},
        ]
    }
    out.update(overrides)
    return out


class Provider:
    name = "fake"

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0
        self.requests = []

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(
            text=json.dumps(self.payload, ensure_ascii=False),
            model="deepseek-v4.1-flash",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )


import pytest


@pytest.fixture
def context(monkeypatch):
    monkeypatch.delenv("THESIS_DEEP_NARRATIVE_LLM_ENABLED", raising=False)
    records = []

    class Budget:
        def can_spend(self, db, amount):
            return True

        def record(self, db, model, workflow, cost, tokens, *, commit):
            records.append((model, workflow, cost, tokens, commit))

        def estimate_cost_eur(self, model, input_tokens, output_tokens):
            return 0

    monkeypatch.setattr(svc, "BudgetController", Budget)
    return SimpleNamespace(flush=lambda: None), records


def _call(context, provider, **kw):
    db, _ = context
    return svc.maybe_deep_narrative(
        db, _company(), _valuation(), _long_term_model(),
        "La publicidad sigue monetizando.", NEWS, provider=provider, **kw)


def test_deep_narrative_returns_sections_with_code_owned_citations_and_model_trace(context):
    facts = _facts()
    provider = Provider(payload=_model_output(facts))
    result = _call(context, provider)
    assert result is not None
    assert result["model"] == "deepseek-v4.1-flash"
    assert result["provider"] == "fake"
    titles = [s["titulo"] for s in result["sections"]]
    assert titles[:4] == ["Lo que sabemos", "Como se construye la valoracion", "Fuentes y anclaje", "Lo que aun no sabemos"]
    assert titles[-1] == "Salvedad"
    # Citas puestas por el codigo con los localizadores reales del paquete.
    assert any("Fuentes citadas:" in p and "https://example.org/news/123" in p for p in result["sections"][2]["parrafos"])
    # La ruta pide el workflow profundo, no el selector de 200 tokens.
    assert provider.requests[0].task == "deep_thesis"
    assert provider.requests[0].max_tokens == 4000
    db, records = context
    assert records == [("deepseek-v4.1-flash", "thesis_deep_narrative", 0, 150, False)]


def test_rag_pack_exposes_only_locator_never_chunk_text(context):
    rag = [{"type": "knowledge_chunk", "title": "Carta de Fundsmith 2024",
            "knowledge_document_id": 42, "text": "TEXTO INTERNO QUE NO DEBE SALIR"}]
    facts = svc.fact_pack(_company(), _valuation(), _long_term_model(), None, [], None, rag)
    joined = json.dumps(facts, ensure_ascii=False)
    assert "TEXTO INTERNO QUE NO DEBE SALIR" not in joined
    assert any("Fundsmith" in f["texto"] and "Biblioteca 42" in f["fuente"] for f in facts)


def test_unanchored_number_is_rejected_and_falls_back(context):
    facts = _facts()
    bad = _model_output(facts)
    bad["secciones"][0]["parrafos"] = ["La empresa cotiza a 999.99 USD con un margen enorme para el escenario base registrado en esta tesis provisional."]
    provider = Provider(payload=bad)
    result = _call(context, provider)
    assert result is None
    assert provider.calls == 2  # un reintento y fuera


def test_url_verdict_and_missing_mandatory_section_are_rejected(context):
    facts = _facts()
    with_url = _model_output(facts)
    with_url["secciones"][2]["parrafos"] = ["Segun https://evil.example.com la empresa vale mucho mas que el escenario base del modelo registrado en esta tesis."]
    assert _call(context, Provider(payload=with_url)) is None

    verdict = _model_output(facts)
    verdict["secciones"][0]["parrafos"] = ["Recomendamos comprar porque el escenario base de 800.00 USD supera al precio actual registrado en el modelo de valoracion."]
    assert _call(context, Provider(payload=verdict)) is None

    missing = _model_output(facts)
    missing["secciones"] = [s for s in missing["secciones"] if s["id"] != "lo_que_no_sabemos"]
    assert _call(context, Provider(payload=missing)) is None


def test_flag_off_disabled_provider_budget_and_error_all_fail_closed(context, monkeypatch):
    facts = _facts()
    monkeypatch.setenv("THESIS_DEEP_NARRATIVE_LLM_ENABLED", "0")
    assert _call(context, Provider(payload=_model_output(facts))) is None
    monkeypatch.delenv("THESIS_DEEP_NARRATIVE_LLM_ENABLED")

    disabled = Provider(payload=_model_output(facts))
    disabled.name = "disabled"
    assert _call(context, disabled) is None

    class BrokeBudget:
        def can_spend(self, db, amount):
            return False
    monkeypatch.setattr(svc, "BudgetController", BrokeBudget)
    assert _call(context, Provider(payload=_model_output(facts))) is None

    assert _call(context, Provider(error=RuntimeError("red"))) is None


def test_short_or_template_like_output_is_rejected(context):
    facts = _facts()
    short = _model_output(facts)
    for section in short["secciones"]:
        section["parrafos"] = [p[:60] for p in section["parrafos"][:1]]
    assert _call(context, Provider(payload=short)) is None


def test_is_sin_datos_marker():
    assert svc.is_sin_datos([{"titulo": "Análisis narrativo", "parrafos": ["Sin datos"]}])
    assert not svc.is_sin_datos([{"titulo": "X", "parrafos": ["Contenido real de la narrativa."]}])
    assert not svc.is_sin_datos(None)
