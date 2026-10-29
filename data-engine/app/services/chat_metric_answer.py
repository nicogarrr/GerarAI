"""Question-specific answers: do not substitute a company evidence dump."""
import re
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.source_urls import linkable_source_url
from app.models import Company, Document, FinancialFact
from app.schemas import ChatResponse


def metric_question_answer(db: Session, question: str, company: Company | None) -> ChatResponse | None:
    tenant = db.info.get("tenant_id")
    if company is None or type(tenant) is not int or tenant <= 0:
        return None
    margin = bool(re.search(r"(?i)\bmargen\b.*\b(?:FCF|caja libre)\b|\bFCF\b.*\bmargen\b", question))
    stores = bool(re.search(r"(?i)\btiendas?\b", question))
    if not margin and not stores:
        return None
    sources = []
    if stores:
        answer = (f"No tengo un recuento verificado de tiendas físicas de {company.ticker} "
                  "en los datos financieros que consulta este chat. No puedo deducirlo de los ingresos ni del precio.")
    else:
        rows = db.scalars(select(FinancialFact).where(
            FinancialFact.tenant_id == tenant, FinancialFact.company_id == company.id,
            FinancialFact.metric.in_(["free_cash_flow", "revenue"]),
            FinancialFact.source_type.in_(["SEC", "ESEF"]), FinancialFact.is_reported.is_(True),
        ).order_by(FinancialFact.fiscal_year.desc().nullslast(), FinancialFact.id.desc())).all()
        by_period = {}
        for row in rows:
            by_period.setdefault((row.period, row.unit, row.source_type), {}).setdefault(row.metric, row)
        pair = next((group for group in by_period.values() if "free_cash_flow" in group and "revenue" in group
                     and group["revenue"].value is not None and group["revenue"].value > 0
                     and group["free_cash_flow"].value is not None), None)
        if pair is None:
            answer = (f"No puedo calcular el margen FCF de {company.ticker}: faltan flujo de caja libre e ingresos "
                      "verificados del mismo periodo y moneda. No usaré el margen bruto como sustituto.")
        else:
            fcf, revenue = pair["free_cash_flow"], pair["revenue"]
            def num(value):
                return f"{float(value):,.2f}".replace(",", "\x07").replace(".", ",").replace("\x07", ".")

            def money(value, unit):
                # USD en-US ($25.00); otras unidades es-ES con su código.
                return f"${float(value):,.2f}" if unit == "USD" else f"{num(value)} {unit}"
            answer = (f"El margen FCF de {company.ticker} es {num(fcf.value / revenue.value * 100)} % "
                      f"en el periodo {fcf.period}. Se calcula como flujo de caja libre "
                      f"({money(fcf.value, fcf.unit)}) / ingresos ({money(revenue.value, revenue.unit)}) × 100.")
            for fact, title in [(fcf, "Flujo de caja libre"), (revenue, "Ingresos")]:
                document = db.scalar(select(Document).where(Document.id == fact.source_id, Document.tenant_id == tenant)) if fact.source_id else None
                url = (linkable_source_url(document.source_url) if document else None) or f"/research/{quote(company.ticker, safe='')}?view=financials"
                sources.append({"type": "financial_fact", "id": fact.id, "title": f"{title} · {fact.period} · {fact.source_type}", "url": url})
    return ChatResponse(answer=answer, sources=sources, model="deterministic", confidence=0.9,
                        prompt_version="specific-metric-v1", llm_trace={"path": "specific_metric", "provider_calls": 0})
