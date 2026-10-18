"""Cartera de inversores publicos: posiciones, pesos y ultimos movimientos.

Fuentes gratuitas de la SEC (13F, 13D/A, Forms 3 y 4). Cada dato sale como
``{"value", "label", "as_of", "source_url"}`` con etiqueta:

- OFICIAL:   tal como lo declara el filing (o suma/resta de cifras declaradas).
- INFERIDO:  estimacion propia; solo si una fila lo marca asi, nunca por defecto.
- SIN_DATOS: no hay fuente. ``value`` es None y nunca se rellena.

13F: se reutiliza lo ya ingerido (``investors.py``). Quien no presenta 13F
(p. ej. Trump) usa ``investor_positions`` / ``investor_movements`` (sincronizadas
desde EDGAR con ``sync_form4``) mas ``CURATED`` (lectura manual de filings
concretos con accession). El peso solo se calcula si hay valor y total con
fuente; sin eso es SIN_DATOS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InvestorMovement, InvestorPosition
from app.services.investors import (
    NO_13F_NOTE,
    _latest_view,
    _manager,
    _total,
    _value_usd,
    get_investor,
)
from app.services.manager_holding_ingestion_service import (
    LIMITATIONS,
    ManagerHoldingIngestionService,
)

OFICIAL = "OFICIAL"
INFERIDO = "INFERIDO"
SIN_DATOS = "SIN_DATOS"
LABELS = (OFICIAL, INFERIDO, SIN_DATOS)

MOVEMENTS_LIMIT = 50
# Inversores no-13F cuyo declarante en EDGAR (Forms 3/4) esta verificado.
# bezos: "BEZOS JEFFREY P" en la busqueda de propietarios de la SEC (own-disp, CIK 0001043298).
FORM4_FILER_CIK = {"trump": "0000947033", "bezos": "0001043298"}

_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_TRUMP_13D_URL = f"{_ARCHIVES}/947033/000114036125046424/xslSCHEDULE_13D_X01/primary_doc.xml"

ACTIONS = {
    "P": "compra",
    "S": "venta",
    "G": "donacion",
    "J": "otro",
    "A": "concesion",
    "M": "ejercicio",
    "F": "retencion",
}
CODE_NOTES = {
    "G": "Codigo G (donacion/transferencia): no es compra ni venta en mercado.",
    "J": "Codigo J (otra adquisicion o disposicion; ver notas del Form 4): no es mercado abierto.",
}


def datum(value: Any, label: str, as_of: date | str | None, source_url: str | None = None) -> dict[str, Any]:
    """Dato etiquetado. Sin valor => SIN_DATOS, sea cual sea la etiqueta pedida."""
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}")
    empty = {"value": None, "label": SIN_DATOS, "as_of": None, "source_url": None}
    if value is None:
        return empty
    if isinstance(value, Decimal):
        value = float(value)
    if label == SIN_DATOS:
        raise ValueError("SIN_DATOS cannot carry a value")
    as_of_text = as_of.isoformat() if isinstance(as_of, date) else (as_of or None)
    # Fail closed: sin cifra finita o sin fecha no hay dato; OFICIAL ademas exige fuente.
    if isinstance(value, float) and not math.isfinite(value):
        return empty
    if not as_of_text:
        return empty
    if label == OFICIAL and not source_url:
        return empty
    return {
        "value": value,
        "label": label,
        "as_of": as_of_text,
        "source_url": source_url or None,
    }


@dataclass(frozen=True)
class CuratedPosition:
    slug: str
    issuer_name: str
    issuer_cik: str
    ticker: str
    security_title: str
    shares: float
    ownership_pct: float
    as_of: date
    source_form: str
    accession_number: str
    source_url: str
    note: str


@dataclass(frozen=True)
class CuratedMovement:
    slug: str
    accession_number: str
    line_no: int
    issuer_name: str
    ticker: str
    movement_date: date
    filing_date: date
    action: str
    transaction_code: str
    shares: float | None
    shares_after: float | None
    source_form: str
    source_url: str
    note: str


# Leido a mano en EDGAR (data.sec.gov submissions de CIK 0000947033 y XML de cada filing).
CURATED_POSITIONS: tuple[CuratedPosition, ...] = (
    CuratedPosition(
        slug="trump",
        issuer_name="Trump Media & Technology Group Corp.",
        issuer_cik="0001849635",
        ticker="DJT",
        security_title="Common Stock, par value $0.0001 per share",
        shares=114_750_000.0,
        ownership_pct=41.5,
        as_of=date(2025, 12, 18),
        source_form="SCHEDULE 13D/A",
        accession_number="0001140361-25-046424",
        source_url=_TRUMP_13D_URL,
        note=(
            "Titular: Donald J. Trump Revocable Trust (propiedad indirecta). 41,5% sobre "
            "276.497.911 acciones en circulacion segun el 13D/A nº 3 (evento 2025-12-18, "
            "presentado 2025-12-22). No se ha verificado ningun 13D/A posterior."
        ),
    ),
)

CURATED_MOVEMENTS: tuple[CuratedMovement, ...] = (
    CuratedMovement(
        "trump",
        "0001474506-24-000118",
        0,
        "Trump Media & Technology Group Corp.",
        "DJT",
        date(2024, 3, 25),
        date(2024, 3, 28),
        "alta",
        "",
        78_750_000.0,
        78_750_000.0,
        "3",
        f"{_ARCHIVES}/947033/000147450624000118/",
        "Form 3 (declaracion inicial): 78.750.000 acciones emitidas en la fusion con Digital World "
        "(25-mar-2024), mas derecho a 36.000.000 acciones earnout.",
    ),
    CuratedMovement(
        "trump",
        "0001474506-24-000146",
        0,
        "Trump Media & Technology Group Corp.",
        "DJT",
        date(2024, 4, 26),
        date(2024, 4, 30),
        "otro",
        "J",
        36_000_000.0,
        114_750_000.0,
        "4",
        f"{_ARCHIVES}/947033/000147450624000146/",
        "Form 4, codigo J: entrega de 36.000.000 acciones earnout a precio 0; no es compra en mercado.",
    ),
    CuratedMovement(
        "trump",
        "0001474506-24-000291",
        0,
        "Trump Media & Technology Group Corp.",
        "DJT",
        date(2024, 12, 17),
        date(2024, 12, 19),
        "donacion",
        "G",
        114_750_000.0,
        0.0,
        "4",
        f"{_ARCHIVES}/947033/000147450624000291/",
        "Form 4, codigo G: las 114.750.000 acciones dejan de figurar como propiedad directa y pasan a "
        "propiedad indirecta (Donald J. Trump Revocable Trust). No es una venta.",
    ),
)


# ---------------------------------------------------------------- lectura


def _curated_rows(slug: str) -> tuple[list[CuratedPosition], list[CuratedMovement]]:
    return (
        [p for p in CURATED_POSITIONS if p.slug == slug],
        [m for m in CURATED_MOVEMENTS if m.slug == slug],
    )


def _position_item(
    *,
    issuer: str,
    ticker: str | None,
    cusip: str | None,
    title: str,
    shares: float | None,
    ownership_pct: float | None,
    value_usd: float | None,
    value_label: str,
    weight_pct: float | None,
    label: str,
    as_of: date | str | None,
    source_form: str,
    source_url: str,
    note: str,
    weight_label: str | None = None,
) -> dict[str, Any]:
    # Sin formulario de origen no hay procedencia: la URL no cuenta.
    source_url = source_url if source_form else ""
    return {
        "issuer": issuer,
        "ticker": ticker or None,
        "cusip": cusip or None,
        "title_of_class": title,
        "shares": datum(shares, label, as_of, source_url),
        "ownership_pct": datum(ownership_pct, label, as_of, source_url),
        "value_usd": datum(value_usd, value_label, as_of, source_url),
        "weight_pct": datum(weight_pct, weight_label or value_label, as_of, source_url),
        "source_form": source_form,
        "note": note or None,
    }


def _weights(items_values: list[float | None]) -> list[float | None]:
    total = sum(v for v in items_values if v is not None)
    if not total or any(v is None for v in items_values):
        # Peso solo si TODAS las posiciones tienen valor con fuente.
        return [None] * len(items_values)
    return [round(v / total * 100, 2) for v in items_values if v is not None]


def _movement_item(
    *,
    movement_date: date | None,
    filing_date: date | None,
    issuer: str,
    ticker: str | None,
    action: str,
    code: str,
    shares: float | None,
    price: float | None,
    shares_after: float | None,
    label: str,
    source_form: str,
    source_url: str,
    note: str,
) -> dict[str, Any]:
    source_url = source_url if source_form else ""
    return {
        "date": movement_date.isoformat() if movement_date else None,
        "filing_date": filing_date.isoformat() if filing_date else None,
        "issuer": issuer,
        "ticker": ticker or None,
        "action": action,
        "transaction_code": code or None,
        "shares": datum(shares, label, movement_date, source_url),
        "price_usd": datum(price, label, movement_date, source_url),
        "shares_after": datum(shares_after, label, movement_date, source_url),
        "source_form": source_form,
        "note": note or None,
    }


def _portfolio_13f(db: Session, slug: str) -> dict[str, Any]:
    inv = get_investor(slug)
    assert inv is not None
    manager = _manager(db, inv)
    rows = _latest_view(db, manager) if manager else []
    if not rows:
        return {
            "positions": [],
            "movements": [],
            "as_of": None,
            "source_kinds": [],
            "note": "Sin datos: no hay 13F ingerido para este gestor.",
        }
    rows.sort(key=lambda r: r.value_usd_thousands or Decimal(0), reverse=True)
    complete = manager.coverage == "ok" and all(r.value_usd_thousands is not None for r in rows)
    # Peso y total solo si TODAS las filas tienen valor: un denominador parcial
    # daria porcentajes "oficiales" no verificables.
    total = _total(rows) if complete else None
    report = manager.last_report_date  # type: ignore[union-attr]
    positions = [
        _position_item(
            issuer=r.name_of_issuer,
            ticker=None,
            cusip=r.cusip,
            title=r.title_of_class,
            shares=float(r.shares) if r.shares is not None else None,
            ownership_pct=None,
            value_usd=_value_usd(r.value_usd_thousands, report.isoformat()),
            value_label=OFICIAL if r.value_usd_thousands is not None else SIN_DATOS,
            weight_pct=round(float(r.value_usd_thousands) / total * 100, 2)
            if total and r.value_usd_thousands is not None
            else None,
            label=OFICIAL,
            as_of=report,
            source_form="13F-HR",
            source_url=r.filing_url,
            note=("Opción (put/call): importe nocional, no posición en acciones." if r.put_call else ""),
        )
        for r in rows
    ]
    movements: list[dict[str, Any]] = []
    changes = ManagerHoldingIngestionService().changes(db, cik=inv.cik or "")
    if changes.get("status") == "ok":
        latest = date.fromisoformat(changes["latest_report"])
        interesting = [c for c in changes["changes"] if c["change"] != "unchanged"]
        interesting.sort(key=lambda c: -(c.get("value_usd_thousands_latest") or 0))
        for c in interesting[:MOVEMENTS_LIMIT]:
            before, now = c.get("shares_previous"), c.get("shares_latest")
            change = c["change"]
            # Ausencia de valor NO es posicion cero: delta solo con las cifras necesarias
            # presentes. Nueva/cerrada solo se afirma con cobertura completa del gestor.
            if change == "new":
                delta = now if manager.coverage == "ok" else None  # type: ignore[union-attr]
                action = "nueva"
            elif change == "closed":
                delta = -before if (before is not None and manager.coverage == "ok") else None  # type: ignore[union-attr]
                action = "cerrada"
            elif now is not None and before is not None:
                delta = now - before
                action = "aumento" if change == "increased" else "reduccion"
            else:
                delta = None
                action = "sin_datos"
            if delta is None:
                action = "sin_datos"
            movements.append(
                _movement_item(
                    movement_date=latest,
                    filing_date=None,
                    issuer=c["name_of_issuer"],
                    ticker=None,
                    action=action,
                    code="",
                    shares=delta,
                    price=None,
                    shares_after=now,
                    label=OFICIAL,
                    source_form="13F-HR",
                    source_url=positions[0]["shares"]["source_url"] or "",
                    note="Diferencia entre dos 13F trimestrales (fecha = cierre del trimestre, no del trade).",
                )
            )
    return {
        "positions": positions,
        "movements": movements,
        "as_of": report.isoformat(),
        "source_kinds": ["13F-HR"],
        "total_value_usd": datum(
            _value_usd(total, report.isoformat()) if total else None,
            OFICIAL,
            report,
            next((r.filing_url for r in rows if r.filing_url), ""),
        ),
        "coverage": "ok" if complete else "partial",
        "note": None
        if complete
        else "Cobertura parcial: el 13F no esta verificado como completo; pesos y total no disponibles (N/D).",
    }


def _portfolio_other(db: Session, slug: str) -> dict[str, Any]:
    cur_pos, cur_mov = _curated_rows(slug)
    db_pos = list(db.scalars(select(InvestorPosition).where(InvestorPosition.investor_slug == slug)))
    db_mov = list(db.scalars(select(InvestorMovement).where(InvestorMovement.investor_slug == slug)))
    # La BD (sincronizada) gana a lo curado cuando coinciden.
    pos_keys = {(p.issuer_cik, p.security_title, p.as_of) for p in db_pos}
    mov_keys = {(m.accession_number, m.line_no) for m in db_mov}
    entries: list[dict[str, Any]] = []
    for p in db_pos:
        entries.append(
            dict(
                issuer=p.issuer_name,
                ticker=p.ticker,
                cusip=None,
                title=p.security_title,
                shares=float(p.shares) if p.shares is not None else None,
                ownership_pct=float(p.ownership_pct) if p.ownership_pct is not None else None,
                value_usd=float(p.value_usd) if p.value_usd is not None else None,
                value_label=p.value_label if p.value_usd is not None else SIN_DATOS,
                label=p.label,
                as_of=p.as_of,
                source_form=p.source_form,
                source_url=p.source_url,
                note=p.note,
            )
        )
    for c in cur_pos:
        if (c.issuer_cik, c.security_title, c.as_of) in pos_keys:
            continue
        entries.append(
            dict(
                issuer=c.issuer_name,
                ticker=c.ticker,
                cusip=None,
                title=c.security_title,
                shares=c.shares,
                ownership_pct=c.ownership_pct,
                value_usd=None,
                value_label=SIN_DATOS,
                label=OFICIAL,
                as_of=c.as_of,
                source_form=c.source_form,
                source_url=c.source_url,
                note=c.note,
            )
        )
    # Solo la ultima fecha por emisor/clase.
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        key = (e["issuer"], e["title"])
        if key not in latest or str(e["as_of"]) > str(latest[key]["as_of"]):
            latest[key] = e
    ordered = list(latest.values())
    weights = _weights([e["value_usd"] for e in ordered])
    # Peso OFICIAL solo si numerador y denominador son OFICIAL y comparten fecha;
    # con cualquier valor INFERIDO (o fechas distintas) el peso es INFERIDO.
    mixed = any(e["value_label"] != OFICIAL for e in ordered) or len({str(e["as_of"]) for e in ordered}) > 1
    positions = [
        _position_item(weight_pct=w, weight_label=INFERIDO if mixed else OFICIAL, **e)
        for e, w in zip(ordered, weights, strict=True)
    ]
    movements = [
        _movement_item(
            movement_date=m.movement_date,
            filing_date=m.filing_date,
            issuer=m.issuer_name,
            ticker=m.ticker,
            action=m.action,
            code=m.transaction_code,
            shares=float(m.shares) if m.shares is not None else None,
            price=float(m.price_usd) if m.price_usd is not None else None,
            shares_after=float(m.shares_after) if m.shares_after is not None else None,
            label=m.label,
            source_form=m.source_form,
            source_url=m.source_url,
            note=m.note,
        )
        for m in db_mov
    ] + [
        _movement_item(
            movement_date=c.movement_date,
            filing_date=c.filing_date,
            issuer=c.issuer_name,
            ticker=c.ticker,
            action=c.action,
            code=c.transaction_code,
            shares=c.shares,
            price=None,
            shares_after=c.shares_after,
            label=OFICIAL,
            source_form=c.source_form,
            source_url=c.source_url,
            note=c.note,
        )
        for c in cur_mov
        if (c.accession_number, c.line_no) not in mov_keys
    ]
    movements.sort(key=lambda m: m["date"] or "", reverse=True)
    forms = sorted(
        {e["source_form"] for e in entries if e["source_form"]}
        | {m["source_form"] for m in movements if m["source_form"]}
    )
    dates = [str(e["as_of"]) for e in ordered]
    return {
        "positions": positions,
        "movements": movements[:MOVEMENTS_LIMIT],
        "as_of": max(dates) if dates else None,
        "source_kinds": forms,
        "total_value_usd": datum(None, SIN_DATOS, None),
        "note": None if positions else NO_13F_NOTE,
    }


def investor_portfolio(db: Session, slug: str) -> dict[str, Any] | None:
    inv = get_investor(slug)
    if inv is None:
        return None
    body = _portfolio_13f(db, slug) if inv.cik else _portfolio_other(db, slug)
    body.setdefault("total_value_usd", datum(None, SIN_DATOS, None))
    has = bool(body["positions"])
    coverage_note = (
        LIMITATIONS
        if inv.cik
        else "Sin 13F: solo posiciones documentadas en 13D/Forms 3/4. El valor y el peso no están disponibles (N/D) "
        "mientras no haya valoracion con fuente; no es la cartera completa."
    )
    return {
        "slug": inv.slug,
        "name": inv.name,
        "firm": inv.firm,
        "has_13f": inv.cik is not None,
        "status": "ok" if has else "sin_datos",
        "labels": list(LABELS),
        "limitations": coverage_note,
        **body,
    }


# ---------------------------------------------------------------- sincronizacion Form 4


def _action(code: str) -> str:
    return ACTIONS.get(code, "otro")


def sync_form4(db: Session, slug: str, *, limit: int = 20, fetch=None, filings=None) -> int:
    """Descarga los Form 4 recientes del declarante y guarda los movimientos (idempotente).

    ``fetch`` y ``filings`` se inyectan en tests; en produccion usan el conector
    Form 4 (SEC, gratis, con el throttle compartido). Devuelve filas nuevas.
    """
    from app.services.connectors import form4

    cik = FORM4_FILER_CIK.get(slug)
    if cik is None:
        raise ValueError(f"no Form 4 filer CIK reviewed for {slug!r}")
    # Libera cualquier transaccion que ya traiga el llamador (p. ej. un SELECT previo) antes
    # de salir a la red: no se retiene conexion del pool durante los fetch. Solo rollback
    # (nunca commit de cambios ajenos); con cambios pendientes se aborta en vez de descartarlos.
    if db.new or db.dirty or db.deleted:
        raise ValueError("sync_form4 needs a session without pending changes")
    if db.in_transaction():
        db.rollback()
    listing = filings if filings is not None else form4.recent_form4_filings(cik, limit=limit)
    fetch = fetch or form4.fetch_filing_xml
    expected = int(cik)

    # Fase 1: red + parseo, sin tocar la BD (no se retiene transaccion durante el fetch).
    fetched: list[tuple[dict, dict]] = []
    for filing in listing:
        parsed = form4.parse_form4_xml(fetch(filing["document_url"]))
        reporters = parsed.get("reporters") or []
        # Fail closed: un unico declarante y con el CIK revisado; si no, no se persiste.
        if len(reporters) != 1 or not str(reporters[0].get("cik") or "").isdigit():
            continue
        if int(reporters[0]["cik"]) != expected:
            continue
        fetched.append((filing, parsed))

    # Fase 2: persistencia corta.
    created = 0
    for filing, parsed in fetched:
        lines = [t for t in parsed["transactions"] if not t["is_derivative"]]
        for line_no, tx in enumerate(lines):
            exists = db.scalar(
                select(InvestorMovement.id).where(
                    InvestorMovement.investor_slug == slug,
                    InvestorMovement.accession_number == filing["accession_number"],
                    InvestorMovement.line_no == line_no,
                )
            )
            if exists:
                continue
            code = tx["type"] or ""
            shares = tx["shares"]
            db.add(
                InvestorMovement(
                    investor_slug=slug,
                    accession_number=filing["accession_number"],
                    line_no=line_no,
                    issuer_name=parsed["issuer_name"],
                    ticker=parsed["ticker"],
                    movement_date=date.fromisoformat(tx["date"]) if tx["date"] else None,
                    filing_date=date.fromisoformat(filing["filing_date"])
                    if filing.get("filing_date")
                    else None,
                    action=_action(code),
                    transaction_code=code,
                    shares=Decimal(str(shares)) if shares is not None else None,
                    price_usd=Decimal(str(tx["price"])) if tx["price"] is not None else None,
                    label=OFICIAL,
                    source_form=filing["form"],
                    source_url=filing["index_url"],
                    note=CODE_NOTES.get(code, ""),
                )
            )
            created += 1
    db.commit()
    return created
