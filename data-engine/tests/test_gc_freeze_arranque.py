"""La API congela el heap del arranque (gc.freeze) fuera de tests.

Tras el arranque hay ~575.000 objetos de larga vida que el GC recorria en
cada recoleccion completa durante las peticiones (~0,4 s por peticion de
/portfolio/intelligence con 300 posiciones). Estos tests fijan que el helper
recoge antes de congelar y que el arranque lo llama solo fuera de tests (el
proceso de pytest crea muchas apps). No se arranca la app aqui: salir de
``lifespan`` apaga los ejecutores de sondas de nivel de modulo y romperia
los tests de /health que corran despues en el mismo proceso.
"""

from __future__ import annotations

import ast
import inspect

import main
from app.core import gc_tuning


def test_recoge_y_luego_congela(monkeypatch):
    llamadas: list[str] = []
    monkeypatch.setattr(gc_tuning.gc, "collect", lambda *a: llamadas.append("collect") or 0)
    monkeypatch.setattr(gc_tuning.gc, "freeze", lambda: llamadas.append("freeze"))
    monkeypatch.setattr(gc_tuning.gc, "get_freeze_count", lambda: 1234)
    assert gc_tuning.freeze_startup_heap() == 1234
    assert llamadas == ["collect", "freeze"]


def test_lifespan_congela_solo_fuera_de_tests():
    arbol = ast.parse(inspect.getsource(main.lifespan))
    llamadas = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.If)
        and any(
            isinstance(c, ast.Call) and getattr(c.func, "id", None) == "freeze_startup_heap"
            for c in ast.walk(nodo)
        )
    ]
    assert llamadas, "lifespan debe llamar a freeze_startup_heap"
    condicion = ast.unparse(llamadas[-1].test)
    assert "app_env" in condicion and "!= 'test'" in condicion, condicion
