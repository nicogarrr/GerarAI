"""Pausa del recolector ciclico durante calculos grandes de una peticion.

/portfolio/intelligence crea cientos de miles de objetos (cierres Decimal,
filas, retornos) que se liberan por refcount; el GC ciclico se disparaba
igualmente decenas de veces por peticion recorriendo el heap (~0,25 s de
1,6 s en el banco de 300 posiciones). Mientras dura el calculo se pausa y
al terminar se reactiva; la basura ciclica que quede la recoge la siguiente
pasada normal.

``gc.disable()`` es global al proceso: un contador con candado hace que
solo se reactive cuando termina el ULTIMO calculo en curso, y solo si el
GC estaba activo cuando empezo el primero (si alguien lo tenia apagado,
sigue apagado).
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_lock = threading.Lock()
_holders = 0
_reenable = False


@contextmanager
def gc_paused() -> Iterator[None]:
    global _holders, _reenable
    with _lock:
        if _holders == 0:
            _reenable = gc.isenabled()
            if _reenable:
                gc.disable()
        _holders += 1
    try:
        yield
    finally:
        with _lock:
            _holders -= 1
            if _holders == 0 and _reenable:
                _reenable = False
                gc.enable()
