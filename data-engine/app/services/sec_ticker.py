"""Lookup ticker -> CIK tolerante a la notación de clase (BRK.B vs BRK-B).

EDGAR (`company_tickers.json`) nombra las clases de acción con guion
(BRK-B) mientras el master y Finnhub usan punto (BRK.B). La comparación
exacta nunca casa para esos emisores y la ingesta SEC terminaba en
«Sin CIK para BRK.B»: la ficha se quedaba sin hechos persistidos.

Política (fail closed, como el resto de la capa SEC):
1. Match exacto (mismo ticker, case-insensitive) — siempre gana.
2. Si no hay exacto, comparación sin separadores [-./ ] SOLO cuando el
   match es único. Un empate ambiguo devuelve None: nunca se atribuyen
   hechos de un emisor a otro por una normalización dudosa.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_SEPARATORS = re.compile(r"[-./ ]")


def normalize_sec_ticker(ticker: str) -> str:
    """Forma comparable del ticker: sin separadores de clase, en mayúsculas."""
    return _SEPARATORS.sub("", ticker).upper()


def match_cik(entries: Iterable[tuple[str, str]], wanted: str) -> str | None:
    """CIK para ``wanted`` dentro de pares (ticker_sec, cik), o None.

    Exacto primero; normalizado solo si es único. Los CIK se devuelven tal
    cual llegan (el caller decide el padding).
    """
    pairs = [(str(ticker), str(cik)) for ticker, cik in entries]
    wanted_upper = wanted.strip().upper()
    for ticker, cik in pairs:
        if ticker.upper() == wanted_upper:
            return cik
    wanted_norm = normalize_sec_ticker(wanted_upper)
    matches = {cik for ticker, cik in pairs if normalize_sec_ticker(ticker) == wanted_norm}
    return next(iter(matches)) if len(matches) == 1 else None
