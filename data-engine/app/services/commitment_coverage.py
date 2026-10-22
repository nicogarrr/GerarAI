"""Cobertura de seguimiento de llamadas por ticker (union cartera + watchlist).

El universo se lee de la cuenta real de Nico (solo lectura, 2026-10-22); los
tickers son identificadores, sin importes. La cobertura se DERIVA del registro de
fuentes; nada se declara cumplido sin fuente. Ausencia en el registro significa
"sin fuente resuelta", no "no existe".
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.commitment_financial_release import FINANCIAL_ASSETS
from app.services.commitment_source_check_job import job_target_tickers
from app.services.transcript_source_registry import all_entries

UNIVERSE_READ_ON = "2026-10-22"
PORTFOLIO = ("ASTS", "BN", "RKLB", "UBER", "BABA", "ONDS", "HYMC", "KRKNF")
WATCHLIST = ("CGEO.L", "CPT", "BN", "KKR", "POOL", "CB", "UNH", "HIMS", "RXRX",
             "NAUT", "ABCL", "IBRX", "AAPL")

# FOTO ESTATICA leida el 2026-10-22: NO se sincroniza con la cartera/watchlist de Nico.
# La cobertura dinamica (identidad/tenant desde fuente propia) esta PENDIENTE; mientras tanto
# todas las funciones aceptan `universe` para inyectar la lista real.
UNIVERSE: tuple[str, ...] = tuple(dict.fromkeys(PORTFOLIO + WATCHLIST))
UNIVERSE_IS_STATIC_SNAPSHOT = True


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


def universe_coverage(universe: tuple[str, ...] | None = None) -> list[TickerCoverage]:
    return [coverage_for(t) for t in (UNIVERSE if universe is None else universe)]


def coverage_with_checks(
    latest: dict[str, dict], universe: tuple[str, ...] | None = None,
) -> list[dict]:
    """Cobertura + ultimo chequeo REAL del job (latest.json). Sin chequeo => nunca_chequeado."""
    targets = job_target_tickers()
    rows = []
    for c in universe_coverage(universe):
        mine = [r for r in latest.values() if r.get("ticker") == c.ticker]
        outcomes = sorted({r.get("outcome", "?") for r in mine})
        last = max((r.get("checked_on", "") for r in mine), default=None)
        if not c.checkable_by_job or c.ticker not in targets:
            state = "sin_chequeo_posible"
        elif not mine:
            state = "nunca_chequeado"
        elif "error" in outcomes:
            state = "ultimo_chequeo_con_error"
        elif outcomes == ["extraido"]:
            state = "fuente_obtenida"  # NO equivale a seguimiento de compromisos completo
        else:
            state = "abstencion_en_chequeo"
        rows.append({**c.__dict__, "pending": list(c.pending), "state": state,
                     "last_checked_on": last, "outcomes": outcomes,
                     "universe_static_snapshot": UNIVERSE_IS_STATIC_SNAPSHOT})
    return rows


def dynamic_universe(db) -> tuple[tuple[str, ...], dict[str, tuple[bool, bool]]]:
    """Universo DESDE LA BD del tenant (posiciones netas != 0 + watchlist), no la foto estatica."""
    from sqlalchemy import func, select

    from app.models.entities import Company, Position, WatchItem

    net = (select(Position.company_id).group_by(Position.company_id)
           .having(func.sum(Position.quantity) != 0).subquery())
    held = {t for (t,) in db.execute(
        select(Company.ticker).join(net, net.c.company_id == Company.id))}
    watched = {s.upper() for (s,) in db.execute(select(WatchItem.symbol))}
    universe = tuple(sorted(held | watched))
    flags = {t: (t in held, t in watched) for t in universe}
    return universe, flags


def coverage_report(db, store) -> dict:
    """Cobertura dinamica + ultimo chequeo real del job + historial reciente (solo lectura)."""
    universe, flags = dynamic_universe(db)
    latest = store.load()
    rows = coverage_with_checks(latest, universe)
    for r in rows:
        r["in_portfolio"], r["in_watchlist"] = flags[r["ticker"]]
        r["universe_static_snapshot"] = False
    return {
        "universe_source": "bd_tenant",
        "universe_size": len(universe),
        "store_corrupt_quarantined": store.corrupt_quarantined,
        "note": "fuente_obtenida no equivale a seguimiento completo de compromisos",
        "companies": rows,
        "history": store.read_history(limit=50),
    }
