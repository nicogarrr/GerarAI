"""Lectura de DividendRecord sin doble conteo por reajuste de splits.

Yahoo chart devuelve UN evento por fecha ex y su importe va AJUSTADO por los
splits posteriores (AAPL 2020: 0.1925 ajustado vs 0.77 declarado). La ingesta
deduplica por (empresa, ex_date, amount), asi que tras un split una fila vieja
(0.77) y la reajustada (0.1925) coexisten para la misma ex_date y los
consumidores (TTM, proyeccion) las sumarian.

Solo se colapsan las filas de Yahoo (un evento por fecha y divisa, la mas
reciente por fetched_at). Otras fuentes (FMP puede traer ordinario + especial el
mismo dia) NO se tocan, y no se borra ni se actualiza ninguna fila.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

YAHOO_SOURCE = "yahoo_finance"


def collapse_yahoo_readjusted(records: Iterable[Any]) -> list[Any]:
    kept: list[Any] = []
    latest: dict[tuple[Any, Any, Any], Any] = {}
    for record in records:
        if record.source != YAHOO_SOURCE:
            kept.append(record)
            continue
        key = (record.company_id, record.ex_date, record.currency)
        current = latest.get(key)
        if current is None or _stamp(record) >= _stamp(current):
            latest[key] = record
    kept.extend(latest.values())
    return kept


def _stamp(record: Any) -> tuple[datetime, int]:
    fetched = record.fetched_at or datetime.min.replace(tzinfo=None)
    return (fetched.replace(tzinfo=None), record.id or 0)
