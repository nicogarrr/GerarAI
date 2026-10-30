"""Una respuesta RECHAZADA por el llamador no se queda en la cache.

En main la cache guardaba cualquier respuesta con finish_reason limpio. Si el
guard de salida (CJK, tokens corruptos) o el parseo JSON la rechazaban, la
entrada seguia viva 15 min: la siguiente peticion identica recibia la misma
salida mala desde cache (sin llegar al proveedor) y el reintento tambien
quedaba cacheado, asi que la funcion degradaba durante todo el TTL.
"""

import pytest

from app.llm import StructuredOutputError
from app.llm.response_cache import tenant_cache_scope
from app.services.llm_output_guard import LLMOutputRejected, complete_guarded
from tests.test_response_cache import _ok_body, _provider, _request, _Transport, run


def test_guard_rejected_output_is_evicted_and_next_call_reaches_provider():
    provider, stub, redis = _provider(transport=_Transport(_ok_body("这是一个中文回答，不是西班牙语。" * 3)))
    with tenant_cache_scope(7):
        for _ in range(2):
            with pytest.raises(LLMOutputRejected):
                run(complete_guarded(provider, _request(), source="test"))
    assert stub.calls == 4
    assert not redis.values


def test_unparseable_json_is_evicted():
    provider, stub, redis = _provider(transport=_Transport(_ok_body("lo siento, no tengo datos")))
    with tenant_cache_scope(7):
        for _ in range(2):
            with pytest.raises(StructuredOutputError):
                run(provider.generate_json(_request()))
    assert stub.calls == 2
    assert not redis.values


def test_accepted_output_is_still_served_from_cache():
    provider, stub, _ = _provider(transport=_Transport(_ok_body("Respuesta correcta en español.")))
    with tenant_cache_scope(7):
        first = run(complete_guarded(provider, _request(), source="test"))
        second = run(complete_guarded(provider, _request(), source="test"))
    assert stub.calls == 1
    assert second.response.from_cache and second.response.text == first.response.text
