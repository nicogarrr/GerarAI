"""Estimaciones propias y enlace exacto de cada cifra (solo lectura).

- GET /companies/{ticker}/own-consensus: celdas del consenso propio (``own_consensus``)
  con su fuente, fórmula, puertas y confianza, más el acierto medido por fuente y
  horizonte (``estimate_accuracy``). Sin red ni modelo.
- GET /companies/{ticker}/fact-source-link?metric=&period=: el enlace de una cifra
  guardada a su sitio exacto en el informe iXBRL de la SEC (``sec_fact_anchor``) y si
  es presentada o derivada (4T = año − 9M). Lee el documento del filing una vez y lo
  recuerda en memoria del proceso.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.company_resolver import resolve_company

router = APIRouter()
_PRIMARY = re.compile(r'<a href="(?:/ix\?doc=)?(/Archives/edgar/data/[^"]+?\.htm)">[^<]*</a>\s*</td>\s*'
                      r'<td scope="row">(10-K|10-Q|20-F|40-F|10-K/A|10-Q/A)</td>', re.I)


def _company(db: Session, ticker: str) -> Any:
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_dot").detail)
    return company


def _tenant(db: Session) -> int:
    tenant = db.info.get("tenant_id")
    return tenant if type(tenant) is int else 0


@router.get("/{ticker}/own-consensus")
def own_consensus(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Consenso propio por métrica y periodo y acierto medido de cada fuente."""
    from app.services.estimate_accuracy import company_accuracy
    from app.services.own_consensus import build_company_consensus

    company = _company(db, ticker)
    tenant = _tenant(db)
    acc = company_accuracy(db, company, tenant)
    result = build_company_consensus(db, company, tenant, measured_errors=acc["measured_errors"])
    result["accuracy"] = {"version": acc["version"], "by_source": acc["by_source"],
                          "cases": acc["cases"][-60:]}
    return result


@lru_cache(maxsize=48)
def _filing_document(cik: str, accession: str) -> tuple[str | None, str | None]:
    from app.services.connectors import form4
    from app.services.connectors.edgar_common import filing_index_url

    index = form4._get_text(filing_index_url(cik, accession) + f"{accession}-index.htm", None)  # noqa: SLF001
    m = _PRIMARY.search(index)
    if m is None:
        return None, None
    url = f"https://www.sec.gov{m.group(1)}"
    return url, form4._get_text(url, None)  # noqa: SLF001


@router.get("/{ticker}/fact-source-link")
def fact_source_link(ticker: str, metric: str = Query(..., max_length=60),
                     period: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}:(FY|Q[1-4])$"),
                     db: Session = Depends(get_db)) -> dict:
    """Enlace exacto de una cifra presentada (``#id`` del elemento iXBRL) o su fórmula si es derivada."""
    from app.models import FinancialFact
    from app.services.own_consensus import actuals_from_facts
    from app.services.sec_fact_anchor import source_link

    company = _company(db, ticker)
    fact = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                  FinancialFact.metric == metric,
                                                  FinancialFact.period == period)).first()
    additive = metric in {"revenue", "operating_income"}
    if fact is None and period.endswith(":Q4") and additive:
        rows = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                      FinancialFact.metric == metric)).all()
        acts = actuals_from_facts([(str(r.period), float(r.value), r.filed, r.source_url) for r in rows],
                                  metric=metric)
        derived = next((a for a in acts.values() if a.derived and a.end.isoformat() == period[:10]), None)
        if derived is not None:
            return {"metric": metric, "period": period, "value": derived.value,
                    **source_link(metric=metric, period=period, value=derived.value, doc_url=derived.url,
                                  html=None, derived_formula=derived.formula)}
    if fact is None:
        raise HTTPException(status_code=404, detail="Sin esa cifra guardada")
    out: dict[str, Any] = {"metric": metric, "period": period, "value": float(fact.value),
                           "accession": fact.accession_number, "filed": fact.filed.isoformat() if fact.filed else None}
    cik = (getattr(company, "cik", None) or "").strip()
    if not fact.accession_number or not cik.isdigit():
        out.update({"calc_type": "reported" if fact.is_reported else "derived", "url": fact.source_url,
                    "anchor": None, "reason": "sin filing de la SEC con el que anclar la cifra"})
        return out
    try:
        doc_url, html = _filing_document(str(int(cik)), str(fact.accession_number))
    except Exception as exc:  # noqa: BLE001 - sin el documento queda el enlace al filing
        doc_url, html = None, None
        out["reason"] = f"documento de la SEC no disponible ({type(exc).__name__})"
    out.update(source_link(metric=metric, period=period, value=float(fact.value), doc_url=doc_url or fact.source_url,
                           html=html))
    if out.get("anchor") is None and "reason" not in out:
        out["reason"] = "la cifra no aparece etiquetada con ese periodo y valor en el documento principal"
    return out
