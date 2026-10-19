"""Form 4 via edgartools con el MISMO shape que ``connectors/form4.py``.

Dos caminos, una sola forma de salida (los dicts de transaccion de
``parse_form4_xml``, enriquecibles como hace ``insider_service``):

- Snapshot/offline (produccion OCI): el snapshot guarda el XML crudo del
  filing y se parsea con el tolerant-parser del repo (stdlib, sin red).
  No se usa ``Ownership.from_xml`` aqui: verificado en edgartools 5.59.1 que
  resuelve los reporting owners contra la SEC (red) durante el parse, asi que
  no es usable sin red ni con la IP baneada.
- Live (dev): objeto edgartools con ``to_dataframe()`` (``Ownership``) o un
  DataFrame ya materializado. Columnas verificadas en 5.59.1
  (``ownership/summary.py`` modo detailed): 'Transaction Type', 'Code',
  'Description', 'Shares', 'Price', 'Value', 'Date', 'Form', 'Issuer',
  'Ticker', 'Insider', 'Position', 'Remaining Shares'. El DataFrame pierde
  ``acquired_disposed`` (A/D) e ``insider_cik``: se derivan (Purchase->A,
  Sale->D) o se vacian, documentado abajo; el XML es autoritativo.

``is_open_market_buy`` se reutiliza por import (misma semantica P+A que el
resto del repo): una compra es compra venga de la via que venga.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.services.connectors import form4 as form4_connector

# Claves EXACTAS de cada transaccion de form4.parse_form4_xml (mismo orden).
FORM4_TX_KEYS: tuple[str, ...] = (
    "ticker",
    "issuer_name",
    "issuer_cik",
    "period_of_report",
    "insider",
    "insider_cik",
    "multi_reporter",
    "reporters_count",
    "attribution",
    "role",
    "officer_title",
    "is_officer",
    "type",
    "acquired_disposed",
    "shares",
    "price",
    "value",
    "date",
    "is_derivative",
    "rule_10b5_1",
)

FORM4_TOP_KEYS: tuple[str, ...] = (
    "ticker",
    "issuer_name",
    "issuer_cik",
    "period_of_report",
    "reporters",
    "transactions",
)

_DERIVATIVE_TYPE_RE = re.compile(r"^derivative", re.IGNORECASE)
_OFFICER_HINT_RE = re.compile(
    r"\bofficer\b|\bchief\b|\bceo\b|\bcfo\b|\bpresident\b|\btreasurer\b|\bsecretary\b",
    re.IGNORECASE,
)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value if value == value else None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def transactions_from_edgartools_dataframe(
    df: Any,
    *,
    ticker: str | None = None,
    issuer_name: str = "",
    issuer_cik: str = "",
    period_of_report: str | None = None,
    reporters: list[dict] | None = None,
) -> dict:
    """Normaliza el DataFrame detailed de ``Ownership`` al shape del conector.

    Columnas que se leen (resto se ignora): 'Transaction Type' (p.ej.
    'Purchase'/'Sale'/'Derivative Purchase'), 'Code' (codigo SEC crudo P/S),
    'Shares', 'Price', 'Value', 'Date', 'Ticker', 'Issuer', 'Insider',
    'Position', 'Form'. Perdidas documentadas frente al XML: sin A/D (se
    deriva de Purchase/Sale, resto None), sin insider_cik (""), sin rol
    director/officer/10% (Position como rol literal), sin notas al pie
    (rule_10b5_1 queda None, nunca False inventado).
    """
    rows: list[dict] = []
    try:
        records = df.to_dict(orient="records")
    except Exception:
        records = []
    known_reporters = list(reporters) if reporters else []
    multi = len(known_reporters) > 1
    for record in records:
        tx_type = str(record.get("Transaction Type") or "").strip()
        code = str(record.get("Code") or "").strip().upper() or None
        tx_lower = tx_type.lower()
        is_derivative = bool(_DERIVATIVE_TYPE_RE.match(tx_lower))
        if tx_lower == "purchase":
            acquired = "A"
        elif tx_lower == "sale":
            acquired = "D"
        else:
            acquired = None
        shares = _to_float(record.get("Shares"))
        price = _to_float(record.get("Price"))
        value = _to_float(record.get("Value"))
        if value is None and shares is not None and price is not None:
            value = shares * price
        raw_date = record.get("Date")
        position = str(record.get("Position") or "").strip() or None
        insider = str(record.get("Insider") or "").strip()
        form = str(record.get("Form") or "").strip()
        if form.lower().startswith("form "):
            form = form[5:].strip()
        rows.append(
            {
                "ticker": ticker or (str(record.get("Ticker") or "").strip() or None),
                "issuer_name": issuer_name or str(record.get("Issuer") or ""),
                "issuer_cik": issuer_cik,
                "period_of_report": period_of_report,
                "insider": insider,
                "insider_cik": "",
                "multi_reporter": multi,
                "reporters_count": len(known_reporters) or 1,
                "attribution": "joint_filing" if multi else "single_reporter",
                "role": position or "insider",
                "officer_title": position,
                "is_officer": bool(position and _OFFICER_HINT_RE.search(position)),
                "type": code,
                "acquired_disposed": acquired,
                "shares": shares,
                "price": price,
                "value": value,
                "date": _iso_date(raw_date),
                "is_derivative": is_derivative,
                # El DataFrame de edgartools no trae notas al pie: desconocido.
                "rule_10b5_1": None,
            }
        )
    return {
        "ticker": ticker,
        "issuer_name": issuer_name,
        "issuer_cik": issuer_cik,
        "period_of_report": period_of_report,
        "reporters": known_reporters,
        "transactions": rows,
    }


def ownership_transactions(source: Any, **kwargs: Any) -> dict:
    """Parsea Form 4 al shape del conector desde XML o objeto edgartools.

    - ``str``/``bytes``: XML crudo (snapshot/offline) via el tolerant-parser
      del repo: MISMO shape por construccion.
    - objeto con ``to_dataframe()`` (``Ownership`` live) o DataFrame:
      normalizacion documentada arriba.
    """
    if isinstance(source, (str, bytes)):
        return form4_connector.parse_form4_xml(source)
    to_df = getattr(source, "to_dataframe", None)
    if callable(to_df):
        try:
            df = to_df()
        except TypeError:
            df = to_df(True)
        return transactions_from_edgartools_dataframe(df, **kwargs)
    if hasattr(source, "to_dict"):
        return transactions_from_edgartools_dataframe(source, **kwargs)
    raise TypeError(f"unsupported Form 4 source: {type(source).__name__}")


def enrich_like_insider_service(transactions: list[dict], filing: dict) -> list[dict]:
    """Anade accession/tx_line/filing_date/source_url/form como insider_service.

    Replica ``get_signals_for_ticker`` (mismo orden y mismos fallbacks): la
    fecha cae a filing_date cuando la fila no trae, y tx_line es el ordinal
    dentro del filing. Mutacion in-place + retorno por conveniencia.
    """
    wanted = str(filing.get("ticker") or "").strip().upper() or None
    for line_index, tx in enumerate(transactions):
        tx.setdefault("ticker", wanted)
        tx["accession_number"] = filing.get("accession_number")
        tx["tx_line"] = line_index
        tx["filing_date"] = filing.get("filing_date")
        tx["source_url"] = filing.get("document_url")
        tx["form"] = filing.get("form")
        if not tx.get("date"):
            tx["date"] = filing.get("filing_date")
    return transactions


def is_open_market_buy(tx: dict) -> bool:
    """Delega en el conector: P+A (mercado abierto o privada, ver form4)."""
    return form4_connector.is_open_market_buy(tx)
