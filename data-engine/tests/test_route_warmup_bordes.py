"""Bordes de ``app.core.route_warmup``: rama de baja prioridad y arranque en hilo.

Lo que cada test demuestra:
- ``warm_route_contexts`` invoca ``effective_low_priority_routes`` cuando la
  ruta lo expone (rama 39->44) y cuenta ese router como precalentado.
- ``start_route_warmup`` lanza un hilo daemon con nombre fijo que ejecuta el
  precalentado sin bloquear el arranque (52-67).
"""

from __future__ import annotations

from types import SimpleNamespace

import app.core.route_warmup as warmup
from app.core.route_warmup import start_route_warmup, warm_route_contexts


def test_ruta_con_low_priority_se_invoca_y_cuenta():
    llamadas = []

    class _Ruta:
        def effective_candidates(self):
            return []

        def effective_low_priority_routes(self):
            llamadas.append("low")

    app = SimpleNamespace(router=SimpleNamespace(routes=[_Ruta()]))
    assert warm_route_contexts(app) == 1
    assert llamadas == ["low"]


def test_ruta_sin_low_priority_cuenta_sin_invocarlo():
    class _Ruta:
        effective_low_priority_routes = None  # FastAPI viejo: no existe

        def effective_candidates(self):
            return []

    app = SimpleNamespace(router=SimpleNamespace(routes=[_Ruta()]))
    assert warm_route_contexts(app) == 1


def test_start_route_warmup_lanza_hilo_daemon_que_precalienta(monkeypatch):
    vistos = []

    def fake_warm(app):
        vistos.append(app)
        return 2

    monkeypatch.setattr(warmup, "warm_route_contexts", fake_warm)
    app = SimpleNamespace(router=SimpleNamespace(routes=[]))
    thread = start_route_warmup(app)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert thread.daemon is True
    assert thread.name == "gerarai-route-warmup"
    assert vistos == [app]
