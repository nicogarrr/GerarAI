"""Solape derivado por CUSIP exacto, sin emparejar emisores por nombre."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Position
from app.models.entities import InstrumentReference
from app.services.investors import INVESTORS, _latest_view, _manager, _value_usd, most_bought
from app.services.manager_holding_ingestion_service import public_coverage, verification_status


def _isin_cusip(isin: str | None) -> str | None:
    value = isin or ""
    if not re.fullmatch(r"(?:US|CA)[A-Z0-9]{9}\d", value):
        return None
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    checksum = sum((n * 2 // 10 + n * 2 % 10) if i % 2 else n
                   for i, n in enumerate(map(int, reversed(digits))))
    return value[2:11] if checksum % 10 == 0 else None


def _cusip(company: Company, reference: InstrumentReference | None) -> tuple[str | None, str | None]:
    own = _isin_cusip(company.isin)
    ref_cusip = reference.cusip if reference and reference.cusip else None
    ref_isin = reference.isin if reference and reference.isin else None
    if reference and reference.ticker_normalized != company.ticker.strip().upper():
        return None, "Identidad en conflicto: la referencia no corresponde al ticker."
    if company.isin and ref_isin and company.isin != ref_isin:
        return None, "Identidad en conflicto: los ISIN registrados no coinciden."
    if ref_cusip and not re.fullmatch(r"[A-Z0-9*@#]{9}", ref_cusip):
        return None, "Referencia CUSIP inválida."
    derived_ref = _isin_cusip(ref_isin)
    if ref_cusip and derived_ref and ref_cusip != derived_ref:
        return None, "Identidad en conflicto: CUSIP e ISIN de la referencia."
    if own and ref_cusip and own != ref_cusip:
        return None, "Identidad en conflicto: CUSIP de referencia e ISIN de cartera."
    if own:
        return own, "CUSIP derivado del ISIN registrado"
    if company.isin:
        # Un identificador mal formado o no derivable no permite usar un ticker como sustituto.
        return None, "ISIN registrado sin CUSIP derivable verificado."
    if ref_isin and derived_ref is None:
        return None, "ISIN de referencia sin CUSIP derivable verificado."
    if reference and ref_cusip:
        return ref_cusip, f"Referencia {reference.source} · {reference.as_of.isoformat()}"
    return None, None


def portfolio_overlap(db: Session) -> dict:
    tenant = db.info.get("tenant_id")
    empty = {"status": "sin_datos", "kind": "derivado", "positions": [], "not_owned": [],
             "unresolved_positions": 0, "managers_with_data": 0, "managers_without_data": 0, "managers_partial": 0,
             "report_dates": [], "message": "Cartera sin posiciones abiertas."}
    if tenant is None:
        return empty
    # Sin DISTINCT sobre la entidad: companies tiene columnas JSON y postgres
    # no define operador de igualdad para json (500 en prod). La
    # deduplicacion va en la subquery de ids.
    company_ids = (
        select(Position.company_id)
        .where(Position.tenant_id == tenant, Position.quantity > 0)
        .distinct()
    )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids))).all())
    if not companies:
        return empty
    refs = {r.ticker_normalized: r for r in db.scalars(select(InstrumentReference).where(
        InstrumentReference.ticker_normalized.in_([c.ticker.strip().upper() for c in companies]))).all()}
    positions = []
    for c in companies:
        cusip, source = _cusip(c, refs.get(c.ticker.strip().upper()))
        positions.append({"ticker": c.ticker, "name": c.name, "cusip": cusip,
                          "identity_source": source, "holders": [],
                          "status": "sin_identificador" if cusip is None else "sin_coincidencias"})
    by_cusip = {}
    for p in positions:
        if p["cusip"]:
            by_cusip.setdefault(p["cusip"], []).append(p)
    periods = set()
    available = missing = partial = 0
    for inv in INVESTORS:
        if not inv.cik:
            continue
        manager = _manager(db, inv)
        rows = _latest_view(db, manager) if manager else []
        if not rows:
            missing += 1
            continue
        available += 1
        partial += int(public_coverage(manager.coverage) == "partial")
        seen = set()
        for row in rows:
            if row.put_call or row.cusip not in by_cusip or row.cusip in seen:
                continue
            seen.add(row.cusip)
            periods.add(row.report_date.isoformat())
            holder = {"slug": inv.slug, "name": inv.name, "report_date": row.report_date.isoformat(),
                      "filing_date": row.filing_date.isoformat() if row.filing_date else None,
                      "filing_url": row.filing_url, "coverage": public_coverage(manager.coverage),
                      "verification": verification_status(manager.coverage)}
            for position in by_cusip[row.cusip]:
                position["holders"].append(holder)
                position["status"] = "coincidencia"
    unresolved = sum(p["cusip"] is None for p in positions)
    bought = most_bought(db)
    # Sin identidad completa no se puede afirmar que una compra ajena esté fuera de la cartera.
    candidates = [] if unresolved else [i for i in bought["items"]
                                       if i["cusip"] not in by_cusip and i["buyers_count"] >= 2]
    return {**empty, "status": "ok" if available else "sin_datos", "positions": positions,
            "not_owned": candidates, "unresolved_positions": unresolved,
            "managers_with_data": available, "managers_without_data": missing, "managers_partial": partial,
            "report_dates": sorted(periods | set(bought["report_dates"])),
            "message": None if available else "Sin informes 13F sincronizados.",
            "comparison_complete": unresolved == 0 and missing == 0 and partial == 0,
            "limitations": ["Derivado por CUSIP exacto. Sin coincidencia no significa ausencia en todas sus carteras.",
                            "13F histórico, con hasta 45 días de retraso. Solo posiciones largas declaradas; no opciones."]}


_LIMITATIONS_13F = [
    "Derivado por CUSIP exacto. Sin coincidencia no significa ausencia en todas sus carteras.",
    "13F histórico, con hasta 45 días de retraso. Solo posiciones largas declaradas; no opciones.",
]


def holders_by_ticker(db: Session, ticker: str) -> dict | None:
    """Gestores revisados que declaran el ticker en su último 13F (vista inversa).

    Mismo cruce que el solape de cartera: CUSIP exacto con las comprobaciones
    de identidad de `_cusip`; sin identidad verificada no se afirma nada.
    Devuelve None si el ticker no existe en el universo.
    """
    normalized = ticker.strip().upper()
    company = db.scalar(select(Company).where(Company.ticker == normalized))
    if company is None:
        return None
    reference = db.scalar(
        select(InstrumentReference).where(InstrumentReference.ticker_normalized == normalized)
    )
    cusip, source = _cusip(company, reference)
    base = {
        "ticker": company.ticker,
        "name": company.name,
        "cusip": cusip,
        "identity_source": source,
        "holders": [],
        "managers_with_data": 0,
        "managers_without_data": 0,
        "managers_partial": 0,
        "limitations": _LIMITATIONS_13F,
    }
    if cusip is None:
        return {**base, "status": "sin_identificador"}
    available = missing = partial = 0
    holders = []
    for inv in INVESTORS:
        if not inv.cik:
            continue
        manager = _manager(db, inv)
        rows = _latest_view(db, manager) if manager else []
        if not rows:
            missing += 1
            continue
        available += 1
        partial += int(public_coverage(manager.coverage) == "partial")
        seen = set()
        for row in rows:
            if row.put_call or row.cusip != cusip or row.cusip in seen:
                continue
            seen.add(row.cusip)
            holders.append({
                "slug": inv.slug,
                "name": inv.name,
                "report_date": row.report_date.isoformat() if row.report_date else None,
                "filing_date": row.filing_date.isoformat() if row.filing_date else None,
                "filing_url": row.filing_url or None,
                "coverage": public_coverage(manager.coverage),
                "verification": verification_status(manager.coverage),
                "value_usd": _value_usd(
                    row.value_usd_thousands,
                    row.report_date.isoformat() if row.report_date else None,
                ),
                "shares": float(row.shares) if row.shares is not None else None,
            })
    holders.sort(key=lambda h: h["value_usd"] or 0.0, reverse=True)
    return {
        **base,
        "status": "ok" if available else "sin_datos",
        "holders": holders,
        "managers_with_data": available,
        "managers_without_data": missing,
        "managers_partial": partial,
    }
