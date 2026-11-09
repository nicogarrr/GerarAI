"""IN por lotes acotados.

SQLite aborta con "too many SQL variables" al pasar de su limite de variables
(999 en muchas builds; los datos reales de facts/fuentes lo superan con
creces) y un IN gigante degrada tambien en Postgres. 500 deja margen de
sobra para el resto de parametros de la consulta en ambos motores.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")

IN_CHUNK_SIZE = 500


def chunked(values: Iterable[T], size: int | None = None) -> Iterator[list[T]]:
    """Lotes de como mucho ``size`` elementos (por defecto IN_CHUNK_SIZE)."""
    limit = size or IN_CHUNK_SIZE
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) >= limit:
            yield batch
            batch = []
    if batch:
        yield batch
