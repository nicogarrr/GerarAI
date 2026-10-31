"""Feed insider agregado: operaciones Form 4 persistidas de todos los emisores.

Lee SOLO lo ya persistido (insider_filings / insider_transactions): sin red,
sin depender del ban de IP de la SEC. Reutiliza ``detect_signals`` para
clusters y compras de CEO/CFO, de modo que el criterio es el mismo que el de
la lectura por ticker.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import insider_service

SIDES = {"buy": "P", "sell": "S"}


def _side(code: str | None, acquired_disposed: str | None) -> str | None:
    if code == "P":
        return "compra"
    if code == "S":
        return "venta"
    return None


def ticker_list(raw: str | None) -> list[str]:
    """Simbolos de un emisor multiclase: "LEN, LEN.B", "LEN;LEN.B", " len ,len.b"."""
    if not raw:
        return []
    return [t.strip().upper() for t in str(raw).replace(";", ",").split(",") if t.strip()]


def primary_ticker(raw: str | None) -> str | None:
    """Simbolo representativo para listar al emisor una sola vez.

    Un Form 4 de un emisor con varias clases trae "LEN, LEN.B" (o "GTX,GTXAP").
    Sin normalizar, el mismo emisor aparece como dos empresas ("LEN" y
    "LEN, LEN.B") y sus compras no suman en cluster. Se usa el primer simbolo
    de la lista solo como representante (no se afirma que sea el principal);
    el dato original se conserva en `issuer_tickers_raw`.
    """
    symbols = ticker_list(raw)
    return symbols[0] if symbols else raw


def _tx_dict(row: InsiderTransaction, filing: InsiderFiling, line: int) -> dict[str, Any]:
    return {
        "ticker": primary_ticker(row.issuer_ticker or filing.issuer_ticker),
        "issuer_tickers_raw": row.issuer_ticker or filing.issuer_ticker,
        "issuer_name": filing.issuer_name,
        "insider": row.insider,
        "insider_cik": row.insider_cik,
        "role": row.role,
        "officer_title": row.officer_title,
        "multi_reporter": bool(row.multi_reporter),
        "type": row.code,
        "acquired_disposed": row.acquired_disposed,
        "shares": row.shares,
        "price": row.price,
        # Divisa declarada por transaccion. SEC Form 4: siempre USD (se
        # declara y liquida en USD). PDMR UK: la que traiga la fuente; si
        # falta (93/307 en el feed real), None -> UI: "divisa no informada".
        "currency": ((row.data_quality or {}).get("currency")
        if isinstance(row.data_quality, dict) else None)
        or ("USD" if row.form in ("4", "4/A") else None),
        "value": row.value,
        "date": row.tx_date or filing.filing_date,
        "is_derivative": bool(row.is_derivative),
        "rule_10b5_1": bool(row.rule_10b5_1),
        "accession_number": row.accession_number,
        "tx_line": line,
        "filing_date": filing.filing_date,
        "source_url": row.source_url or filing.source_url,
        "form": row.form or filing.form,
    }


def _tx_dict_from_row(row: Any, line: int) -> dict[str, Any]:
    """``_tx_dict`` sobre la fila de columnas del feed (misma salida exacta).

    Los labels del SELECT se leen por nombre; cualquier deriva de campos entre
    este builder y ``_tx_dict`` la cubren los tests de contrato del feed.
    """
    data_quality = row["data_quality"]
    tx_form = row["tx_form"]
    return {
        "ticker": primary_ticker(row["tx_issuer_ticker"] or row["filing_issuer_ticker"]),
        "issuer_tickers_raw": row["tx_issuer_ticker"] or row["filing_issuer_ticker"],
        "issuer_name": row["issuer_name"],
        "insider": row["insider"],
        "insider_cik": row["insider_cik"],
        "role": row["role"],
        "officer_title": row["officer_title"],
        "multi_reporter": bool(row["multi_reporter"]),
        "type": row["code"],
        "acquired_disposed": row["acquired_disposed"],
        "shares": row["shares"],
        "price": row["price"],
        # Divisa declarada por transaccion. SEC Form 4: siempre USD (se
        # declara y liquida en USD). PDMR UK: la que traiga la fuente; si
        # falta (93/307 en el feed real), None -> UI: "divisa no informada".
        "currency": ((data_quality or {}).get("currency")
        if isinstance(data_quality, dict) else None)
        or ("USD" if tx_form in ("4", "4/A") else None),
        "value": row["value"],
        "date": row["tx_date"] or row["filing_date"],
        "is_derivative": bool(row["is_derivative"]),
        "rule_10b5_1": bool(row["rule_10b5_1"]),
        "accession_number": row["accession_number"],
        "tx_line": line,
        "filing_date": row["filing_date"],
        "source_url": row["tx_source_url"] or row["filing_source_url"],
        "form": tx_form or row["filing_form"],
    }


def _group_tranches(items: list[dict]) -> list[dict]:
    """Agrupa los tramos de una misma operacion (mismo filing + insider + codigo).

    Un Form 4 suele desglosar una venta en decenas de tramos a distintos
    precios (mismo accession, una fila por tramo): mostrados sueltos la tabla
    es ruido puro (cientos de filas para decenas de operaciones). Se agregan:
    acciones sumadas, precio medio ponderado (importe / acciones), importe
    total. ``tranches`` cuenta los tramos que componen la fila.
    """
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for tx in items:
        key = (tx.get("accession_number"), tx.get("insider"), tx.get("type"), tx.get("form"), tx.get("currency"))
        group = groups.get(key)
        if group is None:
            group = dict(tx)
            group["tranches"] = 0
            group["_shares_sum"] = 0.0
            group["_value_sum"] = 0.0
            groups[key] = group
            order.append(key)
        group["tranches"] += 1
        # Planificado solo si TODOS los tramos de la operacion lo son.
        group["rule_10b5_1"] = bool(group.get("rule_10b5_1")) and bool(tx.get("rule_10b5_1"))
        if tx.get("shares") is not None:
            group["_shares_sum"] += float(tx["shares"])
        if tx.get("value") is not None:
            group["_value_sum"] += float(tx["value"])
    grouped: list[dict] = []
    for key in order:
        group = groups[key]
        shares = group.pop("_shares_sum")
        value = group.pop("_value_sum")
        if shares:
            group["shares"] = shares
            if value:
                group["price"] = value / shares
        if value:
            group["value"] = value
        grouped.append(group)
    grouped.sort(key=lambda t: (str(t.get("date") or ""), str(t.get("accession_number") or "")), reverse=True)
    return grouped


def build_feed(
    db: Session,
    *,
    days: int = 90,
    side: str = "all",
    ticker: str | None = None,
    limit: int = 100,
    today: date | None = None,
) -> dict[str, Any]:
    """Operaciones P/S no derivadas de los ultimos ``days`` dias + senales."""
    today = today or date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    wanted = ticker.strip().upper() if ticker else None

    # Columnas, no entidades ORM: la respuesta muestra ``limit`` filas pero la
    # ventana entera se usa para totales y senales; instanciar un ORM por fila
    # era el 64% del coste (benchmark sintetico 45k filas, 2026-10-31: 1.013 ms
    # ORM vs 346 ms solo columnas). Mismos valores, mismo WHERE.
    tx_t = InsiderTransaction
    stmt = (
        select(
            tx_t.issuer_ticker.label("tx_issuer_ticker"),
            InsiderFiling.issuer_ticker.label("filing_issuer_ticker"),
            InsiderFiling.issuer_name.label("issuer_name"),
            tx_t.insider.label("insider"),
            tx_t.insider_cik.label("insider_cik"),
            tx_t.role.label("role"),
            tx_t.officer_title.label("officer_title"),
            tx_t.multi_reporter.label("multi_reporter"),
            tx_t.code.label("code"),
            tx_t.acquired_disposed.label("acquired_disposed"),
            tx_t.shares.label("shares"),
            tx_t.price.label("price"),
            tx_t.data_quality.label("data_quality"),
            tx_t.value.label("value"),
            tx_t.tx_date.label("tx_date"),
            InsiderFiling.filing_date.label("filing_date"),
            tx_t.is_derivative.label("is_derivative"),
            tx_t.rule_10b5_1.label("rule_10b5_1"),
            tx_t.accession_number.label("accession_number"),
            tx_t.source_url.label("tx_source_url"),
            InsiderFiling.source_url.label("filing_source_url"),
            tx_t.form.label("tx_form"),
            InsiderFiling.form.label("filing_form"),
        )
        .join(InsiderFiling, tx_t.filing_id == InsiderFiling.id)
        .where(
            tx_t.is_derivative.is_(False),
            tx_t.code.in_(("P", "S")),
            func.coalesce(tx_t.tx_date, InsiderFiling.filing_date) >= cutoff,
            *tenant_filters(db, InsiderTransaction, InsiderFiling),
        )
    )
    rows = db.execute(stmt).mappings().all()
    if wanted:
        # Mismo criterio que la lista mostrada: separadores, espacios y mayusculas.
        rows = [
            row
            for row in rows
            if wanted in ticker_list(row["tx_issuer_ticker"] or row["filing_issuer_ticker"])
        ]

    txs = [_tx_dict_from_row(row, i) for i, row in enumerate(rows)]
    txs.sort(key=lambda t: (str(t["date"] or ""), str(t["accession_number"])), reverse=True)

    # Totales y senales: solo Form 4/4A (SEC, importe declarado en USD).
    # Canada (currency=None) y PDMR (GBP/EUR/USD/sin divisa) se listan con su
    # divisa declarada pero jamas se suman a cabeceras en USD ni alimentan
    # senales pensadas para Form 4 (umbrales en USD, 10b5-1, clusters SEC).
    form4 = [t for t in txs if t["form"] in ("4", "4/A") and t["currency"] == "USD"]
    signals = insider_service.detect_signals(form4)
    clusters = [s for s in signals if s["signal"] == "cluster_buy"]
    c_suite = [s for s in signals if s["signal"] == "c_suite_buy"]
    big_buys = [s for s in signals if s["signal"] == "big_buy"]
    c_suite.sort(key=lambda s: str(s.get("date") or ""), reverse=True)
    clusters.sort(key=lambda s: str(s.get("window_start") or ""), reverse=True)
    big_buys.sort(key=lambda s: float(s.get("value") or 0), reverse=True)

    code = SIDES.get(side)
    shown = _group_tranches([t for t in txs if code is None or t["type"] == code])

    buys = [t for t in form4 if t["type"] == "P"]
    sells = [t for t in form4 if t["type"] == "S"]

    def _sum(items: list[dict]) -> float:
        return sum(float(t["value"]) for t in items if t.get("value") is not None)

    total_filings = (
        db.scalar(
            select(func.count())
            .select_from(InsiderFiling)
            .where(*tenant_filters(db, InsiderFiling))
        )
        or 0
    )
    with_data = (
        db.scalar(
            select(func.count(func.distinct(InsiderTransaction.filing_id))).where(
                *tenant_filters(db, InsiderTransaction)
            )
        )
        or 0
    )
    return {
        "status": "ok",
        "days": days,
        "side": side,
        "ticker": wanted,
        "totals": {
            "buy_count": len(buys),
            "buy_value": _sum(buys),
            "sell_count": len(sells),
            "sell_value": _sum(sells),
            "filings_total": total_filings,
            "filings_with_transactions": with_data,
            "filings_pending": max(0, total_filings - with_data),
        },
        "clusters": clusters[:10],
        "c_suite_buys": c_suite[:20],
        "big_buys": big_buys[:10],
        "count": len(shown),
        "transactions": [
            {
                "ticker": t["ticker"],
                "issuer_tickers_raw": t["issuer_tickers_raw"],
                "issuer_name": t["issuer_name"],
                "insider": t["insider"],
                "role": t["role"],
                "officer_title": t["officer_title"],
                "side": _side(t["type"], t["acquired_disposed"]),
                "code": t["type"],
                "shares": t["shares"],
                "price": t["price"],
                "value": t["value"],
                "date": t["date"],
                "multi_reporter": t["multi_reporter"],
                "tranches": t["tranches"],
                "rule_10b5_1": t["rule_10b5_1"],
                "accession_number": t["accession_number"],
                "source_url": t["source_url"],
                "form": t["form"],
                "currency": t["currency"],
            }
            for t in shown[:limit]
        ],
    }
