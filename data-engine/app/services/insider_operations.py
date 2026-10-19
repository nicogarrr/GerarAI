"""Operaciones insider (compras P y ventas S) agregadas por empresa.

Vista de Nico (2026-10-19): tabla por empresa de su cartera IBKR y watchlist
— insider, cargo, importe vendido/comprado, acciones, precio medio y numero
de operaciones, con total y periodo. Lee SOLO lo persistido por el monitor
(insider_filings / insider_transactions): sin red, sin inventar.

Reglas de veracidad (auditor 2026-10-19):
- Mismo filtro que el feed: solo codigos P/S (mercado abierto) y filas NO
  derivadas; la fecha efectiva es coalesce(tx_date, filing_date). Lo demas
  se cuenta y declara (excluded_codes, excluded_derivative), nunca suma.
- Precio medio = importe / acciones SOLO sobre filas con acciones E importe;
  si hay filas sin importe el medio queda en None y se declara
  (shares_without_value): un medio parcial pareceria completo.
- Periodo calculado solo con filas P/S fechadas; empresa sin operaciones
  P/S en el periodo va a ``companies_without_data`` (no fila de ceros).
- Filas P/S sin ninguna fecha (ni tx_date ni filing_date) suman al agregado
  pero quedan fuera del periodo y se declaran en ``rows_without_date``.
- Agrupacion por insider (sin partir por titulo): el cargo mostrado es el
  de su fila mas reciente. Los filings conjuntos (multi_reporter) se
  persisten como UNA fila con los nombres juntos, asi que no duplican; el
  tramo a tramo se agrupa como en el feed (mismo accession+insider+codigo
  suma en la misma operacion). Enmiendas (4/A): ``amends_accession`` no se
  puebla en la ingesta, asi que el original sustituido no se puede
  identificar; se declara ``amended_filings`` por empresa en vez de
  ocultarlo.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import InsiderFiling, InsiderTransaction
from app.services.earnings_dates_service import followed_companies
from app.services.insider_feed import primary_ticker

SIDE_BY_CODE = {"P": "buy", "S": "sell"}


def _empty_side() -> dict[str, Any]:
    return {
        "trades": 0,
        "shares": 0.0,
        "value": 0.0,
        "_shares_priced": 0.0,
        "_shares_unpriced": 0.0,
        "_rows_without_value": 0,
    }


def _finish_side(side: dict[str, Any]) -> dict[str, Any]:
    shares_priced = side.pop("_shares_priced")
    shares_unpriced = side.pop("_shares_unpriced")
    rows_without_value = side.pop("_rows_without_value")
    # Solo un medio completo: importe y acciones de las MISMAS filas. Con
    # filas sin importe el medio seria parcial -> None, y se declara.
    avg = side["value"] / shares_priced if shares_priced and not rows_without_value else None
    return {
        "trades": side["trades"],
        "shares": round(side["shares"], 4),
        "value": round(side["value"], 2),
        "avg_price": round(avg, 4) if avg is not None else None,
        "shares_without_value": round(shares_unpriced, 4),
        "rows_without_value": rows_without_value,
    }


def insider_operations(db: Session, days: int = 365) -> dict[str, Any]:
    """Agregado por empresa (cartera + watchlist) e insider, ultimos `days` dias."""
    followed = followed_companies(db)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    # Sin filtro de codigo/fecha en SQL: los descartes se cuentan en Python
    # para declararlos (el WHERE los haria invisibles).
    rows = db.execute(
        select(InsiderTransaction, InsiderFiling)
        .join(InsiderFiling, InsiderTransaction.filing_id == InsiderFiling.id)
    ).all()

    by_ticker: dict[str, list[tuple[InsiderTransaction, InsiderFiling]]] = {}
    for tx, filing in rows:
        ticker = primary_ticker(tx.issuer_ticker or filing.issuer_ticker)
        if ticker and ticker.upper() in followed:
            by_ticker.setdefault(ticker.upper(), []).append((tx, filing))

    companies: list[dict[str, Any]] = []
    without_data: list[str] = []
    for ticker in sorted(followed):
        entries = by_ticker.get(ticker, [])
        insiders: dict[str, dict[str, Any]] = {}
        totals = {"buy": _empty_side(), "sell": _empty_side()}
        excluded_codes = 0
        excluded_derivative = 0
        rows_without_date = 0
        dates: list[str] = []
        accessions: set[str] = set()
        amended = 0
        for tx, filing in entries:
            side_key = SIDE_BY_CODE.get((tx.code or "").strip().upper())
            if side_key is None:
                excluded_codes += 1
                continue
            if tx.is_derivative:
                excluded_derivative += 1
                continue
            effective = tx.tx_date or filing.filing_date or ""
            if not effective:
                rows_without_date += 1
            else:
                if effective < cutoff:
                    continue
                dates.append(effective)
            accessions.add(filing.accession_number)
            if filing.is_amendment:
                amended += 1
            name = (tx.insider or "").strip() or "(sin nombre)"
            bucket = insiders.setdefault(
                name,
                {
                    "buy": _empty_side(),
                    "sell": _empty_side(),
                    "last_tx": "",
                    "role": None,
                    "officer_title": None,
                },
            )
            # El cargo mostrado es el de la fila mas reciente del insider.
            if effective >= bucket["last_tx"]:
                bucket["last_tx"] = effective
                bucket["role"] = tx.role
                bucket["officer_title"] = tx.officer_title
            for target in (bucket[side_key], totals[side_key]):
                target["trades"] += 1
                target["shares"] += tx.shares or 0.0
                if tx.value is not None:
                    target["value"] += tx.value
                    target["_shares_priced"] += tx.shares or 0.0
                else:
                    target["_shares_unpriced"] += tx.shares or 0.0
                    target["_rows_without_value"] += 1

        dated_ps = [t for t in dates]  # periodo solo de filas P/S fechadas
        if not any(bucket["buy"]["trades"] or bucket["sell"]["trades"] for bucket in insiders.values()):
            # Sin operaciones P/S en el periodo: se declara, no fila de ceros.
            without_data.append(ticker)
            continue

        insider_rows = [
            {
                "insider": None if name == "(sin nombre)" else name,
                "role": bucket["role"],
                "officer_title": bucket["officer_title"],
                "buy": _finish_side(bucket["buy"]),
                "sell": _finish_side(bucket["sell"]),
                "last_tx": bucket["last_tx"] or None,
            }
            for name, bucket in insiders.items()
        ]
        # Primero quien mas ha vendido; sin ventas, quien mas ha comprado.
        insider_rows.sort(key=lambda row: (-row["sell"]["value"], -row["buy"]["value"]))
        companies.append(
            {
                "ticker": ticker,
                "company": followed[ticker]["company"].name,
                "origin": followed[ticker]["origin"],
                "period": {"from": min(dated_ps) if dated_ps else None, "to": max(dated_ps) if dated_ps else None},
                "filings": len(accessions),
                "amended_filings": amended,
                "totals": {
                    "buy": _finish_side(totals["buy"]),
                    "sell": _finish_side(totals["sell"]),
                },
                "insiders": insider_rows,
                "excluded_codes": excluded_codes,
                "excluded_derivative": excluded_derivative,
                "rows_without_date": rows_without_date,
            }
        )

    return {
        "status": "ok",
        "days": days,
        "as_of": date.today().isoformat(),
        "scope": "cartera+watchlist",
        "note": (
            "Solo compras/ventas en mercado abierto (codigos Form 4 P/S, no "
            "derivadas) ya persistidas por el monitor; concesiones, ejercicios "
            "y derivados se declaran por empresa y no suman. Las enmiendas 4/A "
            "no se pueden enlazar con el filing original (amends_accession no "
            "se puebla en la ingesta): se declaran en amended_filings."
        ),
        "companies": companies,
        "companies_without_data": without_data,
    }
