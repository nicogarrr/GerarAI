"""Cuerpo vacio del proveedor (HY4 `returned an empty assistant message`).

Medido en prod 2026-11-17 (c31b): una pregunta conceptual acabo en N/D
«el proveedor no responde» tras una sola llamada de 5 s con cuerpo vacio.
Chat interactivo: UN reintento acotado, mismo proveedor, 0 EUR. Sin la bandera
(extraccion, expertos) no se repite nada.
"""

import asyncio

import pytest

from app.llm import LLMRequest, Message
from app.llm.errors import ProviderEmptyResponseError, ProviderResponseError
from app.services import llm_output_guard as guard
from app.services.chat_synthesis_service import _MODEL_DOWN_MOTIVES, _model_down_kind


class _Resp:
    text = "Hola, el flujo de caja libre es el efectivo que queda tras invertir."


class _Bad:
    text = "El flujo de caja libre es 这是一个测试 y queda tras invertir."


class _Provider:
    name = "hy4-go-zero"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _request():
    return LLMRequest(messages=[Message("user", "hola")], task="chat")


def _run(provider, **kwargs):
    return asyncio.run(guard.complete_guarded(provider, _request(), source="t_empty", **kwargs))


@pytest.fixture(autouse=True)
def _plenty_of_time(monkeypatch):
    monkeypatch.setattr("app.llm.interactive_deadline.remaining_seconds", lambda default=None: 20.0)


def test_vacio_se_reintenta_una_vez_con_la_bandera():
    provider = _Provider([ProviderEmptyResponseError("hy4 empty"), _Resp()])
    out = _run(provider, retry_empty_once=True)
    assert provider.calls == 2
    assert out.response.text.startswith("Hola")


def test_sin_bandera_no_se_repite():
    provider = _Provider([ProviderEmptyResponseError("hy4 empty"), _Resp()])
    with pytest.raises(ProviderEmptyResponseError):
        _run(provider)
    assert provider.calls == 1


def test_dos_vacios_propagan_el_error_sin_tercera_llamada():
    provider = _Provider([ProviderEmptyResponseError("a"), ProviderEmptyResponseError("b"), _Resp()])
    with pytest.raises(ProviderEmptyResponseError):
        _run(provider, retry_empty_once=True)
    assert provider.calls == 2


def test_otros_errores_del_proveedor_no_se_reintentan():
    provider = _Provider([ProviderResponseError("no assistant message"), _Resp()])
    with pytest.raises(ProviderResponseError):
        _run(provider, retry_empty_once=True)
    assert provider.calls == 1


def test_poco_plazo_restante_no_reintenta(monkeypatch):
    monkeypatch.setattr("app.llm.interactive_deadline.remaining_seconds", lambda default=None: 2.0)
    provider = _Provider([ProviderEmptyResponseError("a"), _Resp()])
    with pytest.raises(ProviderEmptyResponseError):
        _run(provider, retry_empty_once=True)
    assert provider.calls == 1


def test_before_retry_puede_cancelar_por_presupuesto():
    class _Budget(Exception):
        pass

    def _no_budget():
        raise _Budget()

    provider = _Provider([ProviderEmptyResponseError("a"), _Resp()])
    with pytest.raises(_Budget):
        _run(provider, retry_empty_once=True, before_retry=_no_budget)
    assert provider.calls == 1


def test_motivo_del_fallo_vacio_se_dice_claro():
    kind = _model_down_kind(ProviderEmptyResponseError("hy4 empty"), "provider_or_guard_failure")
    assert kind == "empty"
    es, en = _MODEL_DOWN_MOTIVES[kind]
    assert "vacía" in es and "empty" in en
    # un ProviderResponseError generico NO se etiqueta como vacio
    assert _model_down_kind(ProviderResponseError("x"), "provider_or_guard_failure") != "empty"


def _count_before_retry():
    seen = []
    return seen, lambda: seen.append(1)


def test_vacio_y_luego_valida_cuenta_las_dos_llamadas():
    provider = _Provider([ProviderEmptyResponseError("hy4 empty"), _Resp()])
    out = _run(provider, retry_empty_once=True)
    assert (out.calls, out.retried, out.discarded) == (2, True, [])
    assert out.calls == provider.calls


def test_sin_reintento_cuenta_una_llamada():
    provider = _Provider([_Resp()])
    out = _run(provider, retry_empty_once=True)
    assert (out.calls, out.retried) == (1, False)
    assert provider.calls == 1


def test_rechazada_por_guard_y_luego_valida_cuenta_dos():
    provider = _Provider([_Bad(), _Resp()])
    out = _run(provider)
    assert (out.calls, out.retried, len(out.discarded)) == (2, True, 1)
    assert out.calls == provider.calls


def test_vacio_y_luego_rechazada_no_hace_tercera_llamada():
    provider = _Provider([ProviderEmptyResponseError("hy4 empty"), _Bad(), _Resp()])
    seen, before = _count_before_retry()
    with pytest.raises(guard.LLMOutputRejected) as info:
        _run(provider, retry_empty_once=True, before_retry=before)
    assert provider.calls == 2
    assert info.value.calls == 2
    assert len(info.value.discarded) == 1 and isinstance(info.value.discarded[0], _Bad)
    assert len(seen) == 1  # solo el reintento por vacio pasa por before_retry


def test_rechazada_dos_veces_sin_vacio_sigue_igual():
    provider = _Provider([_Bad(), _Bad(), _Resp()])
    with pytest.raises(guard.LLMOutputRejected) as info:
        _run(provider)
    assert provider.calls == 2 and info.value.calls == 2
    assert len(info.value.discarded) == 2
