"""KO 2026-11-17: el chat citaba la valoración archivada de un borrador no publicable.

El fallback determinista usaba el resumen de la tesis v1 borrador (valor
esperado, margen de seguridad, DCF inverso) aunque la pestaña Tesis lo oculta.
Además /api/chat devolvía 200 sin dejar el motivo del fallback en la telemetría.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.chat_service import _answer_lead
from app.services.chat_telemetry import fallback_error

_LINE = "La tesis guardada de KO es la v1 (estado borrador)."


def _lead(status: str, summary: str) -> str | None:
    thesis = SimpleNamespace(status=status, executive_summary=summary, version=1, valuation_risk_score=0)
    return _answer_lead(
        "¿qué dice la tesis de KO?",
        company=SimpleNamespace(ticker="KO"), facts=[], thesis=thesis, thesis_line=_LINE,
        news=[], claims=[], contradiction_claims=[], price_line=None, focus_metrics=set(),
    )


@pytest.mark.parametrize(
    "summary",
    [
        "Valor esperado de 11,81 $ frente a un precio supuesto de 60 $.",
        "El margen de seguridad es negativo según el modelo.",
        "El reverse DCF exige un crecimiento del 37,3 % anual.",
        "WACC del 8 % y valoración indicativa baja.",
        "Crecimiento del 12 % anual sostenido durante diez años.",
    ],
)
def test_borrador_con_cifras_de_valoracion_no_cita_el_resumen(summary):
    lead = _lead("draft", summary)

    assert lead is not None and lead.startswith(_LINE)
    assert "No cito su resumen" in lead and "Resumen:" not in lead
    for figure in ("11,81", "37,3", "60 $", "WACC", "reverse", "12 %"):
        assert figure not in lead


def test_borrador_sin_cifras_de_valoracion_conserva_el_resumen():
    lead = _lead("draft", "Coca-Cola vende bebidas en más de 200 países con una marca muy fuerte.")

    assert "Resumen: Coca-Cola vende bebidas" in lead
    assert "No cito su resumen" not in lead


def test_tesis_publicada_conserva_su_resumen_con_cifras():
    lead = _lead("published", "Valor esperado de 70 $ con margen de seguridad del 15 %.")

    assert "Resumen: Valor esperado de 70 $" in lead
    assert "No cito su resumen" not in lead


def test_fallback_error_sin_fallback_es_none():
    assert fallback_error(SimpleNamespace(llm_trace={"path": "chat_synthesis", "fallback": False})) is None
    assert fallback_error(SimpleNamespace(llm_trace=None)) is None
    assert fallback_error(SimpleNamespace()) is None


def test_fallback_error_recoge_motivo_y_detalle():
    trace = {"fallback": True, "fallback_reason": "ReadTimeout", "fallback_detail": "read_timeout 18220 ms"}

    assert fallback_error(SimpleNamespace(llm_trace=trace)) == "fallback: ReadTimeout | read_timeout 18220 ms"


def test_fallback_error_sin_motivo_dice_solo_fallback():
    assert fallback_error(SimpleNamespace(llm_trace={"fallback": True})) == "fallback"


def test_fallback_error_se_acota_a_500_caracteres():
    trace = {"fallback": True, "fallback_detail": "x" * 2000}

    assert len(fallback_error(SimpleNamespace(llm_trace=trace))) == 500


@pytest.mark.parametrize(
    "trace,expected",
    [
        ({"fallback": True, "fallback_reason": "ReadTimeout"}, "fallback: ReadTimeout"),
        ({"path": "chat_synthesis", "provider": "p", "model": "m", "fallback": False}, None),
    ],
)
def test_ruta_chat_pasa_el_motivo_del_fallback_a_la_telemetria(monkeypatch, trace, expected):
    from app.api.routes import chat as route
    from app.schemas import ChatRequest, ChatResponse

    class DB:
        info = {"tenant_id": 5}

        def get_bind(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Service:
        def __init__(self, provider=None):
            self.provider = provider

        async def answer(self, *args, **kwargs):
            return ChatResponse(answer="ok", sources=[], model="deterministic", confidence=0, llm_trace=trace)

    recorded = []
    monkeypatch.setattr(route, "SessionLocal", lambda **kw: DB())
    monkeypatch.setattr(route, "ChatService", Service)
    monkeypatch.setattr(route, "record_chat_event", lambda **kw: recorded.append(kw))

    asyncio.run(route.chat(ChatRequest(question="hola"), DB()))

    assert len(recorded) == 1
    assert recorded[0]["error"] == expected
