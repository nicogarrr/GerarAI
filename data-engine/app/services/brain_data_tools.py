"""Read-only, tenant-scoped answers to concrete Cerebro data questions.

No provider calls, ingestion, writes or invented current quotes. A stored price
is always dated. Ratios reuse the screener's audited annual EPS/currency rules.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice, NewsEvent, Position, ThesisVersion
from app.schemas import ChatResponse
from app.services.screener_fundamentals import load_screener_ratios


def _number(value) -> str:
    return f"{float(value):,.2f}".replace(",", "\x07").replace(".", ",").replace("\x07", ".")


def _link(company: Company, view: str = "financials") -> str:
    return f"/research/{quote(company.ticker, safe='')}?view={view}"


def _response(lines: list[str], sources: list[dict], path: str) -> ChatResponse:
    return ChatResponse(answer="\n\n".join(lines), sources=sources, model="deterministic",
                        prompt_version="brain-data-v1", confidence=0.9,
                        llm_trace={"path": path, "provider_calls": 0, "generated": False})


def _source(kind: str, ident, title: str, url: str) -> dict:
    return {"type": kind, "id": ident, "title": title, "url": url}


def _company_data(db: Session, company: Company) -> tuple[list[str], list[dict]]:
    price = db.scalar(select(MarketPrice).where(
        MarketPrice.company_id == company.id, MarketPrice.date <= date.today(),
        MarketPrice.close > 0, MarketPrice.source.not_in(["seed", "test", "mock", "dummy", "placeholder"]),
    ).order_by(MarketPrice.date.desc()).limit(1))
    lines = [f"**{company.ticker} · {company.name}**"]
    sources: list[dict] = []
    if price is None:
        lines.append("Precio: sin cotización válida almacenada.")
    else:
        lines.append(f"Último precio almacenado: {_number(price.close)} {company.currency} "
                     f"({price.date.isoformat()}, {price.source}). No es una cotización en directo.")
        sources.append(_source("market_price", price.id, f"Precio {company.ticker} · {price.date}", _link(company)))
    ratio = load_screener_ratios(db, {company.ticker}).get(company.ticker, {}) if price else {}
    pe = ratio.get("pe")
    if pe is None:
        lines.append("PER: no calculable con precio reciente y BPA anual positivo, verificado y en la misma moneda.")
    else:
        fact = ratio.get("ratioProvenance", {}).get("facts", {}).get("pe", {})
        lines.append(f"PER sobre BPA anual: {_number(pe)} veces (ejercicio {fact.get('year')}); "
                     "precio / beneficio diluido por acción. No es un PER previsto ni de los últimos doce meses.")
        sources.append(_source("financial_fact", fact.get("id"), f"BPA anual {company.ticker} · {fact.get('year')}", _link(company)))
    return lines, sources


def answer_data_question(db: Session, question: str) -> ChatResponse | None:
    """None means this tool does not own the question; never guess user intent."""
    tenant = db.info.get("tenant_id")
    if type(tenant) is not int or tenant <= 0:
        return None
    news = bool(re.search(r"(?i)\bnoticias?\b", question)) and bool(re.search(r"(?i)\bmis\s+(?:empresas|acciones|posiciones)\b|\bmi\s+cartera\b", question))
    theses = bool(re.search(r"(?i)\btesis\b", question)) and bool(re.search(r"(?i)\b(?:tengo|mis|activas|vigentes)\b", question))
    comparison = bool(re.search(r"(?i)\bcompara\w*\b", question))
    valuation = bool(re.search(r"(?i)\b(?:precio|PER|cotiza\w*)\b", question)) and not re.search(r"(?i)\b(?:medio|coste|peso|posici[oó]n|tengo)\b", question)
    if not (news or theses or comparison or valuation):
        return None
    if re.search(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b", question):
        return None
    if news:
        company_ids = select(Position.company_id).where(Position.tenant_id == tenant, Position.quantity > 0)
        rows = db.execute(select(NewsEvent, Company).join(Company, Company.id == NewsEvent.company_id).where(
            NewsEvent.tenant_id == tenant, NewsEvent.company_id.in_(company_ids),
        ).order_by(NewsEvent.date.desc(), NewsEvent.id.desc()).limit(40)).all()
        lines, sources, seen = [], [], set()
        for event, company in rows:
            key = " ".join(event.title.lower().split())
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {company.ticker}: {event.title} ({event.date.date().isoformat()}, {event.source}).")
            sources.append(_source("news_event", event.id, f"{company.ticker}: {event.title}", event.url or _link(company, "news")))
            if len(lines) == 6:
                break
        return _response(["Últimas noticias guardadas de tus posiciones abiertas:", *lines] if lines else ["No hay noticias guardadas de tus posiciones abiertas. No he consultado noticias en directo."], sources, "portfolio_news")
    if theses:
        rows = db.execute(select(ThesisVersion, Company).join(Company, Company.id == ThesisVersion.company_id).where(
            ThesisVersion.tenant_id == tenant,
        ).order_by(Company.ticker, ThesisVersion.version.desc())).all()
        latest, published = {}, {}
        for thesis, company in rows:
            latest.setdefault(company.id, (thesis, company))
            if thesis.status == "published":
                published.setdefault(company.id, (thesis, company))
        active, drafts, sources = [], [], []
        for thesis, company in published.values():
            active.append(f"- {company.ticker}: tesis v{thesis.version} (publicada).")
            sources.append(_source("thesis_version", thesis.id, f"Tesis {company.ticker} v{thesis.version}", _link(company, "thesis")))
        for thesis, company in latest.values():
            if thesis.status != "published":
                drafts.append(f"- {company.ticker}: v{thesis.version}, no activa (borrador o pendiente de publicación).")
                sources.append(_source("thesis_version", thesis.id, f"Última versión {company.ticker} v{thesis.version}", _link(company, "thesis")))
        lines = ["Tesis activas (última publicada por empresa):", *active] if active else ["No hay tesis publicadas guardadas."]
        if drafts:
            lines += ["Otras últimas versiones guardadas (no activas):", *drafts]
        return _response(lines, sources, "portfolio_theses")
    # Exact catalog matches only. Comparisons need at least two explicit tickers;
    # a single-price query needs exactly one. No page-context guess here.
    tokens = set(re.findall(r"\b[A-Z][A-Z0-9.-]{1,14}\b", question))
    companies = list(db.scalars(select(Company).where(Company.ticker.in_(tokens))).all()) if tokens else []
    if (comparison and len(companies) < 2) or (not comparison and len(companies) != 1):
        return None
    lines, sources = [], []
    for company in sorted(companies, key=lambda item: item.ticker)[:4]:
        company_lines, company_sources = _company_data(db, company)
        lines.extend(company_lines)
        sources.extend(company_sources)
    if comparison:
        lines.append("Comparativa de los datos guardados de precio y PER; no basta para decidir qué empresa es mejor inversión.")
    return _response(lines, sources, "company_comparison" if comparison else "company_quote")
