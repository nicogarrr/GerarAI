"""Cobertura de seguimiento de llamadas por ticker (union cartera + watchlist).

El universo se lee de la cuenta real de Nico (solo lectura, 2026-10-22); los
tickers son identificadores, sin importes. La cobertura se DERIVA del registro de
fuentes; nada se declara cumplido sin fuente. Ausencia en el registro significa
"sin fuente resuelta", no "no existe".
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.commitment_financial_release import FINANCIAL_ASSETS
from app.services.transcript_source_registry import all_entries

UNIVERSE_READ_ON = "2026-10-22"
PORTFOLIO = ("ASTS", "BN", "RKLB", "UBER", "BABA", "ONDS", "HYMC", "KRKNF")
WATCHLIST = ("CGEO.L", "CPT", "BN", "KKR", "POOL", "CB", "UNH", "HIMS", "RXRX",
             "NAUT", "ABCL", "IBRX", "AAPL")

UNIVERSE: tuple[str, ...] = tuple(dict.fromkeys(PORTFOLIO + WATCHLIST))


@dataclass(frozen=True)
class TickerCoverage:
    ticker: str
    in_portfolio: bool
    in_watchlist: bool
    transcript_status: str  # estado del registro o "sin_fuente_resuelta"
    transcript_assets: int
    transcript_assets_with_call_date: int
    press_release_registered: bool
    checkable_by_job: bool  # el job puede chequear (activo con call_date o comunicado)
    pending: tuple[str, ...]


def coverage_for(ticker: str) -> TickerCoverage:
    entries = {e.ticker: e for e in all_entries()}
    e = entries.get(ticker)
    assets = e.assets if e else ()
    dated = sum(1 for a in assets if a.call_date)
    pr = any(a.ticker == ticker for a in FINANCIAL_ASSETS)
    pending: list[str] = []
    if e is None:
        pending.append("resolver_fuente_oficial_de_transcripcion")
    elif not assets:
        pending.append("sin_activo_de_transcripcion_verificado")
    if assets and dated < len(assets):
        pending.append("leer_fecha_de_llamada_del_documento")
    if not pr:
        pending.append("sin_comunicado_financiero_registrado")
    return TickerCoverage(
        ticker=ticker,
        in_portfolio=ticker in PORTFOLIO,
        in_watchlist=ticker in WATCHLIST,
        transcript_status=e.status if e else "sin_fuente_resuelta",
        transcript_assets=len(assets),
        transcript_assets_with_call_date=dated,
        press_release_registered=pr,
        checkable_by_job=bool(dated or pr),
        pending=tuple(pending),
    )


def universe_coverage() -> list[TickerCoverage]:
    return [coverage_for(t) for t in UNIVERSE]
