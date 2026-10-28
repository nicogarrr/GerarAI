"""Auditor de cobertura de cierres oficiales (market_prices, source="yfinance").

SOLO LECTURA. No escribe, no llama a proveedores, no toca el actor de precios
(sync_official_closes) ni sustituye cierres por cotizaciones spot. Para una
sesion S responde, empresa a empresa, DONDE cae cada una y POR QUE falta:

    python scripts/audit_close_coverage.py                       # ultima sesion comun
    python scripts/audit_close_coverage.py --session 2026-10-27  # una sesion concreta
    python scripts/audit_close_coverage.py --json out.json       # volcado
    python scripts/audit_close_coverage.py --previous antes.json # reconcilia con otro volcado
    python scripts/audit_close_coverage.py --fail-under 80       # opcional: sale 1 si cobertura elegible < 80 %

Reparto (cada empresa cae en UNA sola categoria; la suma es el total):

  fuera_de_universo  sin simbolo Yahoo seguro (yahoo_symbol is None). El actor
                     NO la pide a proposito: no es un hueco, es perimetro.
                     Causas: sin_ticker, bolsa_sin_sufijo_mapeado,
                     divisa_no_usd_sin_bolsa.
  cubierta           elegible con cierre yfinance en S.
  falta              elegible SIN cierre en S, con causa verificable:
    sesion_sin_barras_en_su_bolsa  casi toda su bolsa (sufijo) tampoco tiene S
                                   pero SI la sesion anterior: festivo o cierre
                                   de ESA bolsa. Se infiere de los pares, no de
                                   un calendario inventado.
    unidad_no_verificable          el actor descarta la barra: bolsa con unidad
                                   propia (.L en peniques) y sin divisa
                                   declarada que coincida (bar_unit_is_known).
    sin_barras_desde               ultimo cierre mas de N sesiones antes de S
                                   mientras sus pares si tienen S: posible
                                   deslistado/suspendido (con la fecha).
    rezagada                       tiene barras, solo le faltan las ultimas
                                   sesiones: ingesta atrasada o lote fallido.
    nunca_ingerida                 elegible y sin ninguna barra yfinance.

Cuando la inferencia por pares no es posible (bolsa con menos de MIN_PEERS
empresas) no se afirma festivo: la causa cae a la siguiente.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.entities import Company, MarketPrice  # noqa: E402
from app.services.market_change import OFFICIAL_CLOSE_SOURCES, common_sessions  # noqa: E402
from app.services.propicks_price_service import (  # noqa: E402
    _EXCHANGE_YAHOO_SUFFIX,
    _US_EXCHANGE_TOKENS,
    PriceBar,
    _symbol_suffix,
    bar_unit_is_known,
    yahoo_symbol,
)

MIN_PEERS = 3  # pares minimos de una bolsa para inferir festivo/cierre
PEER_CLOSED_MAX_SHARE = 0.10  # <=10 % de la bolsa con barra en S -> bolsa cerrada
PEER_OPEN_MIN_SHARE = 0.50  # >=50 % con barra en S -> la bolsa operaba
STALE_SESSIONS = 5  # mas sesiones que esto sin barras = posible deslistado
MAX_LISTED = 500  # filas de detalle en el informe


def weekdays_between(start: date, end: date) -> int:
    """Dias laborables en (start, end]: sesiones que le faltan a quien cerro en `start`."""
    if end <= start:
        return 0
    days = (end - start).days
    return sum(1 for i in range(1, days + 1) if (start + timedelta(days=i)).weekday() < 5)


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def out_of_universe_cause(company: Company) -> str:
    """Por que yahoo_symbol devolvio None (mismas ramas que yahoo_symbol)."""
    if not (company.ticker or "").strip():
        return "sin_ticker"
    exchange = (company.exchange or "").strip().upper()
    us_exchange = not exchange or exchange == "UNKNOWN" or any(t in exchange for t in _US_EXCHANGE_TOKENS)
    if exchange and not us_exchange and exchange not in _EXCHANGE_YAHOO_SUFFIX:
        return "bolsa_sin_sufijo_mapeado"
    return "divisa_no_usd_sin_bolsa"


def venue_of(symbol: str) -> str:
    return _symbol_suffix(symbol) or "US"


def audit(db: Session, *, session_day: date | None = None) -> dict[str, Any]:
    """Informe de cobertura para `session_day` (por defecto, la ultima sesion comun)."""
    common, common_prev = common_sessions(db)
    session_day = session_day or common
    if session_day is None:
        return {"session": None, "total": 0, "note": "sin cierres oficiales en market_prices"}
    previous_day = previous_weekday(session_day)

    companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
    symbols = {c.id: yahoo_symbol(c) for c in companies}

    official = MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES)
    on_session = {
        cid: unit
        for cid, unit in db.execute(
            select(MarketPrice.company_id, MarketPrice.quote_currency).where(official, MarketPrice.date == session_day)
        ).all()
    }
    on_previous = {
        cid for (cid,) in db.execute(select(MarketPrice.company_id).where(official, MarketPrice.date == previous_day)).all()
    }
    last_date = {
        cid: day
        for cid, day in db.execute(
            select(MarketPrice.company_id, func.max(MarketPrice.date)).where(official, MarketPrice.date <= session_day).group_by(MarketPrice.company_id)
        ).all()
    }

    # Pares por bolsa (solo elegibles): evidencia de festivo / cierre de la plaza.
    venue_members: dict[str, list[int]] = defaultdict(list)
    for cid, symbol in symbols.items():
        if symbol is not None:
            venue_members[venue_of(symbol)].append(cid)

    def venue_stats(venue: str) -> dict[str, Any]:
        members = venue_members[venue]
        n = len(members)
        with_s = sum(1 for cid in members if cid in on_session)
        with_prev = sum(1 for cid in members if cid in on_previous)
        return {
            "venue": venue,
            "eligible": n,
            "with_session": with_s,
            "with_previous": with_prev,
            "share_session": round(with_s / n, 4) if n else 0.0,
            "share_previous": round(with_prev / n, 4) if n else 0.0,
        }

    stats = {venue: venue_stats(venue) for venue in venue_members}

    counts: dict[str, int] = defaultdict(int)
    causes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    listed: list[dict[str, Any]] = []
    classification: dict[int, str] = {}

    for company in companies:
        cid = company.id
        symbol = symbols[cid]
        if symbol is None:
            category, cause, evidence = "fuera_de_universo", out_of_universe_cause(company), {}
        elif cid in on_session:
            category, cause = "cubierta", "con_cierre"
            evidence = {"quote_currency": on_session[cid]} if on_session[cid] else {"unidad": "sin_declarar"}
            if not on_session[cid]:
                cause = "con_cierre_sin_unidad_declarada"
        else:
            category = "falta"
            venue = venue_of(symbol)
            st = stats[venue]
            last = last_date.get(cid)
            lag = weekdays_between(last, session_day) if last else None
            peers_ok = st["eligible"] >= MIN_PEERS
            probe = PriceBar(day=session_day, close=0, adj_close=0, volume=0)  # type: ignore[arg-type]
            if peers_ok and st["share_session"] <= PEER_CLOSED_MAX_SHARE and st["share_previous"] >= PEER_OPEN_MIN_SHARE:
                cause = "sesion_sin_barras_en_su_bolsa"
                evidence = {"venue": venue, "share_session": st["share_session"], "share_previous": st["share_previous"], "inferred_from_peers": True}
            elif not bar_unit_is_known(company, probe):
                cause = "unidad_no_verificable"
                evidence = {"venue": venue, "currency": company.currency}
            elif last is None:
                cause = "nunca_ingerida"
                evidence = {"venue": venue}
            elif lag is not None and lag > STALE_SESSIONS and st["share_session"] >= PEER_OPEN_MIN_SHARE:
                cause = "sin_barras_desde"
                evidence = {"last_close": last.isoformat(), "sessions_behind": lag, "venue": venue}
            else:
                cause = "rezagada"
                evidence = {"last_close": last.isoformat() if last else None, "sessions_behind": lag, "venue": venue}
        classification[cid] = category
        counts[category] += 1
        causes[category][cause] += 1
        if category != "cubierta" and len(listed) < MAX_LISTED:
            listed.append({
                "company_id": cid,
                "ticker": company.ticker,
                "exchange": company.exchange,
                "currency": company.currency,
                "symbol": symbol,
                "category": category,
                "cause": cause,
                "evidence": evidence,
            })

    total = len(companies)
    eligible = total - counts["fuera_de_universo"]
    covered = counts["cubierta"]
    assert sum(counts.values()) == total  # el reparto cierra: cada empresa en una categoria
    return {
        "session": session_day.isoformat(),
        "previous_session": previous_day.isoformat(),
        "common_session": common.isoformat() if common else None,
        "total": total,
        "eligible": eligible,
        "out_of_universe": counts["fuera_de_universo"],
        "covered": covered,
        "missing": counts["falta"],
        "coverage_pct_of_eligible": round(100 * covered / eligible, 2) if eligible else None,
        "coverage_pct_of_total": round(100 * covered / total, 2) if total else None,
        "categories": {k: dict(v) for k, v in causes.items()},
        "venues": sorted(stats.values(), key=lambda s: (-s["eligible"], s["venue"])),
        "detail_truncated": (total - covered) > len(listed),
        "detail": listed,
        "covered_ids": sorted(cid for cid, cat in classification.items() if cat == "cubierta"),
        "universe_ids": sorted(cid for cid, cat in classification.items() if cat != "fuera_de_universo"),
    }


def reconcile(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Diferencia entre dos informes: que empresas entraron/salieron del universo y de la cobertura.

    Explica un cambio de cifra (p. ej. 180 -> 185) por identidad, no por resta:
    cada empresa nueva/perdida aparece en una lista, y la cuenta tiene que cerrar.
    """
    cur_u, prev_u = set(current.get("universe_ids", [])), set(previous.get("universe_ids", []))
    cur_c, prev_c = set(current.get("covered_ids", [])), set(previous.get("covered_ids", []))
    out = {
        "universe": {"previous": len(prev_u), "current": len(cur_u), "entered": sorted(cur_u - prev_u), "left": sorted(prev_u - cur_u)},
        "covered": {"previous": len(prev_c), "current": len(cur_c), "gained": sorted(cur_c - prev_c), "lost": sorted(prev_c - cur_c)},
    }
    out["covered"]["closes"] = len(cur_c) - len(prev_c) == len(out["covered"]["gained"]) - len(out["covered"]["lost"])
    out["universe"]["closes"] = len(cur_u) - len(prev_u) == len(out["universe"]["entered"]) - len(out["universe"]["left"])
    return out


def render(report: dict[str, Any]) -> str:
    if report.get("session") is None:
        return "Sin cierres oficiales en market_prices.\n"
    lines = [
        f"Sesion {report['session']} (anterior {report['previous_session']}; ultima comun {report['common_session']})",
        f"Empresas: {report['total']} | elegibles: {report['eligible']} | fuera de universo: {report['out_of_universe']}",
        f"Cubiertas: {report['covered']} ({report['coverage_pct_of_eligible']} % de elegibles, {report['coverage_pct_of_total']} % del total) | faltan: {report['missing']}",
        "",
    ]
    for category, by_cause in sorted(report["categories"].items()):
        lines.append(f"{category}: {sum(by_cause.values())}")
        lines.extend(f"  {cause}: {n}" for cause, n in sorted(by_cause.items(), key=lambda kv: -kv[1]))
    lines += ["", "Bolsas (elegibles / con cierre en S / con cierre en S-1):"]
    lines.extend(f"  {v['venue']}: {v['eligible']} / {v['with_session']} / {v['with_previous']}" for v in report["venues"][:20])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session", type=date.fromisoformat, default=None)
    parser.add_argument("--json", type=Path, default=None, help="escribe el informe completo")
    parser.add_argument("--previous", type=Path, default=None, help="informe JSON anterior a reconciliar")
    parser.add_argument("--fail-under", type=float, default=None, help="sale 1 si la cobertura de elegibles baja de este %")
    args = parser.parse_args(argv)

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        report = audit(db, session_day=args.session)
    finally:
        db.close()
    sys.stdout.write(render(report))
    if args.previous is not None and report.get("session"):
        rec = reconcile(report, json.loads(args.previous.read_text()))
        sys.stdout.write(
            f"\nReconciliacion: universo {rec['universe']['previous']} -> {rec['universe']['current']} "
            f"(+{len(rec['universe']['entered'])}/-{len(rec['universe']['left'])}); cubiertas {rec['covered']['previous']} -> "
            f"{rec['covered']['current']} (+{len(rec['covered']['gained'])}/-{len(rec['covered']['lost'])})\n"
        )
        report["reconciliation"] = rec
    if args.json is not None:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.fail_under is not None and (report.get("coverage_pct_of_eligible") or 0) < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
