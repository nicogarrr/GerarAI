"""Troceo de listas para cláusulas ``IN``.

Sin trocear, una ``IN`` con miles de valores puede acercarse al límite de
variables de la sentencia (sqlite histórico: 999; moderno: 32766; Postgres:
65535) y genera sentencias gigantes de parsear. Los lotes preservan el orden
de entrada; el tamaño por defecto se lee en cada llamada para que los tests
puedan bajarlo con ``monkeypatch``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")

SQL_IN_CHUNK_SIZE = 2000


def sql_in_chunks(values: Iterable[T], *, size: int | None = None) -> Iterator[list[T]]:
    """Lotes consecutivos de ``values`` (máx. ``size``) para cláusulas IN."""
    chunk_size = SQL_IN_CHUNK_SIZE if size is None else size
    if chunk_size < 1:
        raise ValueError("size debe ser >= 1")
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) >= chunk_size:
            yield batch
            batch = []
    if batch:
        yield batch
