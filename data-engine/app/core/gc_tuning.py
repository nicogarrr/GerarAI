"""Recolector de basura del proceso de la API.

Tras el arranque, la API tiene ~575.000 objetos de larga vida (modulos,
metadatos ORM, rutas, esquemas Pydantic) que el GC de Python vuelve a
recorrer en cada recoleccion completa durante las peticiones. Con 300
posiciones, /portfolio/intelligence pasaba ~0,4 s por peticion en pausas del
GC. ``gc.freeze()`` mueve esos objetos a la generacion permanente: el GC deja
de recorrerlos (y, en procesos que hacen fork, no se tocan sus paginas).

Solo lo llama el arranque de la API fuera de tests; los workers de Dramatiq y
el scheduler no pasan por ``lifespan``. No cambia umbrales del GC.
"""

from __future__ import annotations

import gc


def freeze_startup_heap() -> int:
    """Recoge la basura del arranque y congela lo que queda vivo.

    Devuelve cuantos objetos quedaron congelados. El ``gc.collect()`` previo
    evita congelar ciclos ya muertos (no se liberarian nunca).
    """
    gc.collect()
    gc.freeze()
    return gc.get_freeze_count()
