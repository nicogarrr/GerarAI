"""Ingesta de cotizadas por grupo de industria SIC (fuentes gratis de la SEC; regla «comparables-sic-v1»).

Los comparables de un grupo (``sic_classification.SIC_INDUSTRY_GROUPS``) solo existen si la base tiene sus
fichas. Este módulo las descubre por CÓDIGO SIC, nunca por una lista de tickers:

1. ``www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=nnnn&output=atom``: todos los registrantes con ese
   SIC (CIK), paginado de 100 en 100.
2. ``www.sec.gov/files/company_tickers_exchange.json``: CIK → ticker y mercado. Solo entran los que cotizan en
   un mercado regulado de EE. UU. (Nasdaq, NYSE, NYSE American, Cboe); una privada (SpaceX) no está y nunca
   entra con múltiplo.

Ritmo de la SEC: ≤ 10 peticiones/s (pausa entre páginas); un 429/403 corta la pasada, sin reintentos en bucle.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

BROWSE_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=&dateb=&owner=include"
              "&start={start}&count=100&output=atom")
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
LISTED_EXCHANGES = frozenset({"Nasdaq", "NYSE", "NYSE American", "CBOE"})
PAGE = 100
MAX_PAGES = 40
_CIK = re.compile(r"<cik>(\d+)</cik>")


class SecRefused(RuntimeError):
    """La SEC respondió 429/403: se para la pasada (sin reintentos en bucle)."""


def codes(ranges: Iterable[tuple[int, int]]) -> list[int]:
    out: list[int] = []
    for lo, hi in ranges:
        out.extend(range(int(lo), int(hi) + 1))
    return out


def parse_ciks(atom: str) -> list[int]:
    return [int(c) for c in _CIK.findall(atom or "")]


def ciks_for_sic(sic: int, get_text: Callable[[str], str], pause: Callable[[], None] = lambda: None) -> set[int]:
    out: set[int] = set()
    for page in range(MAX_PAGES):
        got = parse_ciks(get_text(BROWSE_URL.format(sic=int(sic), start=page * PAGE)))
        out.update(got)
        pause()
        if len(got) < PAGE:
            break
    return out


def listed_by_cik(tickers_json: Mapping[str, Any]) -> dict[int, tuple[str, str, str]]:
    """{cik: (ticker, nombre, mercado)} de los que cotizan en un mercado regulado (el primer ticker del CIK:
    la SEC los lista con la clase principal primero)."""
    fields = list(tickers_json.get("fields") or ["cik", "name", "ticker", "exchange"])
    out: dict[int, tuple[str, str, str]] = {}
    for row in tickers_json.get("data") or []:
        rec = dict(zip(fields, row, strict=False))
        if rec.get("exchange") not in LISTED_EXCHANGES or not rec.get("ticker"):
            continue
        try:
            cik = int(rec["cik"])
        except (TypeError, ValueError):
            continue
        out.setdefault(cik, (str(rec["ticker"]).upper(), str(rec.get("name") or ""), str(rec["exchange"])))
    return out


def group_candidates(ranges: Iterable[tuple[int, int]], get_text: Callable[[str], str],
                     tickers_json: Mapping[str, Any], pause: Callable[[], None] = lambda: None
                     ) -> list[dict[str, Any]]:
    """Cotizadas del grupo: [{cik, ticker, name, exchange, sic}] ordenadas por ticker (determinista)."""
    listed = listed_by_cik(tickers_json)
    seen: dict[int, dict[str, Any]] = {}
    for sic in codes(ranges):
        for cik in sorted(ciks_for_sic(sic, get_text, pause)):
            if cik in listed and cik not in seen:
                tk, name, ex = listed[cik]
                seen[cik] = {"cik": cik, "ticker": tk, "name": name, "exchange": ex, "sic": sic}
    return sorted(seen.values(), key=lambda r: r["ticker"])


__all__ = ["BROWSE_URL", "LISTED_EXCHANGES", "TICKERS_URL", "SecRefused", "ciks_for_sic", "codes",
           "group_candidates", "listed_by_cik", "parse_ciks"]
