"""Caché de lecturas acotada a UNA llamada de valoración.

El motor de valoración consulta los mismos hechos muchas veces por llamada
(medido 4-nov-2026, lab: 202 SELECTs a financial_facts por ``value_company``,
revenue ×21, free_cash_flow ×20, cash ×20...; 14 SELECTs a fx_rates): cada
puente, cross-check y motor vuelve a pedir el mismo (company_id, metric).

Esta caché vive en ``db.info`` SOLO durante una llamada a
``ValuationService.value_company`` (el embudo por el que pasan todos los
consumidores: tesis, red team, snapshot, persistencia):

- Se instala al entrar y se borra SIEMPRE al salir (éxito o excepción), así
  que nunca sirve datos entre peticiones ni después de una escritura.
- La clave incluye el tenant de la sesión: un hecho de otro tenant no puede
  cruzar. ``db.info`` es por sesión y las sesiones no se comparten entre
  hilos, así que no hay fuga entre llamadas concurrentes.
- Fuera de una llamada de valoración (sin caché instalada) cada helper sigue
  el camino de siempre, consulta a consulta.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy.orm import Session

_CACHE_KEY = "valuation_call_cache_v1"
T = TypeVar("T")


@contextmanager
def valuation_call_cache(db: Session) -> Iterator[None]:
    """Instala la caché de llamada y la borra al salir, también en error.

    Anidamiento: si otra llamada ya la instaló (owns=False) no se toca al
    salir; el dueño la limpia.
    """
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        # Unit tests y consumidores que pasan un doble mínimo de sesión: sin
        # almacén por sesión no hay caché, pero la valoración debe funcionar.
        yield
        return
    owns = _CACHE_KEY not in info
    if owns:
        info[_CACHE_KEY] = {}
    try:
        yield
    finally:
        if owns:
            info.pop(_CACHE_KEY, None)


def cached(db: Session, namespace: str, key: object, producer: Callable[[], T]) -> T:
    """Resultado de ``producer()`` cacheado por (namespace, tenant, key).

    Sin caché instalada ejecuta ``producer()`` directamente: comportamiento
    idéntico al de antes fuera del embudo de valoración.
    """
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return producer()
    cache = info.get(_CACHE_KEY)
    if cache is None:
        return producer()
    full_key = (namespace, info.get("tenant_id"), key)
    if full_key not in cache:
        cache[full_key] = producer()
    return cache[full_key]
