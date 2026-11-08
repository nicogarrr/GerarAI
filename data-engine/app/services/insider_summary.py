"""Resumen determinista de insiders de un ticker (Form 4/4-A/5/5-A de la SEC).

Lee SOLO lo persistido (``insider_filings`` / ``insider_transactions``, que
alimentan el monitor de la watchlist y la ficha); no llama a la red ni al
modelo. Mismo dato -> mismo resultado: todas las cifras salen de aqui.

Que calcula, y con que reglas (visibles en ``rules`` del resultado):

- Cada operacion con su naturaleza: compra/venta en mercado (codigo P/S,
  no derivada), ejercicio o conversion de opciones (M, X, C), concesion (A),
  retencion fiscal (F), regalo (G) u otra. El codigo P de la SEC cubre compras
  en mercado abierto Y privadas; el XML no siempre las distingue.
- Retraso de presentacion: un Form 4 vence 2 dias habiles despues de la
  operacion (Exchange Act §16(a), regla de 2002). Dias habiles = lunes a
  viernes sin festivos federales de EE. UU. Un Form 5 es por definicion la
  declaracion anual de lo no declarado antes: no se le mide el retraso.
- Compra neta en mercado a 3, 6 y 12 meses: SOLO P y S no derivadas. Los
  ejercicios, concesiones, retenciones y regalos NO cuentan (no son una
  decision de comprar o vender con su dinero), y se dan aparte.
- Compras en grupo: 3 o mas insiders distintos con compras P en una ventana
  de 30 dias.
- Compra como % de lo que el insider ya tenia: acciones compradas / (acciones
  tras la operacion - acciones compradas). Sin el dato de acciones tras la
  operacion (filas guardadas por un parser anterior) no se calcula.
- Primera compra en N anos: anos desde la compra P anterior del mismo insider
  en los datos; sin compra anterior, se dice desde cuando hay datos.
- Las enmiendas (4/A, 5/A) que repiten una fila identica de otro filing no
  se cuentan dos veces.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import InsiderFiling, InsiderTransaction

SOURCE = "SEC EDGAR · Form 4/5"
WINDOWS_DAYS = (90, 180, 365)
CLUSTER_MIN_INSIDERS = 3
CLUSTER_WINDOW_DAYS = 30
FORM4_DUE_BUSINESS_DAYS = 2
FIRST_BUY_MIN_YEARS = 2.0
MAX_ROWS = 200

NATURE_BY_CODE = {
    "P": "compra_mercado",
    "S": "venta_mercado",
    "M": "ejercicio",
    "X": "ejercicio",
    "C": "ejercicio",
    "A": "concesion",
    "F": "retencion_fiscal",
    "G": "regalo",
}
OPEN_MARKET = ("compra_mercado", "venta_mercado")


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=64)
def us_federal_holidays(year: int) -> frozenset[date]:
    """Festivos federales de EE. UU. (dia observado), los que cierra EDGAR."""
    days = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr.
        _nth_weekday(year, 2, 0, 3),  # Washington
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus
        _observed(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2021:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    # Ano nuevo del ano siguiente observado el 31-dic de este.
    days.add(_observed(date(year + 1, 1, 1)))
    return frozenset(d for d in days if d.year == year)


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in us_federal_holidays(day.year)


def business_days_between(start: date, end: date) -> int:
    """Dias habiles despues de ``start`` hasta ``end`` incluido (0 si end <= start)."""
    if end <= start:
        return 0
    count = 0
    day = start
    while day < end:
        day += timedelta(days=1)
        if is_business_day(day):
            count += 1
    return count


def nature_of(code: str | None, acquired_disposed: str | None, is_derivative: bool) -> str:
    code = (code or "").strip().upper()
    nature = NATURE_BY_CODE.get(code, "otra")
    if nature in OPEN_MARKET:
        expected = "A" if nature == "compra_mercado" else "D"
        if is_derivative or (acquired_disposed and acquired_disposed.upper() != expected):
            return "otra"
    return nature


def _insider_key(tx: InsiderTransaction) -> str:
    return (tx.insider_cik or tx.insider or "?").strip().upper()


def _value(tx: InsiderTransaction) -> float | None:
    if tx.value is not None:
        return float(tx.value)
    if tx.shares is not None and tx.price is not None:
        return float(tx.shares) * float(tx.price)
    return None


def _row(tx: InsiderTransaction, filing: InsiderFiling) -> dict[str, Any]:
    tx_day = _parse_date(tx.tx_date)
    filed = _parse_date(filing.filing_date)
    form = str(tx.form or filing.form or "").upper()
    days_late: int | None = None
    late: bool | None = None
    if form.startswith("4") and tx_day and filed:
        bd = business_days_between(tx_day, filed)
        days_late = max(0, bd - FORM4_DUE_BUSINESS_DAYS)
        late = bd > FORM4_DUE_BUSINESS_DAYS
    quality = tx.data_quality or {}
    holdings_after = quality.get("holdings_after")
    nature = nature_of(tx.code, tx.acquired_disposed, bool(tx.is_derivative))
    pct_of_holdings = None
    if nature == "compra_mercado" and holdings_after is not None and tx.shares:
        before = float(holdings_after) - float(tx.shares)
        if before > 0:
            pct_of_holdings = round(float(tx.shares) / before * 100, 2)
    return {
        "insider": tx.insider,
        "insider_cik": tx.insider_cik or None,
        "role": tx.role,
        "officer_title": tx.officer_title,
        "form": form,
        "code": tx.code,
        "nature": nature,
        "acquired_disposed": tx.acquired_disposed,
        "is_derivative": bool(tx.is_derivative),
        "rule_10b5_1": bool(tx.rule_10b5_1),
        "shares": tx.shares,
        "price": tx.price,
        "value": _value(tx),
        "holdings_after": holdings_after,
        "ownership": quality.get("ownership"),
        "pct_of_holdings": pct_of_holdings,
        "tx_date": tx_day.isoformat() if tx_day else None,
        "filing_date": filed.isoformat() if filed else None,
        "business_days_to_file": business_days_between(tx_day, filed) if tx_day and filed else None,
        "days_late": days_late,
        "late": late,
        "accession_number": tx.accession_number,
        "source_url": tx.source_url or filing.source_url or filing.index_url,
        "index_url": filing.index_url,
        "_key": _insider_key(tx),
    }


def _dedupe_amendments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita filas de un filing que repiten EXACTAMENTE una fila de otro filing."""
    seen: dict[tuple, str] = {}
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: (r["filing_date"] or "", r["accession_number"] or "")):
        ident = (row["_key"], row["tx_date"], row["code"], row["shares"], row["price"], row["is_derivative"])
        first_acc = seen.get(ident)
        if first_acc is not None and first_acc != row["accession_number"] and str(row["form"]).endswith("/A"):
            continue
        seen.setdefault(ident, row["accession_number"])
        out.append(row)
    return out


def _side(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trades": len(rows),
        "insiders": len({r["_key"] for r in rows}),
        "shares": sum(float(r["shares"]) for r in rows if r["shares"] is not None),
        "shares_missing": sum(1 for r in rows if r["shares"] is None),
        "value": sum(float(r["value"]) for r in rows if r["value"] is not None),
        "value_missing": sum(1 for r in rows if r["value"] is None),
        "planned_10b5_1": sum(1 for r in rows if r["rule_10b5_1"]),
    }


def _clusters(buys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated = sorted((r for r in buys if r["tx_date"]), key=lambda r: r["tx_date"])
    clusters: list[dict[str, Any]] = []
    for i, start in enumerate(dated):
        start_day = date.fromisoformat(start["tx_date"])
        end_limit = start_day + timedelta(days=CLUSTER_WINDOW_DAYS - 1)
        members = [r for r in dated[i:] if date.fromisoformat(r["tx_date"]) <= end_limit]
        insiders = {r["_key"] for r in members}
        if len(insiders) < CLUSTER_MIN_INSIDERS:
            continue
        end_day = max(date.fromisoformat(r["tx_date"]) for r in members)
        if clusters and start_day <= date.fromisoformat(clusters[-1]["end"]):
            last = clusters[-1]
            merged = {id(r): r for r in last["_rows"] + members}
            last["_rows"] = list(merged.values())
            last["end"] = max(last["end"], end_day.isoformat())
            continue
        clusters.append({"start": start_day.isoformat(), "end": end_day.isoformat(), "_rows": members})
    out = []
    for c in clusters:
        rows = c.pop("_rows")
        names = sorted({str(r["insider"] or r["_key"]) for r in rows})
        out.append({
            **c,
            "insiders": len({r["_key"] for r in rows}),
            "names": names,
            "trades": len(rows),
            "value": sum(float(r["value"]) for r in rows if r["value"] is not None),
            "value_missing": sum(1 for r in rows if r["value"] is None),
        })
    return out


def insider_summary(
    db: Session,
    ticker: str,
    *,
    as_of: date | None = None,
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    normalized = ticker.strip().upper()
    today = as_of or date.today()
    pairs = db.execute(
        select(InsiderTransaction, InsiderFiling)
        .join(InsiderFiling, InsiderFiling.id == InsiderTransaction.filing_id)
        .where(
            InsiderTransaction.issuer_ticker == normalized,
            *tenant_filters(db, InsiderTransaction, InsiderFiling),
        )
    ).all()
    rows = [_row(tx, filing) for tx, filing in pairs]
    rows = [r for r in rows if (_parse_date(r["tx_date"]) or _parse_date(r["filing_date"]) or today) <= today]
    rows = _dedupe_amendments(rows)
    base = {
        "ticker": normalized,
        "as_of": today.isoformat(),
        "source": SOURCE,
        "rules": {
            "form4_due_business_days": FORM4_DUE_BUSINESS_DAYS,
            "cluster_min_insiders": CLUSTER_MIN_INSIDERS,
            "cluster_window_days": CLUSTER_WINDOW_DAYS,
            "open_market_codes": ["P", "S"],
            "excluded_from_net": ["M", "X", "C", "A", "F", "G"],
            "first_buy_min_years": FIRST_BUY_MIN_YEARS,
        },
    }
    if not rows:
        return {**base, "status": "sin_datos", "coverage": None, "windows": [], "clusters": [],
                "first_buys": [], "by_nature": {}, "late": {"filings": 0, "late": 0}, "transactions": []}

    filing_days = sorted(d for d in {r["filing_date"] for r in rows} if d)
    coverage = {
        "first_filing": filing_days[0] if filing_days else None,
        "last_filing": filing_days[-1] if filing_days else None,
        "filings": len({r["accession_number"] for r in rows}),
        "transactions": len(rows),
        "with_holdings_after": sum(1 for r in rows if r["holdings_after"] is not None),
    }

    def eff(r: dict[str, Any]) -> date:
        return _parse_date(r["tx_date"]) or _parse_date(r["filing_date"]) or today

    windows = []
    for days in WINDOWS_DAYS:
        cutoff = today - timedelta(days=days)
        inside = [r for r in rows if eff(r) > cutoff]
        buys = [r for r in inside if r["nature"] == "compra_mercado"]
        sells = [r for r in inside if r["nature"] == "venta_mercado"]
        excluded: dict[str, int] = {}
        for r in inside:
            if r["nature"] not in OPEN_MARKET:
                excluded[r["nature"]] = excluded.get(r["nature"], 0) + 1
        b, s = _side(buys), _side(sells)
        windows.append({
            "days": days,
            "buys": b,
            "sells": s,
            "net_value": b["value"] - s["value"],
            "excluded": excluded,
            "covered": bool(coverage["first_filing"]) and date.fromisoformat(coverage["first_filing"]) <= cutoff,
        })

    all_buys = [r for r in rows if r["nature"] == "compra_mercado"]
    clusters = _clusters(all_buys)

    first_buys = []
    by_insider: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(all_buys, key=lambda r: r["tx_date"] or ""):
        by_insider.setdefault(r["_key"], []).append(r)
    cover_start = _parse_date(coverage["first_filing"])
    for key, buys in by_insider.items():
        prev_day: date | None = None
        for r in buys:
            day = _parse_date(r["tx_date"])
            if day is None:
                continue
            if prev_day is None:
                years = round((day - cover_start).days / 365.25, 1) if cover_start else None
                entry = {"kind": "sin_compra_previa_en_datos", "years": years}
            elif prev_day != day:
                entry = {"kind": "desde_compra_previa", "years": round((day - prev_day).days / 365.25, 1)}
            else:
                entry = None
            if entry and entry["years"] is not None and entry["years"] >= FIRST_BUY_MIN_YEARS:
                first_buys.append({
                    **entry,
                    "insider": r["insider"],
                    "role": r["role"],
                    "tx_date": r["tx_date"],
                    "value": r["value"],
                    "source_url": r["source_url"],
                    "previous_buy": prev_day.isoformat() if prev_day else None,
                })
            prev_day = day

    by_nature: dict[str, dict[str, Any]] = {}
    for r in rows:
        slot = by_nature.setdefault(r["nature"], {"trades": 0, "value": 0.0, "value_missing": 0})
        slot["trades"] += 1
        if r["value"] is None:
            slot["value_missing"] += 1
        else:
            slot["value"] += float(r["value"])

    form4_filings: dict[str, bool] = {}
    for r in rows:
        if r["late"] is None:
            continue
        acc = r["accession_number"]
        form4_filings[acc] = form4_filings.get(acc, False) or bool(r["late"])

    ordered = sorted(rows, key=lambda r: (r["tx_date"] or "", r["filing_date"] or ""), reverse=True)
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in ordered[:max_rows]]
    return {
        **base,
        "status": "ok",
        "coverage": coverage,
        "windows": windows,
        "clusters": [c for c in clusters if _parse_date(c["end"]) and _parse_date(c["end"]) > today - timedelta(days=365 * 3)],
        "first_buys": sorted(first_buys, key=lambda f: f["tx_date"] or "", reverse=True),
        "by_nature": by_nature,
        "late": {
            "filings": len(form4_filings),
            "late": sum(1 for v in form4_filings.values() if v),
        },
        "transactions": public,
        "transactions_total": len(rows),
    }
