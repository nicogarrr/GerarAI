"""Herramientas de SOLO lectura del equipo de expertos.

Reglas: cada herramienta recibe únicamente el ``RunContext`` (tenant, usuario y
ticker los fija el servidor), filtra SIEMPRE por ``ctx.tenant_id`` y solo hace
SELECT (o llama a un servicio de cálculo que no escribe). Cada resultado lleva
su fuente (tabla, id, filing, fecha) para que una afirmación pueda citarlo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Company,
    Document,
    FinancialFact,
    NewsEvent,
    Position,
    RiskEvent,
    ThesisVersion,
)
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec

FACT_YEARS = 2
FACT_ROWS_MAX = 80
NEWS_DAYS = 90
NEWS_MAX = 8
_VALUATION_KEYS = (
    "model_type", "current_price", "bear_value", "base_value", "bull_value", "expected_value",
    "margin_of_safety", "publishable", "missing_inputs",
)


def _day(value: date | datetime | None) -> str:
    if value is None:
        return ""
    return (value.date() if isinstance(value, datetime) else value).isoformat()


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _app_path(ticker: str, view: str) -> str:
    """Pantalla de la app que enseña ese dato (enlace interno real, nunca inventado)."""
    return f"/research/{quote(ticker, safe='')}?view={view}"


def _company(db: Session, ctx: RunContext) -> Company | None:
    if not ctx.ticker:
        return None
    return db.scalars(select(Company).where(Company.ticker == ctx.ticker.strip().upper())).first()


def _filing_links(
    db: Session, company: Company, groups: dict[tuple, Any], accessions: dict[tuple, str]
) -> dict[tuple, str]:
    """URL del archivo SEC de cada grupo de cifras: la del documento guardado si
    es un archivo inmutable de la SEC; si no, el índice EDGAR por accession."""
    from app.services.document_visibility import is_immutable_archive_url
    from app.services.sec_filing_evidence import derive_index_url

    doc_ids = {key[3] for key in groups if isinstance(key[3], int)}
    urls: dict[int, str] = {}
    if doc_ids:
        urls = {
            doc_id: str(url)
            for doc_id, url in db.execute(select(Document.id, Document.source_url).where(Document.id.in_(doc_ids)))
            if url and is_immutable_archive_url(url)
        }
    cik = "".join(ch for ch in str(company.cik or "") if ch.isdigit())
    links: dict[tuple, str] = {}
    for key in groups:
        if isinstance(key[3], int) and key[3] in urls:
            links[key] = urls[key[3]]
        elif cik and int(cik) and key in accessions:
            links[key] = derive_index_url(cik, accessions[key])
    return links


def build_tools(db: Session, *, today: date | None = None) -> dict[str, ToolSpec]:
    """Herramientas ligadas a la sesión de ESTA petición (una por corrida)."""

    def financial_facts(ctx: RunContext) -> list[ToolOutput]:
        company = _company(db, ctx)
        if company is None:
            return []
        rows = db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.tenant_id == ctx.tenant_id,
                FinancialFact.company_id == company.id,
                FinancialFact.is_reported.is_(True),
            )
            .order_by(FinancialFact.fiscal_year.desc().nullslast(), FinancialFact.id.desc())
            .limit(FACT_ROWS_MAX)
        ).all()
        years = sorted({r.fiscal_year for r in rows if r.fiscal_year is not None}, reverse=True)[:FACT_YEARS]
        groups: dict[tuple, dict[str, Any]] = {}
        accessions: dict[tuple, str] = {}
        for row in rows:
            if row.fiscal_year not in years or row.value is None:
                continue
            key = (row.period, row.fiscal_year, row.source_type, row.source_id)
            group = groups.setdefault(key, {"values": {}, "units": {}})
            group["values"].setdefault(row.metric, float(row.value))
            group["units"].setdefault(row.metric, row.unit or "")
            if row.accession_number and key not in accessions:
                accessions[key] = row.accession_number
        links = _filing_links(db, company, groups, accessions)
        out: list[ToolOutput] = []
        for key, group in groups.items():
            period, fiscal_year, source_type, source_id = key
            source = {
                "table": "financial_facts",
                "filing": f"{source_type or '-'}:{source_id or '-'}",
                "period": str(period or ""),
                "date": str(fiscal_year or ""),
            }
            if key in links:
                # Enlace al filing de la SEC del que sale la cifra (se abre desde «Fuentes»).
                source.update({"source": "SEC EDGAR", "url": links[key]})
            out.append(ToolOutput(source=source, data={"ticker": company.ticker, **group}))
        return out

    def valuation_engine(ctx: RunContext) -> list[ToolOutput]:
        company = _company(db, ctx)
        if company is None:
            return []
        out: list[ToolOutput] = []
        from app.services.valuation_service import ValuationService

        try:
            result = ValuationService().value_company(db, company)
        except Exception:  # noqa: BLE001 - un motor caído no es evidencia
            result = None
        if isinstance(result, dict):
            data = {k: result.get(k) for k in _VALUATION_KEYS if result.get(k) is not None}
            if data:
                as_of = (result.get("trace") or {}).get("price_as_of")
                out.append(
                    ToolOutput(
                        source={"table": "valuation_engine", "date": str(as_of or ""),
                                "url": _app_path(company.ticker, "valoracion")},
                        data=data,
                    )
                )
        thesis = db.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.tenant_id == ctx.tenant_id, ThesisVersion.company_id == company.id)
            .order_by(ThesisVersion.version.desc())
        ).first()
        if thesis is not None:
            data = {
                k: _num(getattr(thesis, k))
                for k in ("current_price", "bear_value", "base_value", "bull_value", "expected_value", "margin_of_safety")
                if getattr(thesis, k, None) is not None
            }
            out.append(
                ToolOutput(
                    source={"table": "thesis_versions", "id": str(thesis.id), "version": str(thesis.version),
                            "date": _day(getattr(thesis, "created_at", None)),
                            "url": _app_path(company.ticker, "thesis")},
                    data={"rating": thesis.rating, **data},
                )
            )
        return out

    def risk_events(ctx: RunContext) -> list[ToolOutput]:
        company = _company(db, ctx)
        if company is None:
            return []
        rows = db.scalars(
            select(RiskEvent)
            .where(RiskEvent.tenant_id == ctx.tenant_id, RiskEvent.company_id == company.id)
            .order_by(RiskEvent.id.desc())
            .limit(10)
        ).all()
        return [
            ToolOutput(
                source={"table": "risk_events", "id": str(r.id), "date": _day(getattr(r, "created_at", None))},
                data={"severity": r.severity, "type": r.event_type, "message": r.message, "status": r.status,
                      "metric_value": _num(r.metric_value), "threshold": _num(r.threshold)},
            )
            for r in rows
        ]

    def _positions(ctx: RunContext) -> list[Position]:
        return list(db.scalars(select(Position).where(Position.tenant_id == ctx.tenant_id)).all())

    def portfolio_concentration(ctx: RunContext) -> ToolOutput | None:
        company = _company(db, ctx)
        positions = _positions(ctx)
        total = sum(_num(p.market_value_base) or 0.0 for p in positions)
        if company is None or total <= 0:
            return None
        mine = sum(_num(p.market_value_base) or 0.0 for p in positions if p.company_id == company.id)
        return ToolOutput(
            source={"table": "positions", "date": _day(today or date.today()), "url": "/portfolio"},
            data={"ticker": company.ticker, "weight_pct": round(100 * mine / total, 2),
                  "positions_count": len(positions)},
        )

    def news_events(ctx: RunContext) -> list[ToolOutput]:
        company = _company(db, ctx)
        if company is None:
            return []
        since = (today or date.today()) - timedelta(days=NEWS_DAYS)
        rows = db.scalars(
            select(NewsEvent)
            .where(NewsEvent.tenant_id == ctx.tenant_id, NewsEvent.company_id == company.id, NewsEvent.date >= since)
            .order_by(NewsEvent.date.desc(), NewsEvent.id.desc())
            .limit(NEWS_MAX)
        ).all()
        return [
            ToolOutput(
                source={"table": "news_events", "id": str(n.id), "source": n.source or "", "url": n.url or "",
                        "date": _day(n.date)},
                data={"title": n.title, "summary": (n.summary or "")[:300],
                      "materiality_score": _num(n.materiality_score), "direction": n.impact_direction},
            )
            for n in rows
        ]

    def user_position(ctx: RunContext) -> ToolOutput | None:
        company = _company(db, ctx)
        if company is None:
            return None
        rows = [p for p in _positions(ctx) if p.company_id == company.id and (_num(p.quantity) or 0) > 0]
        if not rows:
            return None
        p = rows[0]
        return ToolOutput(
            source={"table": "positions", "id": str(p.id), "date": _day(today or date.today())},
            data={"ticker": company.ticker, "quantity": _num(p.quantity), "average_cost": _num(p.average_cost),
                  "currency": p.currency, "cost_basis_base": _num(p.cost_basis_base),
                  "market_value_base": _num(p.market_value_base), "unrealized_pnl_base": _num(p.unrealized_pnl_base)},
        )

    def irpf_savings_bands(ctx: RunContext) -> ToolOutput:
        from app.services.tax_irpf_filing import savings_bands

        year = (today or date.today()).year
        bands = [
            {"from": _num(low), "to": _num(high), "rate_pct": round(float(rate) * 100, 2)}
            for low, high, rate in savings_bands(year)
        ]
        return ToolOutput(
            source={"table": "code:tax_irpf_filing.savings_bands", "law": "LIRPF art. 66 y 76", "date": str(year)},
            data={"year": year, "bands": bands},
        )

    specs = [
        ("financial_facts", financial_facts, "Hechos financieros reportados (SEC/ESEF), 2 últimos ejercicios"),
        ("valuation_engine", valuation_engine, "Motor de valoración y última versión de tesis"),
        ("risk_events", risk_events, "Eventos de riesgo registrados de la empresa"),
        ("portfolio_concentration", portfolio_concentration, "Peso de la empresa en la cartera del usuario"),
        ("news_events", news_events, "Noticias de los últimos 90 días con materialidad"),
        ("user_position", user_position, "Posición del usuario en la empresa"),
        ("irpf_savings_bands", irpf_savings_bands, "Tramos de la base del ahorro del IRPF del año"),
    ]
    return {name: ToolSpec(name=name, fn=fn, description=desc) for name, fn, desc in specs}
