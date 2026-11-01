"""Ficha de una empresa en el chat, en inglés (Ajustes → Idioma = English).

Misma respuesta determinista que `_natural_company_answer` (precio, cifras
guardadas, tesis, notas, noticias, lo que falta), con el texto en inglés y los
números en formato en-US. Solo se usa con el inglés elegido; el castellano no
pasa por aquí.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.models.entities import Claim, Company, FinancialFact, NewsEvent, ThesisVersion
from app.services.thesis_publication_gate import withheld_reason_en

METRIC_LABELS_EN = {
    "revenue": "revenue",
    "free_cash_flow": "free cash flow",
    "operating_cash_flow": "operating cash flow",
    "net_income": "net income",
    "net_debt": "net debt",
    "cash_and_equivalents": "cash and equivalents",
    "total_debt": "total debt",
    "shares_diluted": "diluted shares",
    "market_cap": "market cap",
}

_THESIS_STATUS_EN = {
    "draft": "draft",
    "final": "final",
    "published": "published",
    "approved": "approved",
    "changes_requested": "changes requested",
    "draft_failed_audit": "draft (audit not passed)",
    "active": "active",
    "review": "in review",
    "archived": "archived",
    "stale": "out of date",
    "insufficient_data": "insufficient data",
}
_THESIS_RATING_EN = {
    "buy": "buy", "overweight": "overweight", "outperform": "outperform", "accumulate": "accumulate",
    "add": "add", "hold": "hold", "sell": "sell", "underweight": "underweight",
    "underperform": "underperform", "exit": "exit", "watch": "watch", "reduce": "reduce",
    "insufficient_data": "insufficient data",
}

_METRIC_KEYWORDS_EN = (
    (r"revenue|sales|turnover", ("revenue",)),
    (r"net income|earnings|profit", ("net_income",)),
    (r"cash flow|\bfcf\b", ("free_cash_flow", "operating_cash_flow")),
    (r"\bdebt\b", ("net_debt", "total_debt")),
    (r"\bcash\b(?! flow)|liquidity", ("cash_and_equivalents",)),
    (r"diluted shares|share count|shares outstanding", ("shares_diluted",)),
    (r"market cap|capitali[sz]ation", ("market_cap",)),
)

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _to_float(value: Decimal | int | float | None) -> float | None:
    return None if value is None else float(value)


def _number(number: float, digits: int = 2) -> str:
    """1,234,567.89 (en-US), sin ceros sobrantes: 4.4, 300."""
    return f"{number:,.{digits}f}".rstrip("0").rstrip(".")


def fmt_value_en(value: float | None, unit: str | None) -> str:
    """-71.5 million USD / 1.14 billion USD / 300 shares."""
    if value is None:
        return "no data"
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if unit == "shares":
        suffix = " shares"
    elif unit and unit != "decimal":
        suffix = f" {unit}"
    else:
        suffix = ""
    if magnitude >= 1e9:
        rendered = f"{_number(magnitude / 1e9)} billion"
    elif magnitude >= 1e6:
        rendered = f"{_number(magnitude / 1e6)} million"
    elif magnitude >= 1e3:
        rendered = f"{_number(magnitude / 1e3)} thousand"
    else:
        rendered = _number(magnitude)
    return f"{sign}{rendered}{suffix}"


def fmt_period_en(period: str | None, fiscal_year: int | None = None, fiscal_quarter: str | None = None) -> str:
    """'2025-12-31:FY' -> 'FY 2025'; '2025-09-30:Q3' -> 'Q3 2025'."""
    text = (period or "").strip()
    match = re.match(r"^(\d{4})-\d{2}-\d{2}:(FY|Q[1-4])$", text)
    if match:
        year, quarter = match.groups()
        return f"FY {year}" if quarter == "FY" else f"{quarter} {year}"
    if fiscal_year:
        if fiscal_quarter and fiscal_quarter != "FY":
            return f"{fiscal_quarter} {fiscal_year}"
        return f"FY {fiscal_year}"
    return text or "undated period"


def fmt_date_en(iso_date: str | None) -> str:
    """'2026-10-16' -> 'Oct 16, 2026'."""
    text = (iso_date or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$", text)
    if not match:
        return text or "undated"
    year, month, day = match.groups()
    if not 1 <= int(month) <= 12:
        return text
    return f"{_MONTHS_EN[int(month) - 1]} {int(day)}, {year}"


def price_display_en(value: Decimal | int | float, currency: str | None) -> str:
    magnitude = abs(Decimal(str(value)))
    digits = max(2, -magnitude.adjusted() + 3) if 0 < magnitude < 1 else 2
    text = f"{value:,.{digits}f}"
    if currency == "USD":
        return f"${text}"
    if not currency or not currency.strip():
        return f"{text} (currency not declared)"
    return f"{text} {'€' if currency == 'EUR' else currency}"


def price_line_en(ticker: str, value, currency: str | None, *, adjusted: bool, day: str, source: str) -> str:
    kind = "adjusted close" if adjusted else "spot"
    return f"{ticker} trades at {price_display_en(value, currency)} ({kind} on {fmt_date_en(day)}, source {source})."


def primary_sources_hint_en(company: Company, *, sec: bool) -> str:
    if sec:
        return "ingest its primary sources (SEC/FMP)"
    market = (company.exchange or "").strip() or "its market"
    return (
        f"the SEC doesn't cover {market}, so its sources are FMP and the company's own annual "
        "reports: ingest them from its page"
    )


def question_metrics_en(question: str) -> set[str]:
    text = (question or "").lower()
    found: set[str] = set()
    for pattern, metrics in _METRIC_KEYWORDS_EN:
        if re.search(pattern, text):
            found.update(metrics)
    return found


def _fact_text(fact: FinancialFact) -> str:
    return (
        f"{fmt_value_en(_to_float(fact.value), fact.unit)} "
        f"({fmt_period_en(fact.period, fact.fiscal_year, fact.fiscal_quarter)}, {fact.source_type or 'stored source'})"
    )


def news_headline_line_en(news: list[NewsEvent]) -> str | None:
    dated = sorted((event for event in news if event.date), key=lambda event: event.date, reverse=True)
    seen: set[str] = set()
    headlines = []
    for event in dated or news:
        title = " ".join((event.title or "").split())
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        headlines.append(f"'{title}' ({fmt_date_en(event.date.isoformat())})" if event.date else f"'{title}'")
        if len(headlines) == 2:
            break
    if not headlines:
        return None
    return "Latest saved news: " + "; ".join(headlines) + "."


def _short(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rsplit(" ", 1)[0] + "…"


def _lead_en(
    question: str, *, ticker: str, facts: list[FinancialFact], thesis: ThesisVersion | None,
    thesis_line: str | None, news: list[NewsEvent], claims: list[Claim], contradiction_claims: list[Claim],
    price_line: str | None, focus_metrics: set[str], thesis_withheld: str | None,
) -> str | None:
    text = (question or "").lower()
    if not text.strip():
        return None
    if re.search(r"\brisks?\b|\brisky\b", text):
        bits = []
        if contradiction_claims:
            bits.append(f"{len(contradiction_claims)} contradicted or outdated claims")
        pending = sum(1 for c in claims if c.status == "unverified")
        if pending:
            bits.append(f"{pending} claims pending verification")
        if thesis is not None and not thesis_withheld and thesis.valuation_risk_score:
            bits.append(f"valuation risk {thesis.valuation_risk_score}/100 in thesis v{thesis.version}")
        if bits:
            return f"On the risks of {ticker}, what's saved points to: " + "; ".join(bits) + "."
        return f"I have no documented risks saved for {ticker}."
    if re.search(r"thesis|valuation|intrinsic value|fair value|expected value|margin of safety|rating|"
                 r"undervalued|overvalued", text):
        if thesis is None or thesis_line is None:
            return f"I don't have any saved thesis for {ticker}."
        if thesis_withheld:
            return thesis_line
        summary = " ".join((thesis.executive_summary or "").split())
        draft_note = (
            " It's a draft: any value range shown is indicative, not a final intrinsic value."
            if (thesis.status or "").strip() != "published" else ""
        )
        return thesis_line + draft_note + (f" Summary: {_short(summary, 320)}" if summary else "")
    if focus_metrics:
        wanted = [f for f in facts if f.metric in focus_metrics]
        if not wanted:
            labels = ", ".join(sorted(METRIC_LABELS_EN.get(m, m) for m in focus_metrics))
            return f"I don't have that figure saved for {ticker} ({labels})."
        f = wanted[0]
        return f"{ticker} {METRIC_LABELS_EN.get(f.metric, f.metric)}: {_fact_text(f)}."
    if re.search(r"\bprice\b|\bquote\b|trading at|trades at", text) and price_line:
        return price_line
    if re.search(r"\bnews\b|headlines?", text):
        if not news:
            return f"I have no saved news for {ticker}."
        line = news_headline_line_en(news)
        if line is not None:
            return line
    return None


def natural_company_answer_en(
    *, company: Company, facts: list[FinancialFact], thesis: ThesisVersion | None, news: list[NewsEvent],
    missing_metrics: list[str], claims: list[Claim], contradiction_claims: list[Claim], price_line: str | None,
    memory_notes: list[str] | None, market_cap_fact: FinancialFact | None, question: str,
    thesis_withheld: str | None, sec: bool,
) -> str:
    parts: list[str] = []
    thesis_line: str | None = None
    if price_line:
        parts.append(price_line)
    if market_cap_fact is not None and market_cap_fact.value is not None:
        parts.append(f"Market cap: {_fact_text(market_cap_fact)}.")
    focus = question_metrics_en(question)
    if focus:
        facts = sorted(facts, key=lambda f: f.metric not in focus)
    if facts:
        rendered = "; ".join(f"{METRIC_LABELS_EN.get(f.metric, f.metric)} {_fact_text(f)}" for f in facts[:5])
        parts.append(f"Stored data: {rendered}.")
    else:
        parts.append(
            f"I don't have reliable stored financial facts for {company.ticker} yet; "
            f"{primary_sources_hint_en(company, sec=sec)} and I'll answer with figures."
        )
    if thesis and thesis_withheld:
        stamp = thesis.created_at.date().isoformat() if thesis.created_at else "unverified date"
        thesis_line = f"Archived thesis v{thesis.version} ({stamp}): {withheld_reason_en(thesis_withheld)}"
        parts.append(thesis_line)
    elif thesis:
        details = []
        status = _THESIS_STATUS_EN.get((thesis.status or "").strip())
        rating = _THESIS_RATING_EN.get((thesis.rating or "").strip())
        if status:
            details.append(f"status {status}")
        if rating:
            details.append(f"rating {rating}")
        thesis_line = f"I have thesis v{thesis.version} saved" + (f" ({', '.join(details)})." if details else ".")
        parts.append(thesis_line)
    seen_notes: set[str] = set()
    for content in (memory_notes or [])[:3]:
        note = _short(content, 180)
        key = " ".join(note.lower().split())
        if key in seen_notes:
            continue
        seen_notes.add(key)
        parts.append(f"From your saved notes: '{note}'.")
    line = news_headline_line_en(news) if news else None
    if line is not None:
        parts.append(line)
    if contradiction_claims:
        parts.append(f"There are {len(contradiction_claims)} contradicted or outdated claims worth reviewing.")
    elif any(claim.status == "unverified" for claim in claims):
        parts.append("There are claims pending verification.")
    if missing_metrics:
        labels = ", ".join(METRIC_LABELS_EN.get(m, m) for m in missing_metrics)
        parts.append(f"Still missing stored data for: {labels}.")
    lead = _lead_en(
        question, ticker=company.ticker, facts=facts, thesis=thesis, thesis_line=thesis_line, news=news,
        claims=claims, contradiction_claims=contradiction_claims, price_line=price_line, focus_metrics=focus,
        thesis_withheld=thesis_withheld,
    )
    if lead:
        parts = [lead, *[p for p in parts if not lead.startswith(p)]]
    if re.search(r"compar|\bvs\.?\b|versus|against", (question or "").lower()):
        parts.insert(
            1 if lead else 0,
            f"I can't compare two companies in one answer: I'm answering only about {company.ticker}. "
            "Ask about the other company separately.",
        )
    return "\n\n".join(parts)


def thesis_section_text_en(ticker: str, thesis: ThesisVersion | None, withheld_reason: str | None) -> str:
    """Línea de tesis del panel plegado `sections`, en inglés (mismos datos que la castellana)."""
    if thesis is None:
        return f"No thesis stored yet for {ticker}."
    if withheld_reason:
        stamp = thesis.created_at.date().isoformat() if thesis.created_at else "unverified date"
        return (
            f"Archived thesis v{thesis.version} ({stamp}): {withheld_reason_en(withheld_reason)} "
            f"[thesis_version:{thesis.id}]"
        )
    return (
        f"Thesis {ticker} v{thesis.version}: `{thesis.status}` with rating `{thesis.rating}`. "
        f"Expected value={_to_float(thesis.expected_value)} vs current price={_to_float(thesis.current_price)}. "
        f"[thesis_version:{thesis.id}]"
    )
