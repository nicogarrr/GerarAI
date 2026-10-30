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


class CikIndex:
    """Indice ticker -> CIK construido UNA vez sobre ``company_tickers.json``.

    Misma politica que :func:`match_cik` (exacto primero, el primero que
    aparece gana; normalizado solo si es unico), pero cada busqueda es O(1)
    en vez de recorrer los ~10.000 emisores.
    """

    __slots__ = ("_exact", "_normalized")

    def __init__(self, entries: Iterable[tuple[str, str]]) -> None:
        self._exact: dict[str, str] = {}
        self._normalized: dict[str, set[str]] = {}
        for ticker, cik in entries:
            ticker, cik = str(ticker), str(cik)
            self._exact.setdefault(ticker.upper(), cik)
            self._normalized.setdefault(normalize_sec_ticker(ticker), set()).add(cik)

    def lookup(self, wanted: str) -> str | None:
        wanted_upper = wanted.strip().upper()
        exact = self._exact.get(wanted_upper)
        if exact is not None:
            return exact
        matches = self._normalized.get(normalize_sec_ticker(wanted_upper), set())
        return next(iter(matches)) if len(matches) == 1 else None


def match_cik(entries: Iterable[tuple[str, str]], wanted: str) -> str | None:
    """CIK para ``wanted`` dentro de pares (ticker_sec, cik), o None.

    Exacto primero; normalizado solo si es único. Los CIK se devuelven tal
    cual llegan (el caller decide el padding).
    """
    return CikIndex(entries).lookup(wanted)
