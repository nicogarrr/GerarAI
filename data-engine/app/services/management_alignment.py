"""Research-only, precomputed alignment evidence. No network or thesis inputs."""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.source_urls import sec_filing_url
from app.core.tenancy import tenant_filters
from app.models.entities import (
    Company,
    CorporateAction,
    Document,
    FinancialFact,
    InsiderFiling,
    InsiderTransaction,
    ManagementAlignmentSnapshot,
)

VERSION = 1
METRICS = {
    "shares_outstanding", "shares_diluted", "stock_based_compensation",
    "common_stock_repurchased", "common_stock_issued", "revenue",
    "operating_cash_flow", "capital_expenditure",
}


def _date(raw: object) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _url(raw: str | None) -> bool:
    try:
        parts = urlsplit(raw or "")
        return parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        return False


def _round(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _ratio(a: dict | None, b: dict | None, *, change: bool = False) -> dict:
    if not a or not b:
        return {"value": None, "reason": "Falta una cifra con fuente y fecha para comparar."}
    if not change and a["date"] != b["date"]:
        return {"value": None, "reason": "Los datos no corresponden al mismo cierre fiscal."}
    if a["unit"] != b["unit"] or b["value"] <= 0:
        return {"value": None, "reason": "Unidades incompatibles o denominador no positivo."}
    return {"value": _round((a["value"] / b["value"] - int(change)) * 100), "sources": [a, b]}


def _evidence(fact: FinancialFact, company: Company, today: date, *, allow_dei: bool = False) -> dict | None:
    end = _date(fact.period)
    if (end is None or end > today or not fact.value.is_finite()
            or not fact.is_reported or fact.source_type not in {"SEC", "ESEF", "CNMV"}
            or not (fact.fiscal_quarter == "FY" and fact.period.endswith(":FY")
                    or allow_dei and fact.metric == "shares_outstanding" and fact.period.endswith(":DEI"))):
        return None
    doc = fact.source
    # SEC accession, not the generic company listing or another year's document.
    cik = company.cik
    if not cik and doc is not None and doc.company_id == company.id:
        cik = (doc.metadata_ or {}).get("cik")
    url = sec_filing_url(None, fact.accession_number, cik) if fact.source_type == "SEC" else (doc.source_url if doc else None)
    filed = fact.filed.isoformat() if fact.filed else None
    if not _url(url) or not filed or fact.filed > today:
        return None
    unit = "shares" if fact.metric in {"shares_outstanding", "shares_diluted"} else company.currency
    if fact.unit != unit:
        return None
    return {"value": float(fact.value), "unit": fact.unit, "date": end.isoformat(),
            "filed": filed, "url": url, "metric": fact.metric, "fact_id": fact.id,
            "basis": "dei" if fact.period.endswith(":DEI") else fact.metric}


def dilution_years(facts: list[FinancialFact], company: Company, splits: list[CorporateAction], today: date) -> list[dict]:
    """Annual evidence, never subtract cash repurchases from shares or fabricate issuance."""
    by_year: dict[int, dict[str, dict]] = {}
    annual_year: dict[str, int] = {}
    annual_end: dict[str, date] = {}
    # One annual filing repeats comparative years. A cover belongs to its latest
    # verified close, not whichever comparative happens to be returned last.
    for f in facts:
        if f.accession_number and f.fiscal_year and f.fiscal_quarter == "FY" and _evidence(f, company, today):
            end = date.fromisoformat(f.period[:10])
            if f.accession_number not in annual_end or end > annual_end[f.accession_number]:
                annual_end[f.accession_number] = end
                annual_year[f.accession_number] = f.fiscal_year
    for fact in sorted(facts, key=lambda f: (not f.period.endswith(":DEI"), f.filed or date.min, f.id or 0), reverse=True):
        evidence = _evidence(fact, company, today, allow_dei=fact.accession_number in annual_year)
        if evidence is not None:
            if fact.period.endswith(":DEI") and not (annual_end[fact.accession_number] <= date.fromisoformat(evidence["date"]) <= annual_end[fact.accession_number] + timedelta(days=180)):
                continue
            year = annual_year[fact.accession_number] if fact.period.endswith(":DEI") else (fact.fiscal_year or int(evidence["date"][:4]))
            by_year.setdefault(year, {}).setdefault(fact.metric, evidence)
    result: list[dict] = []
    previous = None
    for year, metrics in sorted(by_year.items()):
        # Weighted average is a distinct basis, never compared with point-in-time shares.
        shares = metrics.get("shares_outstanding") or metrics.get("shares_diluted")
        sbc, revenue = metrics.get("stock_based_compensation"), metrics.get("revenue")
        repurchases = metrics.get("common_stock_repurchased")
        issued = metrics.get("common_stock_issued")
        delta = {"value": None, "reason": "Falta el ejercicio anterior con la misma base de acciones."}
        if previous and shares and previous["year"] == year - 1:
            prior = previous["shares"]
            if prior and prior["basis"] == shares["basis"]:
                delta = _ratio(shares, prior, change=True)
                if any(s.action_type in {"split", "reverse_split"} and prior["date"] < s.effective_date.isoformat() <= shares["date"] for s in splits):
                    delta = {"value": None, "reason": "Hay un split entre los saldos; no se comparan acciones sin ajustar."}
        fcf = None
        ocf, capex = metrics.get("operating_cash_flow"), metrics.get("capital_expenditure")
        if ocf and capex and ocf["unit"] == capex["unit"] and ocf["date"] == capex["date"] and capex["value"] <= 0:
            # The existing ingestion stores capex as negative cash flow.
            fcf = {**ocf, "value": ocf["value"] + capex["value"]}
        fcf_ratio = _ratio(sbc, fcf)
        if fcf_ratio.get("value") is not None:
            fcf_ratio["sources"] = [sbc, ocf, capex]
        row = {"year": year, "shares": shares, "shares_change_pct": delta,
               "share_basis": shares["basis"] if shares else None,
               "sbc": sbc, "sbc_revenue_pct": _ratio(sbc, revenue),
               "sbc_fcf_pct": fcf_ratio, "repurchases": repurchases,
               "repurchases_label": "Recompras (bruto)",
               "change_label": "Dilución neta anual" if repurchases and issued else "Variación de acciones",
               "warnings": []}
        if shares and shares["value"] <= 0:
            row["warnings"].append("Saldo de acciones no positivo; revisar el dato reportado.")
        if not sbc:
            row["warnings"].append("Sin datos de SBC con fuente y fecha en los hechos anuales persistidos; no implica que no exista SBC.")
        if not repurchases:
            row["warnings"].append("Recompras N/D: falta el importe anual con fuente y fecha; no equivale a cero.")
        if shares and shares["metric"] == "shares_diluted":
            row["warnings"].append("Base alternativa: promedio ponderado diluido, no saldo de acciones al cierre.")
        if delta.get("value") is not None and abs(delta["value"]) > 40:
            row["warnings"].append("Variación abrupta: podría haber un split, una fusión o un cambio de perímetro no registrado. Revisar la fuente.")
        if sbc and sbc["value"] < 0 or repurchases and repurchases["value"] < 0 or capex and capex["value"] > 0:
            row["warnings"].append("Signo inusual en un flujo reportado; revisar la fuente. No se ha ocultado la cifra.")
        row["quality_warnings"] = [w for w in row["warnings"] if not w.startswith("Sin datos de SBC") and not w.startswith("Recompras N/D")]
        result.append(row)
        previous = row
    return result[-5:]


def _months_before(today: date, months: int) -> date:
    year, month0 = divmod(today.year * 12 + today.month - 1 - months, 12)
    return date(year, month0 + 1, min(today.day, calendar.monthrange(year, month0 + 1)[1]))


def insider_windows(rows: list[tuple[InsiderTransaction, str | None]], today: date) -> list[dict]:
    windows = []
    for months in (6, 12):
        trades = []
        warnings = []
        for tx, filing_date in rows:
            effective = _date(tx.tx_date) or _date(filing_date)
            if tx.code not in {"P", "S"} or tx.is_derivative:
                continue
            if effective is None:
                warnings.append("Operación P/S sin fecha; no se asigna a una ventana.")
                continue
            if not _months_before(today, months) <= effective <= today:
                continue
            # Legacy False means unknown until explicit XML evidence is persisted.
            plan = (tx.data_quality or {}).get("alignment_10b5_1")
            plan = plan if type(plan) is bool else None
            value = tx.value if tx.value is not None else (tx.shares * tx.price if tx.shares is not None and tx.price is not None else None)
            reported_value = None
            if value is not None and (not Decimal(str(value)).is_finite() or value < 0):
                warnings.append("Importe P/S inválido; se conserva la operación sin sumarlo al flujo.")
                reported_value = str(value)
                value = None
            trades.append({"code": tx.code, "plan": plan, "value": value,
                           "reported_value": reported_value, "date": effective.isoformat(), "url": tx.source_url if _url(tx.source_url) else None,
                           "accession": tx.accession_number, "form": tx.form})
        if any(not t["url"] for t in trades):
            warnings.append("Hay operaciones sin enlace de origen; el agregado no se publica como cifra verificable.")
        if any(t["form"] in {"4/A", "5/A"} for t in trades):
            warnings.append("Hay enmiendas sin vínculo al original; no se publica un flujo que podría duplicarlo.")
        values_complete = all(t["value"] is not None for t in trades)
        traceable = bool(trades) and all(t["url"] for t in trades)
        amended = any(t["form"] in {"4/A", "5/A"} for t in trades)
        groups = {"buys": [t for t in trades if t["code"] == "P"],
                  "planned_sales": [t for t in trades if t["code"] == "S" and t["plan"] is True],
                  "unplanned_sales": [t for t in trades if t["code"] == "S" and t["plan"] is False],
                  "unknown_sales": [t for t in trades if t["code"] == "S" and t["plan"] is None]}
        net = None
        discretionary = None
        if traceable and not amended and values_complete:
            net = sum(t["value"] * (1 if t["code"] == "P" else -1) for t in trades)
            if not groups["unknown_sales"]:
                discretionary = sum(t["value"] for t in groups["buys"]) - sum(t["value"] for t in groups["unplanned_sales"])
        windows.append({"months": months, "from": _months_before(today, months).isoformat(),
                        "to": today.isoformat(), "groups": groups, "net_value": net,
                        "discretionary_net_value": discretionary, "warnings": list(dict.fromkeys(warnings)),
                        "status": "ok" if traceable and not amended else "sin_datos",
                        "reason": "No hay P/S no derivados, fechados y enlazados en los registros persistidos de esta ventana." if not trades else "La procedencia o las enmiendas impiden un agregado completo."})
    return windows


def recompute_alignment(db: Session, company: Company, *, today: date | None = None) -> ManagementAlignmentSnapshot:
    today = today or date.today()
    facts = list(db.scalars(select(FinancialFact).options(selectinload(FinancialFact.source).load_only(Document.source_url, Document.company_id, Document.metadata_)).where(
        FinancialFact.company_id == company.id, FinancialFact.metric.in_(METRICS), *tenant_filters(db, FinancialFact))))
    splits = list(db.scalars(select(CorporateAction).where(CorporateAction.company_id == company.id,
        CorporateAction.action_type.in_(("split", "reverse_split")), *tenant_filters(db, CorporateAction))))
    rows = list(db.execute(select(InsiderTransaction, InsiderFiling.filing_date).join(
        InsiderFiling, InsiderTransaction.filing_id == InsiderFiling.id).where(
        InsiderTransaction.issuer_ticker == company.ticker, InsiderTransaction.code.in_(("P", "S")),
        InsiderTransaction.is_derivative.is_(False), *tenant_filters(db, InsiderTransaction, InsiderFiling))))
    years = dilution_years(facts, company, splits, today)
    payload = {"ticker": company.ticker, "computed_at": datetime.now(UTC).isoformat(), "as_of": today.isoformat(),
               "years": years, "insiders": insider_windows(rows, today),
               "dilution_reason": "No hay hechos anuales con fuente, fecha, unidad y periodo verificables en la base persistida. La cobertura XBRL puede ser parcial." if not years else None}
    record = db.scalar(select(ManagementAlignmentSnapshot).where(
        ManagementAlignmentSnapshot.company_id == company.id, *tenant_filters(db, ManagementAlignmentSnapshot)))
    if record is None:
        record = ManagementAlignmentSnapshot(company_id=company.id, tenant_id=db.info.get("tenant_id"))
        db.add(record)
    record.payload = payload
    record.version = VERSION
    db.flush()
    return record


def read_alignment(db: Session, company: Company, *, today: date | None = None) -> dict:
    record = db.scalar(select(ManagementAlignmentSnapshot).where(
        ManagementAlignmentSnapshot.company_id == company.id, *tenant_filters(db, ManagementAlignmentSnapshot)))
    if record is None or record.version != VERSION:
        return {"status": "pendiente", "ticker": company.ticker,
                "reason": "El job de agregación todavía no ha generado una instantánea compatible para esta empresa."}
    payload = dict(record.payload)
    computed_date = _date(payload.get("as_of"))
    payload["stale"] = computed_date is None or computed_date < (today or date.today()) - timedelta(days=1)
    return {"status": "ok", **payload}
