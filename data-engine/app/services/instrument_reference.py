"""Referencia normalizada de instrumentos (seed FinanceDatabase + OpenFIGI).

El resolver la consulta primero: un ticker pedido se normaliza
(strip().upper()) y se busca en ``instrument_references``. Si hay fila con
FIGI, se expande a todos los tickers que comparten ese FIGI (o el
compositeFIGI): asi un renombre por corporate action (ticker viejo y nuevo
con el mismo FIGI) resuelve a la misma Company. Si no hay fila, el caller
sigue con el fallback de sufijos exacto igual que hoy.

Honestidad: un instrumento desconocido sigue siendo desconocido (None /
lista vacia) con motivo explicito; ningun campo se inventa. Los campos que
FinanceDatabase no trae se guardan como NULL, nunca como "Unknown".
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import InstrumentReference


def normalize_ticker(ticker: str) -> str:
    """Normaliza un ticker pedido: strip + upper. Cadena vacia si no hay nada."""
    return ticker.strip().upper()


def normalize_text(value: object) -> str | None:
    """'' / 'nan' / 'none' / 'unknown' -> None. Todo lo demas: strip o None si vacio.

    FinanceDatabase deja celdas vacias y placeholders de curacion ("nan",
    "Unknown"); guardarlos tal cual afirmaria un dato que la fuente no da.
    NULL = "la fuente no lo declara".
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "unknown", "n/a", "-"}:
        return None
    return text


def normalize_row(raw: dict, *, as_of: date, source: str = "financedatabase") -> dict | None:
    """Normaliza una fila cruda de FinanceDatabase a columnas del modelo.

    Devuelve None si no hay simbolo utilizable (fila inservible, se salta
    con motivo, nunca se inventa un ticker). Los FIGI/ISIN/CUSIP se
    normalizan a upper sin espacios; vacios -> None.
    """
    symbol = normalize_text(raw.get("symbol") or raw.get("ticker"))
    if not symbol:
        return None
    ticker = normalize_ticker(symbol)
    if not ticker or len(ticker) > 40:
        return None

    def _code(key: str, width: int) -> str | None:
        val = normalize_text(raw.get(key))
        if not val:
            return None
        cleaned = val.strip().upper().replace(" ", "")
        if not cleaned or len(cleaned) > width:
            return None
        return cleaned

    return {
        "ticker_normalized": ticker,
        "figi": _code("figi", 12),
        "composite_figi": _code("composite_figi", 12),
        "shareclass_figi": _code("shareclass_figi", 12),
        "isin": _code("isin", 12),
        "cusip": _code("cusip", 9),
        "sedol": _code("sedol", 7),
        "name": normalize_text(raw.get("name")),
        "exchange": normalize_text(raw.get("exchange")),
        "mic": normalize_text(raw.get("mic") or raw.get("mic_code")),
        "sector": normalize_text(raw.get("sector")),
        "industry": normalize_text(raw.get("industry")),
        "country": normalize_text(raw.get("country")),
        "currency": normalize_text(raw.get("currency")),
        "as_of": as_of,
        "source": source,
    }


def names_by_cusip(db: Session, cusips: list[str]) -> dict[str, str]:
    """Nombre legible del emisor por CUSIP exacto (referencia registrada).

    El nameOfIssuer del 13F viene truncado por la SEC («TAIWAN SEMICONDUCTOR
    MANUFAC»); la referencia de instrumentos trae el nombre completo. Solo se
    sustituye por CUSIP exacto, nunca por parecido de nombre; sin referencia,
    el llamador conserva el nombre tal cual del filing.
    """
    wanted = sorted({c.strip().upper() for c in cusips if c and c.strip()})
    if not wanted:
        return {}
    try:
        rows = db.scalars(
            select(InstrumentReference).where(InstrumentReference.cusip.in_(wanted))
        ).all()
    except Exception:
        # Tabla aun sin migrar (DB anterior a 0047): sin referencia, fallback intacto.
        return {}
    out: dict[str, str] = {}
    for row in rows:
        if row.cusip and row.name:
            out.setdefault(row.cusip.strip().upper(), row.name)
    return out


def get_by_ticker(db: Session, ticker: str) -> InstrumentReference | None:
    """Fila de referencia por ticker normalizado, o None si es desconocido."""
    normalized = normalize_ticker(ticker)
    if not normalized:
        return None
    try:
        return db.scalar(
            select(InstrumentReference).where(
                InstrumentReference.ticker_normalized == normalized
            )
        )
    except Exception:
        # Tabla aun sin migrar (DB anterior a 0047): el seam degrada a
        # "sin referencia" y el resolver sigue con el fallback intacto.
        return None


def get_by_figi(db: Session, figi: str) -> list[InstrumentReference]:
    """Todas las filas que comparten un FIGI (historial de renombres)."""
    normalized = figi.strip().upper()
    if not normalized:
        return []
    try:
        return list(
            db.scalars(
                select(InstrumentReference).where(InstrumentReference.figi == normalized)
            ).all()
        )
    except Exception:
        return []


def figi_sibling_tickers(db: Session, row: InstrumentReference):
    """Generador de tickers que comparten figi o composite_figi con ``row``.

    Nucleo compartido de la expansion por identidad FIGI (antes copiada en
    company_resolver). Es un generador a proposito: si la base falla a mitad,
    el caller conserva lo ya emitido (politica "parcial" de sibling_tickers)
    o descarta todo (politica "todo o nada" de company_resolver) sin duplicar
    las dos consultas.
    """
    if row.figi:
        for sib in db.scalars(
            select(InstrumentReference).where(InstrumentReference.figi == row.figi)
        ).all():
            yield sib.ticker_normalized
    if row.composite_figi:
        for sib in db.scalars(
            select(InstrumentReference).where(
                InstrumentReference.composite_figi == row.composite_figi
            )
        ).all():
            yield sib.ticker_normalized


def sibling_tickers(db: Session, ticker: str) -> list[str]:
    """Tickers candidatos para un pedido via identidad FIGI estable.

    - Sin fila de referencia -> [] (desconocido; el caller usa el fallback).
    - Fila sin FIGI -> [propio ticker] (solo normalizacion de caja/espacios).
    - Fila con FIGI -> todos los tickers que comparten figi o composite_figi
      (renombre por corporate action: viejo y nuevo apuntan al mismo FIGI).
    """
    row = get_by_ticker(db, ticker)
    if row is None:
        return []
    candidates: set[str] = {row.ticker_normalized}
    figis = {f for f in (row.figi, row.composite_figi) if f}
    if not figis:
        return sorted(candidates)
    try:
        candidates.update(figi_sibling_tickers(db, row))
    except Exception:
        return sorted(candidates)
    return sorted(candidates)


def upsert_rows(
    db: Session, rows: list[dict], *, commit: bool = True
) -> dict[str, int]:
    """Inserta/actualiza filas ya normalizadas. Idempotente por ticker.

    Devuelve {"inserted": N, "updated": M, "skipped": K}. Nunca inventa:
    las filas sin ticker_normalized se cuentan como skipped.
    """
    inserted = 0
    updated = 0
    skipped = 0
    for payload in rows:
        ticker = payload.get("ticker_normalized")
        if not ticker:
            skipped += 1
            continue
        existing = db.scalar(
            select(InstrumentReference).where(
                InstrumentReference.ticker_normalized == ticker
            )
        )
        if existing is None:
            db.add(InstrumentReference(**payload))
            inserted += 1
        else:
            changed = False
            for key, value in payload.items():
                if key == "ticker_normalized":
                    continue
                # Una ausencia en la fuente nunca borra un dato ya conocido:
                # que esta ingesta no traiga FIGI/ISIN/sector no significa que
                # el instrumento lo haya perdido.
                if value is None:
                    continue
                if getattr(existing, key) != value:
                    setattr(existing, key, value)
                    changed = True
            if changed:
                updated += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}
