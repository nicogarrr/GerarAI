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

    __slots__ = ("_exact", "_normalized", "_titles")

    def __init__(self, entries: Iterable[tuple[str, ...]]) -> None:
        self._exact: dict[str, str] = {}
        self._normalized: dict[str, set[str]] = {}
        # Razón social SEC por CIK (3.er elemento opcional de cada entrada):
        # sin ella el fallback por línea US no tiene identidad que contrastar.
        self._titles: dict[str, str] = {}
        for entry in entries:
            ticker, cik = str(entry[0]), str(entry[1])
            self._exact.setdefault(ticker.upper(), cik)
            self._normalized.setdefault(normalize_sec_ticker(ticker), set()).add(cik)
            if len(entry) > 2 and str(entry[2]).strip():
                self._titles.setdefault(cik, str(entry[2]).strip())

    def lookup(self, wanted: str) -> str | None:
        wanted_upper = wanted.strip().upper()
        exact = self._exact.get(wanted_upper)
        if exact is not None:
            return exact
        matches = self._normalized.get(normalize_sec_ticker(wanted_upper), set())
        return next(iter(matches)) if len(matches) == 1 else None

    def lookup_foreign_base(self, wanted: str, entity_name: str | None) -> str | None:
        """CIK de la línea US de un listado local con sufijo de mercado.

        Los 40-F/20-F se indexan en company_tickers.json por la línea
        americana del emisor; el listado local (ALF.TO) no aparece y la
        ingesta terminaba en «Sin CIK» para emisores que SÍ presentan a la
        SEC. Fail closed, como el resto de la capa: solo con sufijo de
        mercado conocido, nombre de ficha para contrastar, match único del
        base y razón social SEC compatible. Un homónimo US del ticker base
        (PRM de PRIM -> Perimeter) nunca recibe los hechos.
        """
        wanted_upper = wanted.strip().upper()
        name = (entity_name or "").strip()
        if not name or "." not in wanted_upper:
            return None
        base, _, suffix = wanted_upper.rpartition(".")
        from app.services.company_resolver import KNOWN_MARKET_SUFFIXES

        if not base or suffix not in KNOWN_MARKET_SUFFIXES:
            return None
        cik = self.lookup(base)
        if cik is None:
            return None
        title = self._titles.get(cik, "")
        if not title:
            return None
        from app.services.company_identity_verification import names_compatible

        return cik if names_compatible(title, name) else None


def match_cik(entries: Iterable[tuple[str, str]], wanted: str) -> str | None:
    """CIK para ``wanted`` dentro de pares (ticker_sec, cik), o None.

    Exacto primero; normalizado solo si es único. Los CIK se devuelven tal
    cual llegan (el caller decide el padding).
    """
    return CikIndex(entries).lookup(wanted)
