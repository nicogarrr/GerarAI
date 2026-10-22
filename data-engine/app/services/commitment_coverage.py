"""Cobertura de seguimiento de llamadas por ticker (union cartera + watchlist).

El universo se lee de la cuenta real de Nico (solo lectura, 2026-10-22); los
tickers son identificadores, sin importes. La cobertura se DERIVA del registro de
fuentes; nada se declara cumplido sin fuente. Ausencia en el registro significa
"sin fuente resuelta", no "no existe".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.commitment_calendar import next_calls
from app.services.commitment_financial_release import FINANCIAL_ASSETS
from app.services.commitment_source_check_job import job_target_tickers, read_job_run
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
    transcript_origins: tuple[str, ...]  # href_ir_leido | url_dominio_oficial_por_busqueda
    press_release_registered: bool
    checkable_by_job: bool  # el job puede chequear (activo con call_date o comunicado)
    pending: tuple[str, ...]
    transcript_sources: tuple[dict, ...] = ()
    press_release_sources: tuple[dict, ...] = ()


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
        transcript_origins=tuple(sorted({a.origin for a in assets})),
        press_release_registered=pr,
        checkable_by_job=bool(dated or pr),
        pending=tuple(pending),
        transcript_sources=tuple(
            {"url": a.url, "period": a.period, "call_date": a.call_date, "origin": a.origin,
             "format": a.format, "label": a.label,
             "call_date_source": a.call_date_source,
             "completeness": a.completeness} for a in assets),
        press_release_sources=tuple(
            {"url": a.url, "period": a.period, "kind": a.kind}
            for a in FINANCIAL_ASSETS if a.ticker == ticker),
    )


def universe_coverage(universe: tuple[str, ...] | None = None) -> list[TickerCoverage]:
    return [coverage_for(t) for t in (UNIVERSE if universe is None else universe)]


def coverage_with_checks(
    latest: dict[str, dict], universe: tuple[str, ...] | None = None, today: date | None = None,
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
        rows.append({**c.__dict__, "pending": list(c.pending), "transcript_origins": list(c.transcript_origins),
                     "next_calls": next_calls(c.ticker, today or date.today()),
                     "transcript_sources": list(c.transcript_sources),
                     "press_release_sources": list(c.press_release_sources), "state": state,
                     "last_checked_on": last, "outcomes": outcomes,
                     "from_history": any(r.get("_source") == "historial" for r in mine),
                     "last_good_checked_on": max(
                         (r.get("last_good_checked_on") or "" for r in mine), default="") or None,
                     "universe_static_snapshot": UNIVERSE_IS_STATIC_SNAPSHOT})
    return rows


def dynamic_universe(db) -> tuple[tuple[str, ...], dict[str, tuple[bool, bool]]]:
    """Universo DESDE LA BD del tenant (posiciones netas != 0 + watchlist), normalizado."""
    from sqlalchemy import func, select

    from app.models.entities import Company, Position, WatchItem

    net = (select(Position.company_id).group_by(Position.company_id)
           .having(func.sum(Position.quantity) != 0).subquery())
    held = {t.strip().upper() for (t,) in db.execute(
        select(Company.ticker).join(net, net.c.company_id == Company.id)) if t and t.strip()}
    watched = {s.strip().upper() for (s,) in db.execute(select(WatchItem.symbol))
               if s and s.strip()}
    universe = tuple(sorted(held | watched))
    return universe, {t: (t in held, t in watched) for t in universe}


def coverage_report(db, store) -> dict:
    """Cobertura dinamica + ultimo chequeo real + historial del universo (SOLO LECTURA, sin 500)."""
    universe, flags = dynamic_universe(db)
    latest, status = store.read_snapshot()
    rows = coverage_with_checks(latest, universe)
    degraded = status["latest"] != "ok" and not status.get("first_run")
    for r in rows:
        r["in_portfolio"], r["in_watchlist"] = flags[r["ticker"]]
        r["universe_static_snapshot"] = False
        if r["state"] == "nunca_chequeado":
            if r["ticker"] in status.get("evicted_tickers", []) or status.get("at_retention_cap"):
                r["state"] = "estado_fuera_retencion"  # puede haberse chequeado: desconocido
            elif status.get("first_run"):
                r["state"] = "sin_ejecuciones_aun"  # arranque normal, no averia
            elif degraded:
                r["state"] = "estado_del_almacen_no_fiable"  # no se afirma "nunca chequeado"
    wanted = set(universe)
    history = [h for h in store.read_history(limit=500) if h.get("ticker") in wanted][:50]
    return {
        "universe_source": "bd_tenant",
        "universe_size": len(universe),
        "store": status,
        "job_last_run": read_job_run(store),  # None = nunca ejecutado/ilegible; ok=False = fallo
        "note": "fuente_obtenida no equivale a seguimiento completo de compromisos",
        "companies": rows,
        "history": history,
    }
