"""Narrativa extensa de tesis redactada por el modelo (OpenCode Go).

El modelo SI escribe, pero anclado al paquete determinista de hechos: cualquier
cifra fuera del paquete, URL, veredicto de compra/venta, seccion obligatoria
ausente o JSON invalido rechaza la salida y deja la narrativa base intacta.
Sin red ni BD real: proveedor y presupuesto falsos.
"""

import json
import re
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

    def __init__(self, payload=None, error=None, degraded=False, executed_model="deepseek-v4.1-flash", fallback_trail=()):
        self.payload = payload
        self.error = error
        self.degraded = degraded
        self.executed_model = executed_model
        self.fallback_trail = tuple(fallback_trail)
        self.calls = 0
        self.requests = []
        self.model_router = SimpleNamespace(resolve=lambda request: "deepseek-v4.1-flash")

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(
            text=json.dumps(self.payload, ensure_ascii=False),
            model=self.executed_model,
            provider="opencode-go",
            degraded=self.degraded,
            fallback_trail=self.fallback_trail,
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
    assert result["requested_model"] == "deepseek-v4.1-flash"
    assert result["fallback_trail"] == []
    assert result["provider"] == "opencode-go"
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

def test_trace_never_declares_go_when_fallback_executed(context):
    """Si el adaptador cayó al fallback, la traza dice el modelo que ejecutó
    de verdad y la cadena de fallos: jamás se declara Go habiendo usado otro."""
    facts = _facts()
    provider = Provider(payload=_model_output(facts), executed_model="space-bunny-free",
                        fallback_trail=("opencode-go:deepseek-v4.1-flash:ProviderHTTPError",))
    result = _call(context, provider)
    assert result is not None
    assert result["model"] == "space-bunny-free"
    assert result["requested_model"] == "deepseek-v4.1-flash"
    assert result["fallback_trail"] == ["opencode-go:deepseek-v4.1-flash:ProviderHTTPError"]


def test_degraded_provider_response_is_rejected(context):
    facts = _facts()
    provider = Provider(payload=_model_output(facts), degraded=True)
    assert _call(context, provider) is None
    assert provider.calls == 2


def test_rejection_logs_exact_rule_executed_model_and_fallback_trail(context, caplog):
    import logging

    facts = _facts()
    bad = _model_output(facts)
    bad["secciones"][0]["parrafos"] = ["La empresa cotiza a 999.99 USD con un margen enorme para el escenario base registrado en esta tesis provisional."]
    provider = Provider(payload=bad, executed_model="deepseek-v4.1-flash", fallback_trail=("modelo-previo",))
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_deep_narrative"):
        assert _call(context, provider) is None
    rejection_logs = [r.getMessage() for r in caplog.records if "rechazada" in r.getMessage()]
    assert rejection_logs, "debe registrar el rechazo"
    for msg in rejection_logs:
        assert "cifra_no_anclada" in msg
        assert "deepseek-v4.1-flash" in msg
        assert "modelo-previo" in msg
        # Nunca contenido: ni prosa del modelo ni hechos del paquete.
        assert "999.99" not in msg
        assert "margen enorme" not in msg
        for fact in facts:
            assert fact["texto"][:40] not in msg


def test_retry_note_is_specific_to_the_rejected_rule(context):
    facts = _facts()
    bad = _model_output(facts)
    bad["secciones"][0]["parrafos"] = ["La empresa cotiza a 999.99 USD con un margen enorme para el escenario base registrado en esta tesis provisional."]
    provider = Provider(payload=bad)
    assert _call(context, provider) is None
    assert provider.calls == 2
    second_request = provider.requests[1]
    note = json.loads(second_request.messages[-1].content).get("nota", "")
    assert "rechazada" in note
    assert "redondeos" in note  # instruccion especifica de cifra_no_anclada
    # El reintento nunca relaja: sigue exigiendo hechos del paquete.
    assert "hechos del paquete" in note


def test_markup_emphasis_is_normalized_not_rejected(context):
    facts = _facts()
    marked = _model_output(facts)
    marked["secciones"][1]["parrafos"] = [
        "**Negrita** con el escenario base de 800.00 USD y el precio actual "
        "de 733.12 USD anclados al paquete de hechos de esta tesis provisional."
    ]
    marked["secciones"][2]["parrafos"] = [
        "## Fuentes\nEl escenario base de 800.00 USD sale del motor interno "
        "de valoracion registrado en la seccion 13 del memo de esta tesis."
    ]
    provider = Provider(payload=marked)
    result = _call(context, provider)
    assert result is not None
    published = json.dumps(result["sections"], ensure_ascii=False)
    assert "**" not in published and "##" not in published
    assert "Negrita" in published


def test_url_and_verdict_are_rejected_even_inside_markup(context, caplog):
    import logging

    facts = _facts()
    linked = _model_output(facts)
    linked["secciones"][2]["parrafos"] = [
        '<a href="https://evil.example.com">El escenario base</a> de 800.00 '
        "USD queda registrado en el memo de esta tesis provisional explicativa."
    ]
    provider = Provider(payload=linked)
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_deep_narrative"):
        assert _call(context, provider) is None
    msgs = [r.getMessage() for r in caplog.records if "rechazada" in r.getMessage()]
    assert any("url_detectada" in m for m in msgs)

    caplog.clear()
    verdict = _model_output(facts)
    verdict["secciones"][0]["parrafos"] = [
        "**Recomendamos comprar**: el escenario base de 800.00 USD supera al "
        "precio actual de 733.12 USD registrado en el modelo de valoracion."
    ]
    provider2 = Provider(payload=verdict)
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_deep_narrative"):
        assert _call(context, provider2) is None
    msgs = [r.getMessage() for r in caplog.records if "rechazada" in r.getMessage()]
    assert any("lenguaje_veredicto" in m for m in msgs)


def test_retry_note_for_url_failure_and_parse_failures(context):
    facts = _facts()
    linked = _model_output(facts)
    linked["secciones"][2]["parrafos"] = [
        "Segun https://evil.example.com el escenario base de 800.00 USD queda "
        "registrado en el memo de esta tesis provisional explicativa anclada."
    ]
    provider = Provider(payload=linked)
    assert _call(context, provider) is None
    note = json.loads(provider.requests[1].messages[-1].content).get("nota", "")
    assert "URL" in note

    class BadJson(Provider):
        async def complete(self, request):
            self.calls += 1
            self.requests.append(request)
            return SimpleNamespace(
                text="no-json", model="deepseek-v4.1-flash", provider="opencode-go",
                degraded=False, fallback_trail=(),
                usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
            )

    provider2 = BadJson(payload=None)
    assert _call(context, provider2) is None
    note2 = json.loads(provider2.requests[1].messages[-1].content).get("nota", "")
    assert "JSON valido" in note2


def test_validate_sections_reports_rule_codes():
    facts = _facts()
    ok = _model_output(facts)
    sections, reason = svc._validate_sections(ok, facts)
    assert sections is not None and reason is None

    short = _model_output(facts)
    short["secciones"][0]["parrafos"] = ["corto"]
    _, reason = svc._validate_sections(short, facts)
    assert reason == "parrafo_invalido"

    missing = _model_output(facts)
    missing["secciones"] = [s for s in missing["secciones"] if s["id"] != "fuentes_y_anclaje"]
    _, reason = svc._validate_sections(missing, facts)
    assert reason == "obligatorias_ausentes"

    bad_ids = _model_output(facts)
    bad_ids["secciones"][0]["fact_ids"] = ["f999"]
    _, reason = svc._validate_sections(bad_ids, facts)
    assert reason == "fact_ids_invalidos"


def test_fact_ids_have_no_digits_and_scale_past_26():
    facts = _facts()
    assert facts, "el pack debe tener hechos"
    for fact in facts:
        assert re.fullmatch(r"f[A-Z]+", fact["id"]), fact["id"]
    assert svc._fact_id(1) == "fA"
    assert svc._fact_id(26) == "fZ"
    assert svc._fact_id(27) == "fAA"


def test_model_never_sees_urls_but_citations_keep_real_locator(context):
    facts = _facts()
    assert any("example.org" in f["fuente"] for f in facts), "el pack de prueba debe tener una fuente con URL"
    provider = Provider(payload=_model_output(facts))
    result = _call(context, provider)
    assert result is not None
    # Lo que ve el modelo: sin URL ni host en el paquete visible.
    prompt_json = provider.requests[0].messages[-1].content
    assert "example.org" not in prompt_json
    assert "https://" not in prompt_json
    # Lo que publica el código: la cita conserva el localizador real.
    published = json.dumps(result["sections"], ensure_ascii=False)
    assert "example.org" in published


def test_model_writing_pack_domain_is_still_rejected(context, caplog):
    import logging

    facts = _facts()
    out = _model_output(facts)
    out["secciones"][2]["parrafos"] = [
        "El medio example.org publicó el titular citado y el escenario base "
        "de 800.00 USD queda anclado al motor interno de valoracion del memo."
    ]
    provider = Provider(payload=out)
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_deep_narrative"):
        assert _call(context, provider) is None
    msgs = [r.getMessage() for r in caplog.records if "rechazada" in r.getMessage()]
    assert any("url_detectada" in m for m in msgs)


def test_fact_id_digits_in_prose_are_rejected_as_unanchored(context, caplog):
    import logging

    facts = _facts()
    out = _model_output(facts)
    out["secciones"][0]["parrafos"] = [
        "Según el hecho 15 del paquete, Meta Platforms cotiza a 733.12 USD "
        "frente al escenario base de 800.00 USD registrado por el motor."
    ]
    provider = Provider(payload=out)
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_deep_narrative"):
        assert _call(context, provider) is None
    msgs = [r.getMessage() for r in caplog.records if "rechazada" in r.getMessage()]
    assert any("cifra_no_anclada" in m for m in msgs)


# --- Suministro de datos del paquete (fixtures offline con la forma real del
# --- objeto verificada 2026-10-26; valores sintéticos, nunca datos de tenant).

from decimal import Decimal

from app.models.entities import FinancialFact


def _ltm_full():
    return {
        "framework": {
            "key": "advertising_platform",
            "label": "Advertising / attention platform",
            "primary_question": "Can ad impressions compound advertising revenue?",
        },
        "missing_mandatory_drivers": [],
        "horizon_years": 5,
        "as_of_period": "2025-12-31:FY",
        "assumptions": {
            "revenue_growth": {"value": 0.12, "unit": "decimal", "source_type": "financial_facts",
                               "basis": "annual revenue CAGR across available history",
                               "source_fact_ids": [101, 102], "confidence": 0.9},
            "fcf_margin": {"value": 0.25, "unit": "decimal", "source_type": "financial_facts",
                           "basis": "median of latest annual FCF margins",
                           "source_fact_ids": [103], "confidence": 0.9},
            "wacc": {"value": 0.10, "unit": "decimal", "source_type": "calculated_metric",
                     "basis": "WACC_STANDARD_V1", "source_fact_ids": [104],
                     "source_urls": ["https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=META"]},
            "terminal_growth": {"value": 0.03, "unit": "decimal", "source_type": "model_policy",
                                "basis": "terminal growth policy", "source_fact_ids": []},
        },
        "driver_model": [
            {"key": "daily_active_people", "status": "sourced", "value": 2.1e9, "unit": "people",
             "period": "2025-12", "source_fact_ids": [777]},
            {"key": "ad_impressions", "status": "missing", "value": None, "unit": "unknown",
             "period": "unknown", "source_fact_ids": []},
        ],
    }


def _ff(metric, value, unit, period, source_id=None):
    return FinancialFact(metric=metric, value=Decimal(str(value)), unit=unit,
                         period=period, source_type="sec_companyfacts", source_id=source_id)


def test_pack_includes_fundamentals_with_period_unit_and_source():
    facts = svc.fact_pack(
        _company(), _valuation(), _long_term_model(), None, [], None, None,
        financial_facts=[
            _ff("revenue", 100000000000, "USD", "2025-12-31:FY"),
            _ff("fcf_margin", "0.25", "decimal", "2025-12-31:FY"),
        ],
    )
    textos = [f["texto"] for f in facts]
    assert any("periodos distintos NO son comparables" in t for t in textos)
    assert any("Ingresos de META: 100 mil M USD (periodo 2025-12-31:FY; fuente sec_companyfacts)" in t for t in textos)
    assert any("Margen de FCF de META: 25,0 % (periodo 2025-12-31:FY" in t for t in textos)
    # Cada cifra nueva queda anclada por construcción: el validador las admite.
    allowed = svc._allowed_numbers(facts)
    assert "100" in allowed and "25" in allowed


def test_dcf_assumptions_are_labeled_model_assumptions_not_data():
    facts = svc.fact_pack(_company(), _valuation(), _ltm_full(), None, [])
    sup = next(f["texto"] for f in facts if f["texto"].startswith("Supuestos del motor"))
    assert "supuestos del modelo, no datos realizados ni fuentes externas" in sup
    assert "12,0 % anual" in sup and "25,0 %" in sup and "10,0 %" in sup and "3,0 %" in sup
    assert "horizonte de proyección de 5 años" in sup and "datos de corte 2025-12-31:FY" in sup


def test_assumption_source_urls_stay_in_locator_never_visible(context):
    # El paquete interno de la llamada usa el objeto completo: la URL de un
    # supuesto va al localizador (cita del código), nunca al prompt visible.
    facts = svc.fact_pack(_company(), _valuation(), _ltm_full(),
                          "La publicidad sigue monetizando.", NEWS)
    url_fact = next(f for f in facts if "sec.gov" in f["fuente"])
    assert "no implica verificación de su contenido" in url_fact["texto"]
    payload = _model_output(facts)
    payload["secciones"][2]["fact_ids"].append(url_fact["id"])
    provider = Provider(payload=payload)
    db, _ = context
    result = svc.maybe_deep_narrative(
        db, _company(), _valuation(), _ltm_full(),
        "La publicidad sigue monetizando.", NEWS, provider=provider)
    assert result is not None
    prompt_json = provider.requests[0].messages[-1].content
    assert "sec.gov" not in prompt_json
    # La cita insertada por el código conserva la URL real del supuesto.
    published = json.dumps(result["sections"], ensure_ascii=False)
    assert "sec.gov" in published


def test_sourced_driver_uses_resolved_real_url_locator():
    facts = svc.fact_pack(
        _company(), _valuation(), _ltm_full(), None, [], None, None,
        fact_locators={777: "https://www.sec.gov/Archives/edgar/data/1326801/x/meta-20261231.htm"},
    )
    driver_fact = next(f for f in facts if "personas activas al día" in f["texto"])
    assert "2,1 mil M" in driver_fact["texto"] and "periodo 2025-12" in driver_fact["texto"]
    assert driver_fact["fuente"] == "https://www.sec.gov/Archives/edgar/data/1326801/x/meta-20261231.htm"
    # El driver sin dato NO genera hecho: el hueco honesto se mantiene.
    assert not any("impresiones publicitarias:" in f["texto"] for f in facts)


def test_reverse_dcf_solved_value_is_model_output():
    valuation = _valuation()
    valuation["reverse_dcf"] = {"required_revenue_growth": 0.1, "market_price": 640.0,
                                 "solved_value_per_share": 640.0, "out_of_bounds": False, "status": "ok"}
    facts = svc.fact_pack(_company(), valuation, _long_term_model(), None, [])
    assert any("el DCF inverso resuelve un valor de 640.00 USD" in f["texto"] for f in facts)


def test_no_supply_facts_when_objects_absent_and_gaps_stay_honest():
    ltm = _long_term_model()
    ltm["missing_mandatory_drivers"] = ["daily_active_people"]
    facts = svc.fact_pack(_company(), _valuation(), ltm, None, [], None, None)
    textos = [f["texto"] for f in facts]
    assert not any(t.startswith("Supuestos del motor") for t in textos)
    assert not any("periodos distintos NO son comparables" in t for t in textos)
    assert not any("Driver del marco con dato" in t for t in textos)
    assert any("Drivers obligatorios del marco sin dato: daily_active_people" in t for t in textos)


def test_visible_fuente_label_avoids_false_verification_claim():
    label = svc._visible_fuente("https://www.sec.gov/Archives/x.htm")
    assert "verificada" not in label
    assert "registrada" in label and "no veracidad" in label


def test_wacc_formula_without_technical_class_tokens():
    # Forma real observada 2026-10-26: la base del WACC trae la fórmula Y
    # clases técnicas («CalculatedMetric #66426:», «; definition=...»).
    # La explicación ancha explicita la fórmula, nunca las clases.
    ltm = _ltm_full()
    ltm["assumptions"]["wacc"] = {
        "value": 0.0995, "unit": "decimal", "source_type": "calculated_metric",
        "basis": ("CalculatedMetric #66426: equity_weight * (risk_free_rate + "
                  "beta * equity_risk_premium) + debt_weight * cost_of_debt * "
                  "(1 - tax_rate); definition=WACC_STANDARD_V1"),
        "source_fact_ids": [1], "confidence": 0.7,
    }
    facts = svc.fact_pack(_company(), _valuation(), ltm, None, [])
    sup = next(f["texto"] for f in facts if f["texto"].startswith("Supuestos del motor"))
    assert "equity_weight * (risk_free_rate + beta * equity_risk_premium)" in sup
    assert "CalculatedMetric" not in sup and "WACC_STANDARD_V1" not in sup


def test_model_policy_assumption_marked_without_external_basis():
    # terminal_growth existe como parámetro (0,03) pero es política del
    # modelo: «sin base documentada externa», distinto de «no existe».
    facts = svc.fact_pack(_company(), _valuation(), _ltm_full(), None, [])
    sup = next(f["texto"] for f in facts if f["texto"].startswith("Supuestos del motor"))
    assert "crecimiento terminal del 3,0 %" in sup
    assert "sin base documentada externa" in sup


def test_assumption_fcf_margin_not_equated_with_reported_period_margin():
    facts = svc.fact_pack(
        _company(), _valuation(), _ltm_full(), None, [], None, None,
        financial_facts=[_ff("fcf_margin", "0.23", "decimal", "2025-12-31:FY")],
    )
    sup = next(f["texto"] for f in facts if f["texto"].startswith("Supuestos del motor"))
    assert "no son la misma cifra" in sup
    rep = next(f["texto"] for f in facts if "Margen de FCF de META" in f["texto"])
    assert "23,0 %" in rep and "2025-12-31:FY" in rep
