"""Read-only, tenant-scoped answers to concrete Cerebro data questions.

No provider calls, ingestion, writes or invented current quotes. A stored price
is always dated. Ratios reuse the screener's audited annual EPS/currency rules.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, DividendRecord, MarketPrice, NewsEvent, Position, ThesisVersion
from app.schemas import ChatResponse
from app.services.investment_plan_service import InvestmentPlanService
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.screener_fundamentals import load_screener_ratios


def _number(value) -> str:
    return f"{float(value):,.2f}".replace(",", "\x07").replace(".", ",").replace("\x07", ".")


def _money(value, currency) -> str:
    """USD en formato en-US ($120.50); el resto de divisas, es-ES con su código."""
    if currency == "USD":
        return f"${float(value):,.2f}"
    return f"{_number(value)} {currency or ''}".strip()


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
        lines.append(f"Último precio almacenado: {_money(price.close, company.currency)} "
                     f"({price.date.isoformat()}, {price.source}). No es una cotización en directo.")
        sources.append(_source("market_price", price.id, f"Precio {company.ticker} · {price.date}", _link(company)))
    ratio = load_screener_ratios(db, {company.ticker}).get(company.ticker, {}) if price else {}
    pe = ratio.get("pe")
    if pe is None:
        lines.append("PER: sin dato calculable guardado; hace falta un precio reciente y un BPA anual positivo, verificado y en la misma moneda.")
    else:
        fact = ratio.get("ratioProvenance", {}).get("facts", {}).get("pe", {})
        lines.append(f"PER sobre BPA anual: {_number(pe)} veces (ejercicio {fact.get('year')}); "
                     "precio / beneficio diluido por acción. No es un PER previsto ni de los últimos doce meses.")
        sources.append(_source("financial_fact", fact.get("id"), f"BPA anual {company.ticker} · {fact.get('year')}", _link(company)))
    return lines, sources


_NAME_NOISE = {"inc", "corp", "co", "company", "the", "sa", "plc", "ltd", "nv", "ag", "se", "holdings", "group"}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _company_in_question(db: Session, question: str) -> Company | None:
    """Empresa del catalogo nombrada por ticker o nombre; None si hay 0 o varias."""
    squashed = _squash(question)
    found: dict[int, Company] = {}
    for company in db.scalars(select(Company)).all():
        core = _squash(" ".join(w for w in re.split(r"[\s,.]+", company.name.lower()) if w and w not in _NAME_NOISE))
        by_ticker = re.search(rf"(?<![A-Za-z0-9]){re.escape(company.ticker)}(?![A-Za-z0-9])", question) is not None
        if by_ticker or (len(core) >= 4 and core in squashed):
            found[company.id] = company
    return next(iter(found.values())) if len(found) == 1 else None


def _dividend_line(company: Company, record: DividendRecord) -> str:
    pay = f", pago {record.pay_date.isoformat()}" if record.pay_date else ""
    return (f"{company.ticker}: {_money(record.amount, record.currency)} por acción, "
            f"ex-dividendo {record.ex_date.isoformat()}{pay} ({record.source}).")


def _dividend_answer(db: Session, question: str, tenant: int) -> ChatResponse | None:
    """Dividendos GUARDADOS (declarados por el proveedor); nada proyectado ni inventado."""
    today = date.today()
    portfolio = bool(re.search(r"(?i)\bmi\s+cartera\b|\bmis\s+(?:posiciones|acciones|empresas)\b|\bcobrar\w*\b", question))
    company = None if portfolio else _company_in_question(db, question)
    if company is not None:
        records = list(db.scalars(select(DividendRecord).where(
            DividendRecord.company_id == company.id, DividendRecord.tenant_id == tenant,
        ).order_by(DividendRecord.ex_date.desc()).limit(40)).all())
        sources = [_source("dividend_record", r.id, f"Dividendo {company.ticker} · {r.ex_date}", _link(company)) for r in records[:1]]
        upcoming = sorted((r for r in records if r.ex_date >= today), key=lambda r: r.ex_date)
        past = [r for r in records if r.ex_date < today]
        if not records:
            return _response([f"No tengo dividendos guardados de {company.ticker}. No he consultado el proveedor en directo."], [], "company_dividends")
        lines = [f"**Dividendos guardados de {company.ticker} · {company.name}**"]
        if upcoming:
            lines.append("Próximo declarado: " + _dividend_line(company, upcoming[0]))
            sources = [_source("dividend_record", upcoming[0].id, f"Dividendo {company.ticker} · {upcoming[0].ex_date}", _link(company))]
        else:
            lines.append("No hay un próximo dividendo declarado guardado.")
        if past:
            lines.append("Último pagado guardado: " + _dividend_line(company, past[0]))
            sources.append(_source("dividend_record", past[0].id, f"Dividendo {company.ticker} · {past[0].ex_date}", _link(company)))
        return _response(lines, sources, "company_dividends")
    if not portfolio:
        return None
    rows = db.execute(select(Position, Company).join(Company, Company.id == Position.company_id).where(
        Position.tenant_id == tenant, Position.quantity > 0)).all()
    if not rows:
        return _response(["No hay posiciones abiertas en tu cartera."], [], "portfolio_dividends")
    lines, sources, totals, without = [], [], {}, []
    for position, comp in sorted(rows, key=lambda r: r[1].ticker):
        records = [r for r in db.scalars(select(DividendRecord).where(
            DividendRecord.company_id == comp.id, DividendRecord.tenant_id == tenant,
            DividendRecord.ex_date >= date(today.year, 1, 1), DividendRecord.ex_date <= date(today.year, 12, 31),
        ).order_by(DividendRecord.ex_date)).all() if r.currency == position.currency]
        if not records:
            without.append(comp.ticker)
            continue
        amount = sum((r.amount for r in records), Decimal("0")) * Decimal(str(position.quantity))
        totals[position.currency] = totals.get(position.currency, Decimal("0")) + amount
        lines.append(f"- {comp.ticker}: {len(records)} pago(s) en {today.year}, {_money(amount, position.currency)} "
                     f"({_number(position.quantity)} acciones, importes brutos declarados).")
        sources.append(_source("dividend_record", records[-1].id, f"Dividendo {comp.ticker} · {records[-1].ex_date}", _link(comp)))
    if not lines:
        return _response([f"No hay dividendos guardados de tus posiciones para {today.year}. No he consultado el proveedor en directo."], [], "portfolio_dividends")
    head = f"Dividendos declarados guardados de tus posiciones abiertas en {today.year} (brutos, cantidad actual por acción declarada):"
    total = "Total: " + " · ".join(f"{_money(v, cur)}" for cur, v in sorted(totals.items())) + "."
    tail = [f"Sin dividendos guardados: {', '.join(without)}."] if without else []
    return _response([head, *lines, total, *tail], sources, "portfolio_dividends")


def _plan_answer(db: Session) -> ChatResponse:
    """Plan de inversion guardado y su desviacion actual; solo las cifras del plan, sin ordenes."""
    drift = InvestmentPlanService().drift_analysis(db)
    sources = [_source("investment_plan", "plan", "Plan de inversión", "/plan")]
    if not drift.get("plan_exists"):
        return _response(["No tienes un plan de inversión guardado."], [], "investment_plan")
    cur = PortfolioFXService().base_currency(db)
    lines = [f"Tu plan guardado marca una aportación de {_money(drift['next_contribution'], cur)} al mes."]
    if drift.get("suggestions_blocked"):
        lines.append("No calculo desviaciones ni importes: faltan tipos de cambio de alguna posición o saldo.")
        return _response(lines, sources, "investment_plan")
    below = [d for d in drift["deviations"] if d["current_pct"] < d["target_pct"] - d["band_pct"]]
    if below:
        lines.append("Objetivos por debajo de su banda según tu plan:")
        by_label = {x["label"]: x for x in drift["suggestions"] if x["direction"] == "buy"}
        for d in sorted(below, key=lambda d: d["deviation_pct"]):
            amount = by_label.get(d["label"], {}).get("amount_base")
            extra = f", hueco de {_money(amount, cur)} para llegar al objetivo" if amount is not None else ""
            lines.append(f"- {d['label']}: {_number(d['current_pct'])} % actual frente a {_number(d['target_pct'])} % objetivo{extra}.")
    elif drift["deviations"]:
        lines.append("Ningún objetivo del plan está por debajo de su banda.")
    else:
        lines.append("El plan no tiene objetivos de asignación guardados.")
    lines.append(f"Valor de la cartera usado: {_money(drift['portfolio_value_base'], cur)}. Son las cifras de tu plan, no una orden ni una recomendación nueva.")
    return _response(lines, sources, "investment_plan")


def _pct(value) -> str:
    return _number(float(value) * 100) + " %"


def _thesis_valuation_answer(db: Session, question: str, tenant: int) -> ChatResponse | None:
    """Margen y escenarios de la tesis PUBLICADA de una empresa; solo lo guardado en la tesis."""
    company = _company_in_question(db, question)
    if company is None:
        return None
    published = db.scalar(select(ThesisVersion).where(
        ThesisVersion.tenant_id == tenant, ThesisVersion.company_id == company.id, ThesisVersion.status == "published",
    ).order_by(ThesisVersion.version.desc()).limit(1))
    if published is None:
        latest = db.scalar(select(ThesisVersion).where(
            ThesisVersion.tenant_id == tenant, ThesisVersion.company_id == company.id,
        ).order_by(ThesisVersion.version.desc()).limit(1))
        if latest is None:
            return _response([f"No hay ninguna tesis guardada de {company.ticker}."], [], "thesis_valuation")
        return _response([f"{company.ticker} solo tiene una versión no publicada (v{latest.version}, {latest.status}); no la uso para dar el margen de seguridad. Publica la tesis para ver el margen."],
                         [_source("thesis_version", latest.id, f"Tesis {company.ticker} v{latest.version}", _link(company, "thesis"))], "thesis_valuation")
    ccy = company.currency
    lines = [f"**Tesis de {company.ticker} · v{published.version} (publicada)**"]
    if published.margin_of_safety is None:
        lines.append("Margen de seguridad: pendiente en la tesis.")
    else:
        lines.append(f"Margen de seguridad de la tesis: {_pct(published.margin_of_safety)}.")
    parts = [f"{label} {_money(value, ccy)}" for label, value in (
        ("bajista", published.bear_value), ("base", published.base_value), ("alcista", published.bull_value),
        ("esperado", published.expected_value)) if value is not None]
    if parts:
        lines.append("Valores de la tesis: " + ", ".join(parts) + ".")
    if published.current_price is not None:
        lines.append(f"Precio usado al generar la tesis: {_money(published.current_price, ccy)} (no es la cotización actual).")
    return _response(lines, [_source("thesis_version", published.id, f"Tesis {company.ticker} v{published.version}", _link(company, "thesis"))], "thesis_valuation")


def dividend_ticker_without_records(db: Session, question: str) -> str | None:
    """Ticker nombrado en una pregunta de dividendos sin ningun DividendRecord del tenant.

    El chat lo sincroniza bajo demanda (proveedor gratuito) antes de responder, en
    vez de decir «no tengo» de una empresa que nunca estuvo en cartera ni watchlist.
    """
    tenant = db.info.get("tenant_id")
    if type(tenant) is not int or tenant <= 0:
        return None
    if not re.search(r"(?i)\bdividend\w*", question):
        return None
    if re.search(r"(?i)\bmi\s+cartera\b|\bmis\s+(?:posiciones|acciones|empresas)\b|\bcobrar\w*\b", question):
        return None
    if re.search(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b", question):
        return None
    company = _company_in_question(db, question)
    if company is None:
        return None
    has_records = db.scalar(select(DividendRecord.id).where(
        DividendRecord.company_id == company.id, DividendRecord.tenant_id == tenant,
    ).limit(1))
    return None if has_records is not None else company.ticker


def answer_data_question(db: Session, question: str) -> ChatResponse | None:
    """None means this tool does not own the question; never guess user intent."""
    tenant = db.info.get("tenant_id")
    if type(tenant) is not int or tenant <= 0:
        return None
    news = bool(re.search(r"(?i)\bnoticias?\b", question)) and bool(re.search(r"(?i)\bmis\s+(?:empresas|acciones|posiciones)\b|\bmi\s+cartera\b", question))
    theses = bool(re.search(r"(?i)\btesis\b", question)) and bool(re.search(r"(?i)\b(?:tengo|mis|activas|vigentes)\b", question))
    comparison = bool(re.search(r"(?i)\bcompara\w*\b", question))
    valuation = bool(re.search(r"(?i)\b(?:precio|PER|cotiza\w*)\b", question)) and not re.search(r"(?i)\b(?:medio|coste|peso|posici[oó]n|tengo)\b", question)
    plan = bool(re.search(r"(?i)\b(?:mi|el|tu)\s+plan\b|\bplan\s+de\s+(?:inversi[oó]n|aportaci\w+)", question))
    if plan and not re.search(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b", question):
        return _plan_answer(db)
    thesis_valuation = bool(re.search(r"(?i)\btesis\b", question)) and bool(
        re.search(r"(?i)\b(?:margen\s+de\s+seguridad|valor\s+esperado|escenarios?|valor\s+objetivo|precio\s+objetivo)\b", question))
    if thesis_valuation and not re.search(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b", question):
        answer = _thesis_valuation_answer(db, question, tenant)
        if answer is not None:
            return answer
    dividends = bool(re.search(r"(?i)\bdividend\w*|\bcobrar\w*", question))
    if not (news or theses or comparison or valuation or dividends):
        return None
    if re.search(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b", question):
        return None
    if dividends and not (news or theses or comparison or valuation):
        return _dividend_answer(db, question, tenant)
    if not (news or theses or comparison or valuation):
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
