"""Capa 2 de la tesis: narrativa por seleccion de plantillas, correcta por construccion."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services import thesis_narrative_llm as narrative


def _company() -> Company:
    return Company(
        ticker="META", name="Meta Platforms", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Internet", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )


HYPOTHESIS = "hipotesis determinista"
NEWS = [
    {"source_headline": "Meta presenta Muse, su nuevo modelo", "title": "resumen interno",
     "source": "TechCrunch", "date": "2026-09-25T10:00:00", "date_source": "source"},
]
VALUATION = {
    "status": "ok", "current_price": 336.56, "base_value": 106.85,
    "margin_of_safety": -0.68, "missing_inputs": [],
    "reverse_dcf": {"required_revenue_growth": 0.35},
}
FRAGMENTS = narrative._fragment_templates(_company(), VALUATION, NEWS)


class _FakeUsage:
    input_tokens = 100
    output_tokens = 40
    total_tokens = 140


class _FakeResponse:
    model = "test-model"
    usage = _FakeUsage()

    def __init__(self, text: str):
        self.text = text


class _FakeProvider:
    name = "fake"

    def __init__(self, fragment_ids=None, raw_text: str | None = None, raises: bool = False):
        self._ids = fragment_ids
        self._raw = raw_text
        self._raises = raises
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self._raises:
            raise RuntimeError("provider down")
        if self._raw is not None:
            return _FakeResponse(self._raw)
        return _FakeResponse(json.dumps({"fragment_ids": self._ids}))


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _spy_budget(monkeypatch):
    calls = []

    class _SpyBudget:
        def can_spend(self, db, amount):
            return True

        def record(self, db, model, workflow, cost, tokens, *, commit=True):
            calls.append({"workflow": workflow, "commit": commit})

        @staticmethod
        def estimate_cost_eur(model, input_tokens, output_tokens):
            return 0.01

    monkeypatch.setattr(narrative, "BudgetController", _SpyBudget)
    return calls


def test_templates_are_correct_by_construction():
    # MoS = base/price - 1: se nombra explicitamente, sin distancia
    # precio/base (que usaria el denominador equivocado: 215%, no 68%).
    assert FRAGMENTS["valoracion_posicion"] == (
        "Meta Platforms cotiza a 336.56 USD frente a un escenario base de "
        "106.85 USD (margen de seguridad del -68%)."
    )
    assert FRAGMENTS["expectativas_mercado"] == (
        "Con los supuestos de este DCF inverso, el precio actual exigiría "
        "un crecimiento de ingresos del 35.0% anual."
    )
    assert FRAGMENTS["titular_0"] == (
        'TechCrunch publico el 2026-09-25 "Meta presenta Muse, su nuevo modelo". Fuente: URL no disponible.'
    )
    assert "caveat_titulares" in FRAGMENTS
    assert "caveat_parcial" not in FRAGMENTS
    assert "caveat_insufficient" not in FRAGMENTS


def test_flag_off_returns_baseline(db, monkeypatch):
    monkeypatch.delenv("THESIS_NARRATIVE_LLM_ENABLED", raising=False)
    provider = _FakeProvider(list(FRAGMENTS))
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base", provider=provider)
    assert result == "base"
    assert provider.calls == 0


def test_provider_disabled_returns_baseline(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=SimpleNamespace(name="disabled"))
    assert result == "base"


def test_valid_selection_composes_narrative(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    order = ["valoracion_posicion", "expectativas_mercado", "titular_0", "caveat_titulares"]
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(order))
    assert result == " ".join(FRAGMENTS[fid] for fid in order)
    assert result.startswith("Meta Platforms cotiza a 336.56 USD")


def test_selection_with_unknown_id_falls_back(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(["valoracion_posicion", "inventado"]))
    assert result == "base"


def test_selection_with_duplicates_falls_back(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(["valoracion_posicion", "valoracion_posicion"]))
    assert result == "base"


def test_titular_without_caveat_falls_back(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(["valoracion_posicion", "titular_0"]))
    assert result == "base"


def test_caveat_without_titular_falls_back(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(["valoracion_posicion", "caveat_titulares"]))
    assert result == "base"


def test_partial_requires_caveat_fragment(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    valuation = dict(VALUATION, status="partial", missing_inputs=["beta"])
    frags = narrative._fragment_templates(_company(), valuation, NEWS)
    assert "caveat_parcial" in frags
    assert "sección 13" in frags["caveat_parcial"]
    assert "valoración es parcial" in frags["caveat_parcial"]
    # Sin el fragmento obligatorio de parcialidad: capa 1.
    result = narrative.maybe_narrative(
        db, _company(), valuation, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(["valoracion_posicion"]))
    assert result == "base"
    order = ["valoracion_posicion", "caveat_parcial", "titular_0", "caveat_titulares"]
    result = narrative.maybe_narrative(
        db, _company(), valuation, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(order))
    assert "parcial-indicativa" in result
    assert "beta" in result


def test_insufficient_data_only_offers_caveat(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    valuation = {"status": "insufficient_data", "missing_inputs": ["revenue"],
                 "current_price": None, "base_value": None, "margin_of_safety": None}
    frags = narrative._fragment_templates(_company(), valuation, [])
    assert list(frags) == ["caveat_insufficient"]
    assert "revenue" in frags["caveat_insufficient"]
    result = narrative.maybe_narrative(
        db, _company(), valuation, HYPOTHESIS, [], "base",
        provider=_FakeProvider(["caveat_insufficient"]))
    assert result == frags["caveat_insufficient"]
    # El modelo no puede "olvidar" la salvedad: sin ella no hay seleccion valida.
    result = narrative.maybe_narrative(
        db, _company(), valuation, HYPOTHESIS, [], "base",
        provider=_FakeProvider([]))
    assert result == "base"


def test_provider_error_falls_back(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(raises=True))
    assert result == "base"


def test_invalid_json_falls_back(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(raw_text="no es json"))
    assert result == "base"


def test_budget_recorded_even_when_selection_discarded(db, monkeypatch):
    # La llamada consumio tokens: se cobra con commit=False aunque la
    # seleccion se descarte; aceptar/rechazar solo decide que se persiste.
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    calls = _spy_budget(monkeypatch)
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(["inventado"]))
    assert result == "base"
    assert calls == [{"workflow": "thesis_narrative", "commit": False}]


def test_valuation_core_is_mandatory(db, monkeypatch):
    # Sin el nucleo de valoracion (precio/base/MoS), la seleccion no puede
    # sustituir el executive_summary: noticias o expectativas no bastan.
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    for ids in (["titular_0", "caveat_titulares"], ["expectativas_mercado"]):
        result = narrative.maybe_narrative(
            db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
            provider=_FakeProvider(ids))
        assert result == "base"


def test_caveat_titulares_must_come_after_headlines(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
        provider=_FakeProvider(
            ["valoracion_posicion", "caveat_titulares", "titular_0"]))
    assert result == "base"


def test_no_valuation_core_returns_baseline_without_llm_call(db, monkeypatch):
    # status ok con current_price=None (posible en valuation_service): solo
    # existiria expectativas_mercado, que afirmaria "El mercado descuenta..."
    # sin mercado. Capa 1 intacta y ni siquiera se llama al proveedor.
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    valuation = {"status": "ok", "current_price": None, "base_value": None,
                 "margin_of_safety": None, "missing_inputs": [],
                 "reverse_dcf": {"required_revenue_growth": 0.35}}
    provider = _FakeProvider(["expectativas_mercado"])
    result = narrative.maybe_narrative(
        db, _company(), valuation, HYPOTHESIS, NEWS, "base", provider=provider)
    assert result == "base"
    assert provider.calls == 0


def test_non_string_ids_fall_back_without_exception(db, monkeypatch):
    # JSON valido con ids no-string: nunca TypeError, siempre capa 1.
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    for raw in (
        json.dumps({"fragment_ids": [{"id": "valoracion_posicion"}]}),
        json.dumps({"fragment_ids": [["valoracion_posicion"]]}),
        json.dumps({"fragment_ids": [None]}),
    ):
        result = narrative.maybe_narrative(
            db, _company(), VALUATION, HYPOTHESIS, NEWS, "base",
            provider=_FakeProvider(raw_text=raw))
        assert result == "base"


def test_provider_factory_error_falls_back(db, monkeypatch):
    # Con el flag ON, una config de proveedor incompatible no puede romper
    # la generacion: create_llm_provider lanza y se devuelve la capa 1.
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")

    def _boom():
        raise ValueError("llm_provider invalido")

    monkeypatch.setattr(narrative, "create_llm_provider", _boom)
    result = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base")
    assert result == "base"


# ---------------------------------------------------------------------------
# Analisis narrativo por secciones
# ---------------------------------------------------------------------------


class _FakeSectionsProvider:
    name = "fake"

    def __init__(self, section_ids=None, raw_text: str | None = None):
        self._ids = section_ids
        self._raw = raw_text
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self._raw is not None:
            return _FakeResponse(self._raw)
        return _FakeResponse(json.dumps({"section_ids": self._ids}))


NEWS_WITH_GAPS = [
    *NEWS,
    {"source_headline": "Meta retrasa su capex de IA", "title": "resumen interno",
     "source": "Reuters", "date": "2026-09-27T09:00:00",
     "date_source": "ingested_at_fallback", "requires_update": True},
]
VALUATION_PARTIAL = {
    "status": "partial", "current_price": 336.56, "base_value": 106.85,
    "margin_of_safety": -0.68, "missing_inputs": ["ebitda"],
    "reverse_dcf": {"required_revenue_growth": 0.35},
}


def _sections(valuation=VALUATION, news=NEWS):
    return narrative._section_templates(_company(), valuation, HYPOTHESIS, list(news))


def test_section_templates_titles_and_slots():
    sections = _sections(VALUATION_PARTIAL, NEWS_WITH_GAPS)
    assert set(sections) == {
        "lo_que_sabemos", "hipotesis", "lo_que_cambio", "lo_que_descuenta",
        "no_sabemos",
    }
    assert sections["lo_que_sabemos"]["titulo"] == "Lo que sabemos"
    assert sections["lo_que_cambio"]["titulo"] == "Lo que cambió"
    assert sections["lo_que_descuenta"]["titulo"] == "Lo que exige el precio actual"
    assert sections["no_sabemos"]["titulo"] == "Lo que aún no sabemos"
    # Los parrafos salen de los mismos slots verificados de la capa resumen.
    assert sections["lo_que_sabemos"]["parrafos"][0] == FRAGMENTS["valoracion_posicion"]
    # La hipotesis (interpretacion) no convive con los hechos: seccion propia.
    assert all("Hipótesis" not in p for p in sections["lo_que_sabemos"]["parrafos"])
    assert sections["hipotesis"]["parrafos"] == [HYPOTHESIS]
    # El caveat de titulares cierra siempre la seccion de noticias.
    assert sections["lo_que_cambio"]["parrafos"][-1] == FRAGMENTS["caveat_titulares"]
    # Hechos vs interpretacion con el numero como slot.
    assert any(
        "margen de seguridad del -68% (escenario base/precio - 1" in p
        and "equivale al 32% del precio actual" in p
        for p in sections["lo_que_descuenta"]["parrafos"]
    )


def test_unknown_section_questions_are_ticker_specific():
    sections = _sections(VALUATION_PARTIAL, NEWS_WITH_GAPS)
    preguntas = sections["no_sabemos"]["parrafos"]
    assert any("ebitda" in p and "META" in p for p in preguntas)
    assert any("parcial-indicativa" in p and "META" in p for p in preguntas)
    assert any("fecha registrada es la de ingesta" in p for p in preguntas)
    assert any("pendiente de actualización" in p for p in preguntas)
    # Sin huecos reales no hay seccion de preguntas (nunca genericas).
    sections_full = _sections(VALUATION, NEWS)
    assert "no_sabemos" not in sections_full


def test_section_selection_fail_closed():
    sections = _sections(VALUATION_PARTIAL, NEWS_WITH_GAPS)
    # Id desconocido, duplicados, no-lista.
    assert narrative._validated_section_selection(["lo_que_sabemos", "x"], sections) is None
    assert narrative._validated_section_selection(
        ["lo_que_sabemos", "lo_que_sabemos"], sections) is None
    assert narrative._validated_section_selection("lo_que_sabemos", sections) is None
    assert narrative._validated_section_selection([], sections) is None
    # Obligatorias: hechos y preguntas no se pueden omitir.
    assert narrative._validated_section_selection(["lo_que_cambio"], sections) is None
    assert narrative._validated_section_selection(["lo_que_sabemos"], sections) is None
    # Orden: los hechos abren, las preguntas cierran.
    assert narrative._validated_section_selection(
        ["no_sabemos", "lo_que_sabemos"], sections) is None
    assert narrative._validated_section_selection(
        ["lo_que_sabemos", "no_sabemos", "lo_que_cambio"], sections) is None


def test_section_selection_appends_fixed_disclaimer():
    sections = _sections(VALUATION_PARTIAL, NEWS_WITH_GAPS)
    result = narrative._validated_section_selection(
        ["lo_que_sabemos", "lo_que_cambio", "lo_que_descuenta", "no_sabemos"],
        sections,
    )
    assert result is not None
    assert result[-1]["titulo"] == "Salvedad"
    assert "no es recomendación de inversión" in result[-1]["parrafos"][0]
    assert result[0]["titulo"] == "Lo que sabemos"
    assert result[-2]["titulo"] == "Lo que aún no sabemos"


def test_sections_flag_off_returns_none(db, monkeypatch):
    monkeypatch.delenv("THESIS_NARRATIVE_LLM_ENABLED", raising=False)
    provider = _FakeSectionsProvider(["lo_que_sabemos"])
    result = narrative.maybe_narrative_sections(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, provider=provider)
    assert result is None
    assert provider.calls == 0


def test_sections_valid_selection(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    _spy_budget(monkeypatch)
    sections = _sections()
    provider = _FakeSectionsProvider(list(sections))
    result = narrative.maybe_narrative_sections(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, provider=provider)
    assert result is not None
    assert provider.calls == 1
    assert result[-1]["titulo"] == "Salvedad"


def test_sections_invalid_selection_returns_none(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    _spy_budget(monkeypatch)
    provider = _FakeSectionsProvider(["inventada"])
    result = narrative.maybe_narrative_sections(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, provider=provider)
    assert result is None
    # JSON roto del proveedor: mismo fail-closed.
    provider = _FakeSectionsProvider(raw_text="no json")
    assert narrative.maybe_narrative_sections(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, provider=provider) is None


def test_sections_without_facts_core_return_none(db, monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    _spy_budget(monkeypatch)
    valuation = {"status": "ok"}  # sin precio/base: sin "lo_que_sabemos"
    provider = _FakeSectionsProvider(["lo_que_cambio"])
    result = narrative.maybe_narrative_sections(
        db, _company(), valuation, HYPOTHESIS, NEWS, provider=provider)
    assert result is None
    assert provider.calls == 0


def test_shared_budget_cap_within_one_generate(db, monkeypatch):
    """Las dos capas LLM de un mismo generate comparten el cap diario.

    Con SessionLocal(autoflush=False), registrar el consumo de la primera
    capa con commit=False no bastaba: el SUM de can_spend de la segunda no
    veia la fila pendiente. El flush explicito tras registrar cierra el
    bypass; este test falla si se quita.
    """
    from types import SimpleNamespace as NS

    from app.services.budget import BudgetController

    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    controller = BudgetController()
    controller.settings = NS(llm_daily_cap_eur=0.05, llm_monthly_cap_eur=1000.0)
    controller.estimate_cost_eur = lambda *args: 0.04
    monkeypatch.setattr(narrative, "BudgetController", lambda: controller)

    # Primera capa (resumen): 0 + 0.02 estimado <= 0.05 -> gasta 0.04 real.
    provider1 = _FakeProvider(list(FRAGMENTS))
    summary = narrative.maybe_narrative(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, "base", provider=provider1)
    assert summary != "base"
    assert provider1.calls == 1

    # Segunda capa (secciones): 0.04 registrado + 0.02 estimado > 0.05 -> NO
    # puede gastar: fail-closed sin llamar al proveedor.
    provider2 = _FakeSectionsProvider(list(_sections()))
    result = narrative.maybe_narrative_sections(
        db, _company(), VALUATION, HYPOTHESIS, NEWS, provider=provider2)
    assert result is None
    assert provider2.calls == 0


def test_negative_base_fragment_has_no_margin_percentage():
    valuation = {**VALUATION, "current_price": 58.45, "base_value": -84.7, "margin_of_safety": -2.49}
    fragments = narrative._fragment_templates(_company(), valuation, NEWS)
    text = fragments["valoracion_posicion"]
    assert "-249%" not in text
    assert "no es interpretable" in text
    assert "-84.70" in text


def test_position_fragment_names_expected_value_when_margin_comes_from_it():
    valuation = {
        **VALUATION,
        "current_price": 529.05,
        "base_value": 309.10,
        "expected_value": 365.0,
        "margin_of_safety": 365.0 / 529.05 - 1,
    }
    fragments = narrative._fragment_templates(_company(), valuation, NEWS)
    assert "valor esperado de 365.00" in fragments["valoracion_posicion"]
    assert "margen de seguridad del -31%" in fragments["valoracion_posicion"]
    assert "escenario base" not in fragments["valoracion_posicion"]
