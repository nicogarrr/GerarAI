"""Read-only, tenant-scoped answers to concrete Cerebro data questions.

No provider calls, ingestion, writes or invented current quotes. A stored price
is always dated. Ratios reuse the screener's audited annual EPS/currency rules.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import (
    Company,
    DividendRecord,
    InsiderTransaction,
    MarketPrice,
    NewsEvent,
    Position,
    ThesisVersion,
)
from app.schemas import ChatResponse
from app.services.investment_plan_service import InvestmentPlanService
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.screener_fundamentals import load_screener_ratios
from app.valuation.margin_convention import historical_margin_note


def _number(value) -> str:
    return f"{float(value):,.2f}".replace(",", "\x07").replace(".", ",").replace("\x07", ".")


def _money(value, currency) -> str:
    """USD en formato en-US ($120.50); el resto de divisas, es-ES con su código."""
    if currency == "USD":
        return f"${float(value):,.2f}"
    return f"{_number(value)} {currency or ''}".strip()


from app.services.company_catalog import all_companies
from app.services.display_es import fecha_es as _fecha_es
from app.services.display_es import source_label as _source_label
from app.services.dividend_records import records_in_position_currency, resolve_yahoo_events
from app.services.position_value import position_base_value


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
                     f"({_fecha_es(price.date)}, {_source_label(price.source)}). No es una cotización en directo.")
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
    for company in all_companies(db):
        core = _squash(" ".join(w for w in re.split(r"[\s,.]+", company.name.lower()) if w and w not in _NAME_NOISE))
        by_ticker = re.search(rf"(?<![A-Za-z0-9]){re.escape(company.ticker)}(?![A-Za-z0-9])", question) is not None
        if by_ticker or (len(core) >= 4 and core in squashed):
            found[company.id] = company
    return next(iter(found.values())) if len(found) == 1 else None


def _dividend_line(company: Company, record: DividendRecord) -> str:
    pay = f", pago {_fecha_es(record.pay_date)}" if record.pay_date else ""
    return (f"{company.ticker}: {_money(record.amount, record.currency)} por acción, "
            f"ex-dividendo {_fecha_es(record.ex_date)}{pay} ({_source_label(record.source)}).")


_YEAR_IN_QUESTION_RE = re.compile(r"\b(20\d{2})\b")
_LAST_YEAR_IN_QUESTION_RE = re.compile(r"(?i)\b(?:a[nñ]o|ejercicio)\s+pasado\b")


def _year_in_question(question: str, today: date) -> int:
    """Año que pide la pregunta («2025», «el año pasado»); si no, el actual."""
    explicit = _YEAR_IN_QUESTION_RE.search(question or "")
    if explicit:
        return int(explicit.group(1))
    if _LAST_YEAR_IN_QUESTION_RE.search(question or ""):
        return today.year - 1
    return today.year


def _dividend_answer(db: Session, question: str, tenant: int) -> ChatResponse | None:
    """Dividendos GUARDADOS (declarados por el proveedor); nada proyectado ni inventado."""
    today = local_today()  # año/día del usuario (Madrid), no el UTC del servidor
    # «¿Cuál es mi rentabilidad por dividendo?» / «¿cuáles son mis dividendos?»
    # también son de la cartera (antes, la rentabilidad sobre coste o nada).
    portfolio = bool(re.search(
        r"(?i)\bmi\s+cartera\b|\bmis\s+(?:posiciones|acciones|empresas|dividendos)\b|\bcobr\w*\b"
        r"|\bmi\s+(?:rentabilidad|rendimiento)\s+(?:por|de|del)\s+dividendos?\b",
        question,
    ))
    named = _company_in_question(db, question)
    company = None if portfolio else named
    if company is not None:
        kept, uncertain = resolve_yahoo_events(db.scalars(select(DividendRecord).where(
            DividendRecord.company_id == company.id, DividendRecord.tenant_id == tenant,
        ).order_by(DividendRecord.ex_date.desc()).limit(40)).all())
        records = sorted(kept, key=lambda r: r.ex_date, reverse=True)
        sources = [_source("dividend_record", r.id, f"Dividendo {company.ticker} · {r.ex_date}", _link(company)) for r in records[:1]]
        upcoming = sorted((r for r in records if r.ex_date >= today), key=lambda r: r.ex_date)
        past = [r for r in records if r.ex_date < today]
        if not records and not uncertain:
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
        for event in uncertain:
            lines.append(
                f"Importe incierto el {_fecha_es(event.ex_date)}: "
                f"{', '.join(str(a.normalize()) for a in event.amounts)} {event.currency}; no lo doy por válido.")
        return _response(lines, sources, "company_dividends")
    if not portfolio:
        return None
    rows = db.execute(select(Position, Company).join(Company, Company.id == Position.company_id).where(
        Position.tenant_id == tenant, Position.quantity > 0)).all()
    if not rows:
        return _response(["No hay posiciones abiertas en tu cartera."], [], "portfolio_dividends")
    # «¿Cuántos dividendos he cobrado de MSFT?»: solo esa posición (antes,
    # toda la cartera).
    if named is not None:
        rows = [row for row in rows if row[1].id == named.id]
        if not rows:
            return _response([f"No tienes {named.ticker} en tu cartera ahora mismo; los dividendos de la cartera "
                              "se calculan con las acciones que tienes hoy."], [], "portfolio_dividends")
    lines, sources, totals, without, uncertain_tickers = [], [], {}, [], []
    # Lote anti N+1: una consulta de dividendos del año para TODAS las
    # posiciones (misma ventana y orden por ex_date), agrupada por empresa.
    # «¿Cuántos dividendos he cobrado en 2025?» / «el año pasado»: antes
    # respondía siempre con el año en curso («… para 2026»).
    year = _year_in_question(question, today)
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    company_ids = sorted({comp.id for _, comp in rows})
    dividends_by_company: dict[int, list[DividendRecord]] = {cid: [] for cid in company_ids}
    if company_ids:
        for record in db.scalars(select(DividendRecord).where(
            DividendRecord.company_id.in_(company_ids), DividendRecord.tenant_id == tenant,
            DividendRecord.ex_date >= year_start, DividendRecord.ex_date <= year_end,
        ).order_by(DividendRecord.company_id, DividendRecord.ex_date)).all():
            dividends_by_company[record.company_id].append(record)
    for position, comp in sorted(rows, key=lambda r: r[1].ticker):
        kept, uncertain = resolve_yahoo_events(dividends_by_company[comp.id])
        if uncertain:
            uncertain_tickers.append(comp.ticker)
            continue
        # GBX (peniques) frente a GBp/GBP de la posicion: misma moneda, sin FX.
        records = records_in_position_currency(kept, position.currency)
        if not records:
            without.append(comp.ticker)
            continue
        amount = sum((r.amount for r in records), Decimal("0")) * Decimal(str(position.quantity))
        totals[position.currency] = totals.get(position.currency, Decimal("0")) + amount
        lines.append(f"- {comp.ticker}: {len(records)} pago(s) en {year}, {_money(amount, position.currency)} "
                     f"({_number(position.quantity)} acciones, importes brutos del proveedor; los de Yahoo van ajustados por splits).")
        sources.append(_source("dividend_record", records[-1].id, f"Dividendo {comp.ticker} · {records[-1].ex_date}", _link(comp)))
    if not lines and not uncertain_tickers:
        return _response([f"No hay dividendos guardados de tus posiciones para {year}. No he consultado el proveedor en directo."], [], "portfolio_dividends")
    head = f"Dividendos declarados guardados de tus posiciones abiertas en {year} (brutos, cantidad actual por acción según el proveedor):"
    total = "Total: " + " · ".join(f"{_money(v, cur)}" for cur, v in sorted(totals.items())) + "."
    tail = [f"Sin dividendos guardados: {', '.join(without)}."] if without else []
    if uncertain_tickers:
        tail.append(f"Excluidos del total por importe incierto: {', '.join(uncertain_tickers)}.")
    return _response([head, *lines, total, *tail], sources, "portfolio_dividends")


def _company_news_answer(db: Session, company: Company, tenant: int) -> ChatResponse:
    """Noticias GUARDADAS de una empresa concreta (mencionada en la pregunta).

    Antes, "que noticias hay de ASTS y como afectan a mi cartera" caia en el
    volcado de cartera por llevar "mi cartera": la respuesta eran titulares de
    OTRAS posiciones (el spam 13F de AMZN) y cero de ASTS. Con empresa nombrada
    la respuesta se acota a ella: solo noticias que la citan de verdad, sin el
    ticker pegado del feed y sin duplicados. Si la tiene en cartera se declara
    la posicion (es lo que "como me afecta" permite decir con datos guardados,
    sin inventar un impacto por noticia).
    """
    from app.services.ticker_news_lane import _cites_company

    rows = db.scalars(select(NewsEvent).where(
        NewsEvent.tenant_id == tenant, NewsEvent.company_id == company.id,
    ).order_by(NewsEvent.date.desc(), NewsEvent.id.desc()).limit(60)).all()
    lines, sources, seen = [], [], set()
    for event in rows:
        if not _cites_company(company, event.title or "", event.summary or ""):
            continue
        title = re.sub(
            rf"^\s*{re.escape(company.ticker)}\s*[:\-\u2013]?\s+",
            "", event.title or "", count=1, flags=re.IGNORECASE,
        ).strip()
        if not title:
            continue
        key = " ".join(title.lower().split())
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- '{title}' ({_fecha_es(event.date.date())}, {_source_label(event.source)}).")
        sources.append(_source("news_event", event.id, f"{company.ticker}: {title}", event.url or _link(company, "news")))
        if len(lines) == 6:
            break
    holding_lines: list[str] = []
    position = db.scalars(select(Position).where(
        Position.tenant_id == tenant, Position.company_id == company.id, Position.quantity > 0,
    ).limit(1)).first()
    if position is not None:
        total = sum(
            position_base_value(row) or Decimal("0") for row in db.scalars(select(Position).where(
                Position.tenant_id == tenant, Position.quantity > 0)).all()
        )
        own = position_base_value(position)
        weight = f", el {_number(own / total * 100)} % de tu cartera" if own is not None and total > 0 else ""
        holding_lines.append(
            f"Tienes {_number(position.quantity)} acciones de {company.ticker} en cartera{weight}. "
            "No calculo el impacto de cada noticia: eso pediria un analisis nuevo."
        )
    if not lines:
        head = (f"No hay noticias guardadas de {company.ticker} que citen de verdad a la empresa. "
                "No he consultado noticias en directo.")
        return _response([head, *holding_lines], [], "company_news")
    return _response(
        [f"Ultimas noticias guardadas de {company.ticker} · {company.name}:", *lines, *holding_lines],
        sources, "company_news",
    )


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
        lines.append(f"Margen de seguridad archivado de la tesis: {_pct(published.margin_of_safety)}. "
                     + historical_margin_note(published.valuation_basis))
    parts = [f"{label} {_money(value, ccy)}" for label, value in (
        ("bajista", published.bear_value), ("base", published.base_value), ("alcista", published.bull_value),
        ("esperado", published.expected_value)) if value is not None]
    if parts:
        lines.append("Valores de la tesis: " + ", ".join(parts) + ".")
    if published.current_price is not None:
        lines.append(f"Precio usado al generar la tesis: {_money(published.current_price, ccy)} (no es la cotización actual).")
    return _response(lines, [_source("thesis_version", published.id, f"Tesis {company.ticker} v{published.version}", _link(company, "thesis"))], "thesis_valuation")


def _insider_tx_line(tx: InsiderTransaction, ticker: str) -> str:
    side = "compró" if tx.code == "P" else "vendió"
    parts = [f"- {ticker}: {tx.insider or 'Insider'} {side}"]
    if tx.shares is not None:
        parts.append(f"{_number(tx.shares)} acciones")
    if tx.value is not None:
        parts.append(f"por {_money(tx.value, 'USD')}")
    when = _fecha_es(tx.tx_date) if tx.tx_date else "fecha no declarada"
    return " ".join(parts) + f" ({when}, SEC Form 4)."


def _recent_insider_txs(db: Session, tenant: int, ticker: str, limit: int) -> list[InsiderTransaction]:
    return list(db.scalars(select(InsiderTransaction).where(
        InsiderTransaction.tenant_id == tenant,
        InsiderTransaction.issuer_ticker == ticker,
        InsiderTransaction.code.in_(["P", "S"]),
    ).order_by(InsiderTransaction.tx_date.desc(), InsiderTransaction.id.desc()).limit(limit)).all())


def _insider_source(tx: InsiderTransaction, ticker: str) -> dict:
    return _source("insider_transaction", tx.id, f"Form 4 {ticker} · {tx.tx_date}",
                   tx.source_url or f"/insider?ticker={ticker}")


def _insider_answer(db: Session, question: str, tenant: int) -> ChatResponse | None:
    """Operaciones insider GUARDADAS (Form 4 SEC): compras/ventas P/S con fecha y fuente; nada en directo."""
    portfolio = bool(re.search(r"(?i)\bmi\s+cartera\b|\bmis\s+(?:posiciones|acciones|empresas)\b", question))
    company = None if portfolio else _company_in_question(db, question)
    if company is not None:
        txs = _recent_insider_txs(db, tenant, company.ticker, 5)
        if not txs:
            return _response(
                [f"No tengo operaciones insider guardadas de {company.ticker}. No he consultado la SEC en directo."],
                [], "company_insider")
        lines = [f"**Operaciones insider guardadas de {company.ticker} · {company.name}** "
                 "(compras/ventas código P/S del Form 4; no es el historial completo):"]
        lines.extend(_insider_tx_line(tx, company.ticker) for tx in txs)
        return _response(lines, [_insider_source(tx, company.ticker) for tx in txs], "company_insider")
    if not portfolio:
        return None
    rows = db.execute(select(Position, Company).join(Company, Company.id == Position.company_id).where(
        Position.tenant_id == tenant, Position.quantity > 0)).all()
    if not rows:
        return _response(["No hay posiciones abiertas en tu cartera."], [], "portfolio_insider")
    lines, sources, without = [], [], []
    for _position, comp in sorted(rows, key=lambda r: r[1].ticker):
        txs = _recent_insider_txs(db, tenant, comp.ticker, 3)
        if not txs:
            without.append(comp.ticker)
            continue
        lines.append(f"**{comp.ticker}**")
        lines.extend(_insider_tx_line(tx, comp.ticker) for tx in txs)
        sources.extend(_insider_source(tx, comp.ticker) for tx in txs)
    if not lines:
        return _response(
            ["No tengo operaciones insider guardadas de tus posiciones. No he consultado la SEC en directo."],
            [], "portfolio_insider")
    head = "Operaciones insider guardadas de tus posiciones abiertas (últimas compras/ventas código P/S del Form 4 SEC):"
    tail = [f"Sin operaciones insider guardadas: {', '.join(without)}."] if without else []
    return _response([head, *lines, *tail], sources, "portfolio_insider")


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
    # Avisos, riesgo de cartera (panel + histórico) y diario de decisiones.
    from app.services.brain_context_tools import answer_context_question

    context_answer = answer_context_question(
        db, question, tenant, lambda: _company_in_question(db, question)
    )
    if context_answer is not None:
        return context_answer
    news = bool(re.search(r"(?i)\bnoticias?\b", question)) and bool(re.search(r"(?i)\bmis\s+(?:empresas|acciones|posiciones)\b|\bmi\s+cartera\b", question))
    theses = bool(re.search(r"(?i)\btesis\b", question)) and bool(re.search(r"(?i)\b(?:tengo|mis|activas|vigentes)\b", question))
    comparison = bool(re.search(r"(?i)\bcompara\w*\b", question))
    valuation = bool(re.search(r"(?i)\b(?:precio|PER|cotiza\w*)\b|\ba\s+cu[aá]nto\s+est[aá]n?\b", question)) and not re.search(r"(?i)\b(?:medio|coste|peso|posici[oó]n|tengo|compr[eé]|pagu[eé])\b|\bprecio\s+de\s+compra\b", question)
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
    insider = bool(re.search(r"(?i)\binsiders?\b", question))
    if not (news or theses or comparison or valuation or dividends or insider):
        return None
    if re.search(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b", question):
        return None
    if insider and not (news or theses or comparison or valuation or dividends):
        return _insider_answer(db, question, tenant)
    if dividends and not (news or theses or comparison or valuation):
        return _dividend_answer(db, question, tenant)
    if not (news or theses or comparison or valuation):
        return None
    if news:
        mentioned = _company_in_question(db, question)
        if mentioned is not None:
            return _company_news_answer(db, mentioned, tenant)
        from app.services.ticker_news_lane import _cites_company

        company_ids = select(Position.company_id).where(Position.tenant_id == tenant, Position.quantity > 0)
        rows = db.execute(select(NewsEvent, Company).join(Company, Company.id == NewsEvent.company_id).where(
            NewsEvent.tenant_id == tenant, NewsEvent.company_id.in_(company_ids),
        ).order_by(NewsEvent.date.desc(), NewsEvent.id.desc()).limit(40)).all()
        lines, sources, seen = [], [], set()
        kept_signatures: list[tuple[set[str], datetime]] = []
        from app.services.news_story_cluster import event_signature, same_story
        for event, company in rows:
            # El feed liga la noticia al ticker aunque trate de otra empresa
            # (un articulo de AEP etiquetado GOOGL): se descarta lo que no la
            # cita de verdad. Misma regla que la ruta de empresa.
            if not _cites_company(company, event.title or "", event.summary or ""):
                continue
            # El titular del feed ya trae el ticker pegado delante
            # ("MSFT The Bet Behind..."): no repetirlo tras "MSFT:".
            title = re.sub(
                rf"^\s*{re.escape(company.ticker)}\s*[:\-–]?\s+",
                "", event.title or "", count=1, flags=re.IGNORECASE,
            ).strip()
            if not title:
                continue
            key = " ".join(title.lower().split())
            if key in seen:
                continue
            # Dedup por historia, no por titular literal (la misma noticia
            # llega con titular solo y con titular+entrada pegada: la
            # coincidencia exacta no las casaba y salía dos veces).
            signature = event_signature(event, company)
            if any(same_story(signature, kept_sig, event.date, kept_date) for kept_sig, kept_date in kept_signatures):
                continue
            seen.add(key)
            kept_signatures.append((signature, event.date))
            lines.append(f"- {company.ticker}: '{title}' ({_fecha_es(event.date.date())}, {_source_label(event.source)}).")
            sources.append(_source("news_event", event.id, f"{company.ticker}: {title}", event.url or _link(company, "news")))
            if len(lines) == 6:
                break
        return _response(["Últimas noticias guardadas de tus posiciones abiertas (titulares en su idioma original):", *lines] if lines else ["No hay noticias guardadas de tus posiciones abiertas que citen de verdad a esas empresas. No he consultado noticias en directo."], sources, "portfolio_news")
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
    tokens = re.findall(r"\b[A-Z][A-Z0-9.-]{1,14}\b", question)
    companies = list(db.scalars(select(Company).where(Company.ticker.in_(set(tokens)))).all()) if tokens else []
    # «PER de CB y UNH» / «precio de AAPL, MSFT y KKR»: varios tickers sin la
    # palabra «compara». Antes exigía exactamente uno, devolvía None y la
    # pregunta caía en el generador general sin fuentes («No puedo
    # responderte con fuentes», prueba real realqa-14). Se listan los datos
    # guardados de cada uno, en el orden en que los nombra el usuario.
    multi_valuation = valuation and not comparison and 2 <= len(companies) <= 4
    if (comparison and len(companies) < 2) or (not comparison and not multi_valuation and len(companies) != 1):
        return None
    order = {ticker: index for index, ticker in reversed(list(enumerate(tokens)))}
    ordered = (
        sorted(companies, key=lambda item: order.get(item.ticker, len(tokens)))
        if multi_valuation else sorted(companies, key=lambda item: item.ticker)
    )
    lines, sources = [], []
    for company in ordered[:4]:
        company_lines, company_sources = _company_data(db, company)
        lines.extend(company_lines)
        sources.extend(company_sources)
    if comparison:
        lines.append("Comparativa de los datos guardados de precio y PER; no basta para decidir qué empresa es mejor inversión.")
    if multi_valuation:
        return _response(lines, sources, "company_quotes")
    return _response(lines, sources, "company_comparison" if comparison else "company_quote")
