"""Bordes defensivos de los workers: presupuesto de reintentos y middleware LLM.

Cubre las ramas de degradacion que los tests de comportamiento no ejercitan:
sondas best-effort que fallan (sin mensaje, opciones corruptas, actor
desconocido) deben devolver "sin presupuesto" / "sin tenant" en vez de romper
el worker, y el cleanup del middleware debe funcionar aunque el mensaje no
acepte opciones nuevas o llegue por skip.
"""

from __future__ import annotations

from types import SimpleNamespace

import dramatiq

from app.workers import rate_limit_retry
from app.workers.rate_limit_retry import retry_budget
from app.workers.tenant_llm_middleware import (
    TenantLLMSettingsMiddleware,
    _tenant_id_from_message,
)


def _message(monkeypatch, options, actor_name="actor_x"):
    message = SimpleNamespace(options=options, actor_name=actor_name)
    monkeypatch.setattr(
        rate_limit_retry.CurrentMessage,
        "get_current_message",
        classmethod(lambda cls: message),
    )
    return message


class TestRetryBudgetDegradado:
    def test_sonda_del_mensaje_falla_y_no_hay_presupuesto(self, monkeypatch):
        def _boom(cls):
            raise RuntimeError("broker caido a mitad de lectura")

        monkeypatch.setattr(
            rate_limit_retry.CurrentMessage, "get_current_message", classmethod(_boom)
        )
        assert retry_budget() == (0, None)

    def test_sin_mensaje_no_hay_presupuesto(self, monkeypatch):
        monkeypatch.setattr(
            rate_limit_retry.CurrentMessage,
            "get_current_message",
            classmethod(lambda cls: None),
        )
        assert retry_budget() == (0, None)

    def test_retries_no_numericos_cuentan_como_cero(self, monkeypatch):
        _message(monkeypatch, {"retries": "muchisimos", "max_retries": 3})
        assert retry_budget() == (0, 3)

    def test_actor_desconocido_deja_max_retries_vacio(self, monkeypatch):
        _message(monkeypatch, {"retries": 2}, actor_name="actor_que_no_existe")

        class _Broker:
            def get_actor(self, name):
                raise KeyError(name)

        monkeypatch.setattr(dramatiq, "get_broker", lambda: _Broker())
        assert retry_budget() == (2, None)

    def test_mensaje_sin_actor_no_consulta_al_broker(self, monkeypatch):
        _message(monkeypatch, {"retries": 2}, actor_name=None)

        def _prohibido():
            raise AssertionError("sin actor no hay actor que buscar")

        monkeypatch.setattr(dramatiq, "get_broker", _prohibido)
        assert retry_budget() == (2, None)

    def test_max_retries_no_numerico_se_descarta(self, monkeypatch):
        _message(monkeypatch, {"retries": 1, "max_retries": "infinitos"})
        assert retry_budget() == (1, None)


class TestTenantIdFromMessage:
    def test_actor_irresoluble_degrada_a_sin_tenant(self):
        class _Broker:
            def get_actor(self, name):
                raise LookupError(name)

        message = SimpleNamespace(kwargs={}, args=(1, 2), actor_name="x")
        assert _tenant_id_from_message(_Broker(), message) is None

    def test_tenant_por_posicion_en_la_firma(self):
        def fn(tenant_id, payload):
            return None

        class _Broker:
            def get_actor(self, name):
                return SimpleNamespace(fn=fn)

        message = SimpleNamespace(kwargs={}, args=(7, "p"), actor_name="x")
        assert _tenant_id_from_message(_Broker(), message) == 7

    def test_tenant_no_entero_no_se_acepta(self):
        def fn(tenant_id):
            return None

        class _Broker:
            def get_actor(self, name):
                return SimpleNamespace(fn=fn)

        message = SimpleNamespace(kwargs={}, args=("admin",), actor_name="x")
        assert _tenant_id_from_message(_Broker(), message) is None


class TestMiddlewareCleanup:
    def test_store_token_degrada_a_atributo_si_options_no_acepta_escritura(self):
        class _Options(dict):
            def __setitem__(self, key, value):
                raise TypeError("options congeladas")

        message = SimpleNamespace(options=_Options())
        TenantLLMSettingsMiddleware._store_token(message, "tok-1")
        assert message._tenant_llm_token == "tok-1"

    def test_reset_lee_el_token_del_atributo_si_options_no_es_dict(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(
            "app.llm.tenant_config.reset_tenant_llm_config", llamadas.append
        )
        middleware = TenantLLMSettingsMiddleware()
        message = SimpleNamespace(options=None, _tenant_llm_token="tok-attr")
        middleware._reset(message)
        assert llamadas == ["tok-attr"]

    def test_reset_sin_token_es_noop(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(
            "app.llm.tenant_config.reset_tenant_llm_config", llamadas.append
        )
        middleware = TenantLLMSettingsMiddleware()
        middleware._reset(SimpleNamespace(options={}))
        assert llamadas == []

    def test_after_skip_message_tambien_resetea(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(
            "app.llm.tenant_config.reset_tenant_llm_config", llamadas.append
        )
        middleware = TenantLLMSettingsMiddleware()
        message = SimpleNamespace(options={"_tenant_llm_token": "tok-skip"})
        middleware.after_skip_message(object(), message)
        assert llamadas == ["tok-skip"]
        assert "_tenant_llm_token" not in message.options
