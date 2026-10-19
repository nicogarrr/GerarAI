"""Operaciones insider (compras P y ventas S) agregadas por empresa.

Vista de Nico (2026-10-19): tabla por empresa de su cartera IBKR y watchlist
— insider, cargo, importe vendido/comprado, acciones, precio medio y numero
de operaciones, con total y periodo. Lee SOLO lo persistido por el monitor
(insider_filings / insider_transactions): sin red, sin inventar. Solo cuentan
las operaciones en mercado abierto (codigos P y S); concesiones, ejercicios
de opciones y demas codigos no son compra/venta y se excluyen del agregado
(se declaran en ``excluded_codes``). Un importe ausente nunca se imputa: la
suma usa solo filas con valor y ``txs_without_value`` lo declara.
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
    return {"trades": 0, "shares": 0.0, "value": 0.0}


def _finish_side(side: dict[str, Any]) -> dict[str, Any]:
    avg = side["value"] / side["shares"] if side["shares"] else None
    return {
        "trades": side["trades"],
        "shares": round(side["shares"], 4),
        "value": round(side["value"], 2),
        "avg_price": round(avg, 4) if avg is not None else None,
    }


def insider_operations(db: Session, days: int = 365) -> dict[str, Any]:
    """Agregado por empresa (cartera + watchlist) e insider, ultimos `days` dias."""
    followed = followed_companies(db)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = db.execute(
        select(InsiderTransaction, InsiderFiling)
        .join(InsiderFiling, InsiderTransaction.filing_id == InsiderFiling.id)
        .where(InsiderTransaction.tx_date >= cutoff)
        .order_by(InsiderTransaction.tx_date)
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
        if not entries:
            # Sin Form 4 persistidos en el periodo: se declara, no se inventa.
            without_data.append(ticker)
            continue
        insiders: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
        totals = {"buy": _empty_side(), "sell": _empty_side()}
        excluded = 0
        without_value = 0
        dates: list[str] = []
        for tx, _filing in entries:
            side_key = SIDE_BY_CODE.get((tx.code or "").strip().upper())
            tx_date = tx.tx_date or ""
            if tx_date:
                dates.append(tx_date)
            if side_key is None:
                excluded += 1
                continue
            if tx.value is None:
                without_value += 1
            key = ((tx.insider or "").strip(), tx.role, tx.officer_title)
            bucket = insiders.setdefault(
                key,
                {"buy": _empty_side(), "sell": _empty_side(), "last_tx": ""},
            )
            for target in (bucket[side_key], totals[side_key]):
                target["trades"] += 1
                target["shares"] += tx.shares or 0.0
                target["value"] += tx.value or 0.0
            if tx_date > bucket["last_tx"]:
                bucket["last_tx"] = tx_date
        insider_rows = [
            {
                "insider": name or None,
                "role": role,
                "officer_title": officer_title,
                "buy": _finish_side(bucket["buy"]),
                "sell": _finish_side(bucket["sell"]),
                "last_tx": bucket["last_tx"] or None,
            }
            for (name, role, officer_title), bucket in insiders.items()
        ]
        # Primero quien mas ha vendido; sin ventas, quien mas ha comprado.
        insider_rows.sort(key=lambda row: (-row["sell"]["value"], -row["buy"]["value"]))
        companies.append(
            {
                "ticker": ticker,
                "company": followed[ticker]["company"].name,
                "origin": followed[ticker]["origin"],
                "period": {"from": min(dates) if dates else None, "to": max(dates) if dates else None},
                "filings": len({filing.accession_number for _tx, filing in entries}),
                "totals": {
                    "buy": _finish_side(totals["buy"]),
                    "sell": _finish_side(totals["sell"]),
                },
                "insiders": insider_rows,
                "excluded_codes": excluded,
                "txs_without_value": without_value,
            }
        )

    return {
        "status": "ok",
        "days": days,
        "as_of": date.today().isoformat(),
        "scope": "cartera+watchlist",
        "note": (
            "Solo compras/ventas en mercado abierto (codigos Form 4 P/S) ya "
            "persistidas por el monitor; concesiones y ejercicios quedan "
            "fuera del agregado (excluded_codes por empresa)."
        ),
        "companies": companies,
        "companies_without_data": without_data,
    }
