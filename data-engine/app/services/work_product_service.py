"""Source-manifested investment work products built from canonical records."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from math import isfinite
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    CalculatedMetric,
    Claim,
    Company,
    Document,
    FinancialFact,
    MarketPrice,
    ResearchAlert,
    ThesisVersion,
)
from app.services.peer_comparison_service import (
    DEFAULT_PEER_METRICS,
    PeerComparisonService,
)
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.risk_service import RiskService

WORK_PRODUCT_TYPES = {
    "one_page_memo",
    "full_thesis",
    "earnings_review",
    "valuation_memo",
    "capital_allocation_analysis",
    "comparables",
    "portfolio_review",
    "risk_report",
}
COMPANY_REQUIRED = WORK_PRODUCT_TYPES - {"portfolio_review", "risk_report"}


# QA /research «Generar entregable»: el diálogo volcaba el JSON crudo
# (snake_case, inglés) y el markdown del backend metía str(payload) con
# reprs de Python. El documento que lee el usuario se genera aquí en
# español: secciones con nombre, cifras formateadas y fuentes.
_PRODUCT_LABELS = {
    "one_page_memo": "Memo de una página",
    "full_thesis": "Tesis completa",
    "earnings_review": "Revisión de resultados",
    "valuation_memo": "Memo de valoración",
    "capital_allocation_analysis": "Análisis de asignación de capital",
    "comparables": "Comparables",
    "portfolio_review": "Revisión de cartera",
    "risk_report": "Informe de riesgo",
}
_SECTION_LABELS = {
    "company": "Empresa",
    "investment_summary": "Resumen de inversión",
    "market_price": "Precio de mercado",
    "metrics": "Métricas",
    "risks": "Riesgos",
    "risks_and_open_questions": "Riesgos y preguntas abiertas",
    "thesis": "Tesis",
    "financial_facts": "Datos financieros",
    "calculated_metrics": "Métricas calculadas",
    "peer_comparison": "Comparación con comparables",
    "portfolio_intelligence": "Panorama de cartera",
    "portfolio_risk": "Riesgo de cartera",
}
_KEY_LABELS = {
    "ticker": "Ticker",
    "name": "Nombre",
    "sector": "Sector",
    "industry": "Industria",
    "company_type": "Tipo de empresa",
    "version": "Versión",
    "status": "Estado",
    "rating": "Calificación",
    "executive_summary": "Resumen ejecutivo",
    "current_price": "Precio actual",
    "bear_value": "Valor bajista",
    "base_value": "Valor base",
    "bull_value": "Valor optimista",
    "expected_value": "Valor esperado",
    "margin_of_safety": "Margen de seguridad",
    "close": "Cierre",
    "date": "Fecha",
    "source": "Fuente",
    "kind": "Tipo",
    "statement": "Afirmación",
    "title": "Título",
    "severity": "Severidad",
    "confidence": "Confianza",
    "value": "Valor",
    "unit": "Unidad",
    "period": "Periodo",
}
_METRIC_LABELS = {
    "revenue": "Ingresos",
    "net_income": "Beneficio neto",
    "total_equity": "Patrimonio neto",
    "eps": "BPA",
    "eps_diluted": "BPA diluido",
    "shares_diluted": "Acciones diluidas",
    "free_cash_flow": "Flujo de caja libre",
    "fcf_margin": "Margen de FCF",
    "net_debt": "Deuda neta",
    "total_debt": "Deuda total",
    "cash_and_equivalents": "Efectivo y equivalentes",
    "interest_coverage": "Cobertura de intereses",
    "current_ratio": "Ratio de liquidez",
    "wacc": "WACC",
    "roic": "ROIC",
    "incremental_roic": "ROIC incremental",
    "capital_expenditure": "Inversión de capital",
    "owner_earnings": "Beneficios del propietario",
    "stock_based_compensation": "Compensación en acciones",
    "dividends": "Dividendos",
    "buybacks": "Recompras",
}
_FIELD_VALUES_ES = {
    "sector": {
        "Information Technology": "Tecnología de la información", "Technology": "Tecnología",
        "Communication Services": "Servicios de comunicación", "Consumer Discretionary": "Consumo discrecional",
        "Consumer Staples": "Consumo básico", "Consumer Cyclical": "Consumo cíclico",
        "Consumer Defensive": "Consumo defensivo", "Financials": "Finanzas",
        "Financial Services": "Servicios financieros", "Health Care": "Salud", "Healthcare": "Salud",
        "Industrials": "Industria", "Materials": "Materiales", "Basic Materials": "Materiales básicos",
        "Energy": "Energía", "Utilities": "Servicios públicos", "Real Estate": "Inmobiliario", "Unknown": "Sin datos",
    },
    "company_type": {
        "research_candidate": "Candidata de análisis", "portfolio_holding": "Posición en cartera",
        "operating": "Operativa", "holding": "Sociedad de cartera", "bank": "Banco",
        "insurance": "Aseguradora", "unassigned": "Sin clasificar", "pre_revenue": "Pre-ingresos",
    },
    "rating": {
        "expensive": "Cara", "attractive": "Atractiva", "buy": "Compra", "sell": "Venta",
        "hold": "Mantener", "watch": "Seguimiento", "accumulate": "Acumular", "avoid": "Evitar",
        "trim": "Recortar", "overweight": "Sobreponderar", "underweight": "Infraponderar",
        "blocked": "Bloqueada", "insufficient_data": "Datos insuficientes", "incomplete_price": "Precio incompleto",
    },
}


def _field_value(key: str, value: Any) -> str:
    if key in _FIELD_VALUES_ES and isinstance(value, str):
        return _FIELD_VALUES_ES[key].get(value, value.replace("_", " "))
    return _format(value)


_STATUS_LABELS = {
    "missing": "sin datos",
    "ok": "correcto",
    "high": "alta",
    "medium": "media",
    "low": "baja",
    "draft": "borrador",
    "published": "publicada",
    "contradicted": "contradicha",
    "stale": "desactualizada",
    "uncertain": "incierta",
    "unverified": "sin verificar",
    "operating": "operativa",
    "holding": "holding",
    "unassigned": "sin clasificar",
    "bank": "banco",
    "insurance": "aseguradora",
}
# Avisos del manifiesto (el JSON los expone en inglés y los tests lo pinean;
# la traducción es solo para el documento legible).
_WARNING_LABELS = {
    "No canonical sources were available": "No había fuentes canónicas disponibles.",
    "Data date is unavailable": "La fecha de los datos no está disponible.",
}
_OBSERVATION_KEYS = {"value", "unit", "period", "confidence", "citation"}
# Formato de moneda (regla de Nico): USD en escala inglesa ($343.46, $5.16T,
# $394B); emisores no USD conservan su divisa en formato es-ES; porcentajes
# es-ES con coma.
_MONEY_KEYS = {
    "close",
    "current_price",
    "bear_value",
    "base_value",
    "bull_value",
    "expected_value",
}
_PERCENT_KEYS = {"margin_of_safety"}


def _format_usd(value: Any) -> str:
    """USD en escala inglesa: $343.46, $5.16T, $394B."""
    amount = float(value)
    if not isfinite(amount):
        return "sin datos"
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1e12:
        scaled, suffix = amount / 1e12, "T"
    elif amount >= 1e9:
        scaled, suffix = amount / 1e9, "B"
    elif amount >= 1e6:
        scaled, suffix = amount / 1e6, "M"
    else:
        scaled, suffix = amount, ""
    if suffix or scaled != int(scaled):
        text = f"{scaled:.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{int(scaled):,}"
    return f"{sign}${text}{suffix}"


def _format_pct(value: Any) -> str:
    """Fracción como porcentaje es-ES con coma: 0.25 -> 25,0 %."""
    return f"{float(value) * 100:.1f}".replace(".", ",") + " %"


def _format_money(value: Any, currency: str | None) -> str:
    if currency == "USD":
        return _format_usd(value)
    formatted = _format(value)
    return f"{formatted} {currency}" if currency else formatted


def _label(key: str) -> str:
    if key in _KEY_LABELS:
        return _KEY_LABELS[key]
    return key.replace("_", " ").capitalize()


def _format(value: Any) -> str:
    """Cifra o texto legible en español; nunca reprs de Python."""
    if value is None:
        return "sin datos"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, Decimal):
        text = (
            f"{value:,.4f}".rstrip("0").rstrip(".")
            if value != int(value)
            else f"{int(value):,}"
        )
        return text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        if not isfinite(value):
            return "sin datos"
        text = f"{value:,.4f}".rstrip("0").rstrip(".")
        return text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value)
    return _STATUS_LABELS.get(text, text)


def _render_observation(name: str, obs: dict[str, Any], lines: list[str]) -> None:
    value = obs.get("value")
    unit = obs.get("unit") or ""
    extras = [
        extra
        for extra in (
            obs.get("period"),
            _STATUS_LABELS.get(str(obs.get("confidence")), _format(obs.get("confidence"))),
        )
        if extra
    ]
    suffix = f" ({', '.join(_format(extra) for extra in extras)})" if extras else ""
    label = _METRIC_LABELS.get(name, _label(name))
    if (unit or "").upper() == "USD":
        lines.append(f"- **{label}**: {_format_usd(value)}{suffix}")
    else:
        lines.append(f"- **{label}**: {_format(value)} {unit}{suffix}".rstrip())


def _render_payload(
    payload: Any, lines: list[str], currency: str | None = None
) -> None:
    """Renderiza un payload arbitrario como markdown legible (recursivo)."""
    if isinstance(payload, dict):
        if payload.get("status") == "missing" and len(payload) == 1:
            lines.append("_Sin datos._")
            return
        for key, value in payload.items():
            if key == "citation" or value is None:
                continue
            if key == "markdown" and isinstance(value, str):
                lines.extend(("", value))
            elif isinstance(value, dict):
                if set(value) <= _OBSERVATION_KEYS:
                    _render_observation(key, value, lines)
                else:
                    lines.append(f"- **{_label(key)}**:")
                    nested: list[str] = []
                    _render_payload(value, nested, currency)
                    lines.extend(f"  {line}" if line else line for line in nested)
            elif isinstance(value, list):
                lines.append(f"- **{_label(key)}**:")
                nested = []
                _render_payload(value, nested, currency)
                lines.extend(f"  {line}" if line else line for line in nested)
            elif key in _MONEY_KEYS:
                lines.append(f"- **{_label(key)}**: {_format_money(value, currency)}")
            elif key in _PERCENT_KEYS:
                lines.append(f"- **{_label(key)}**: {_format_pct(value)}")
            else:
                lines.append(f"- **{_label(key)}**: {_field_value(key, value)}")
    elif isinstance(payload, list):
        if not payload:
            lines.append("_Sin datos._")
            return
        for item in payload:
            if isinstance(item, dict) and set(item) <= _OBSERVATION_KEYS:
                _render_observation("valor", item, lines)
            elif isinstance(item, dict):
                pairs = [
                    f"**{_label(k)}**: {_field_value(k, v)}"
                    for k, v in item.items()
                    if k != "citation" and v is not None and not isinstance(v, (dict, list))
                ]
                lines.append("- " + ", ".join(pairs))
                for k, v in item.items():
                    if isinstance(v, (dict, list)) and k != "citation":
                        _render_payload(v, lines)
            else:
                lines.append(f"- {_format(item)}")
    else:
        lines.append(_format(payload))


class WorkProductService:
    def generate(
        self,
        db: Session,
        *,
        product_type: str,
        company: Company | None = None,
        years: int = 10,
    ) -> dict[str, Any]:
        if db.info.get("tenant_id") is None:
            raise ValueError("Tenant context is required for work products")
        if product_type not in WORK_PRODUCT_TYPES:
            raise ValueError("Unsupported work product type")
        if product_type in COMPANY_REQUIRED and company is None:
            raise ValueError(f"{product_type} requires a company")

        if product_type == "portfolio_review":
            sections = {
                "portfolio_intelligence": PortfolioIntelligenceService().build(
                    db, years=max(1, min(years, 20))
                )
            }
            sources, data_as_of = self._portfolio_manifest(db)
            title = _PRODUCT_LABELS["portfolio_review"]
        elif product_type == "risk_report" and company is None:
            sections = {"portfolio_risk": RiskService().dashboard(db)}
            sources, data_as_of = self._portfolio_manifest(db)
            title = f"{_PRODUCT_LABELS['risk_report']} de cartera"
        else:
            assert company is not None
            context = self._context(db, company, years)
            sections = self._sections(db, company, product_type, context)
            sources, data_as_of = context["sources"], context["data_as_of"]
            title = f"{_PRODUCT_LABELS[product_type]} · {company.ticker}"

        manifest = {
            "generated_at": datetime.now(UTC),
            "data_as_of": data_as_of,
            "source_count": len(sources),
            "sources": sources,
            "warnings": [
                message
                for condition, message in (
                    (not sources, "No canonical sources were available"),
                    (data_as_of is None, "Data date is unavailable"),
                )
                if condition
            ],
        }
        return {
            "product_type": product_type,
            "title": title,
            "ticker": company.ticker if company else None,
            "sections": sections,
            "markdown": self._markdown(
                title,
                sections,
                manifest,
                (company.currency or "").upper() if company else None,
            ),
            "manifest": manifest,
        }

    def _context(
        self, db: Session, company: Company, years: int
    ) -> dict[str, Any]:
        minimum_year = date.today().year - max(1, min(years, 20)) + 1
        facts = list(
            db.scalars(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id == company.id,
                    (FinancialFact.fiscal_year.is_(None))
                    | (FinancialFact.fiscal_year >= minimum_year),
                )
                .order_by(
                    FinancialFact.metric,
                    desc(FinancialFact.fiscal_year),
                    desc(FinancialFact.id),
                )
                .limit(500)
            ).all()
        )
        metrics = list(
            db.scalars(
                select(CalculatedMetric)
                .where(
                    CalculatedMetric.company_id == company.id,
                    CalculatedMetric.status == "ok",
                )
                .order_by(
                    CalculatedMetric.metric,
                    desc(CalculatedMetric.fiscal_year),
                    desc(CalculatedMetric.id),
                )
                .limit(300)
            ).all()
        )
        documents = list(
            db.scalars(
                select(Document)
                .where(Document.company_id == company.id)
                .order_by(desc(Document.published_at), desc(Document.created_at))
                .limit(100)
            ).all()
        )
        thesis = db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )
        price = db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company.id)
            .order_by(desc(MarketPrice.date))
            .limit(1)
        )
        claims = list(
            db.scalars(
                select(Claim)
                .where(Claim.company_id == company.id)
                .order_by(desc(Claim.updated_at))
                .limit(50)
            ).all()
        )
        alerts = list(
            db.scalars(
                select(ResearchAlert)
                .where(ResearchAlert.company_id == company.id)
                .order_by(desc(ResearchAlert.created_at))
                .limit(30)
            ).all()
        )
        sources = self._manifest_sources(
            company, facts, metrics, documents, thesis, price
        )
        dates = [
            self._as_date(source["data_date"])
            for source in sources
            if source.get("data_date") is not None
        ]
        return {
            "facts": facts,
            "metrics": metrics,
            "thesis": thesis,
            "price": price,
            "claims": claims,
            "alerts": alerts,
            "sources": sources,
            "data_as_of": max(dates) if dates else None,
        }

    def _sections(
        self,
        db: Session,
        company: Company,
        product_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        facts = self._observations(context["facts"], "financial_fact")
        metrics = self._observations(context["metrics"], "calculated_metric")
        all_metrics = {**facts, **metrics}
        thesis = context["thesis"]
        overview = {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "industry": company.industry,
            "company_type": company.company_type,
        }
        thesis_payload = (
            {
                "version": thesis.version,
                "status": thesis.status,
                "rating": thesis.rating,
                "executive_summary": thesis.executive_summary,
                "current_price": thesis.current_price,
                "bear_value": thesis.bear_value,
                "base_value": thesis.base_value,
                "bull_value": thesis.bull_value,
                "expected_value": thesis.expected_value,
                "margin_of_safety": thesis.margin_of_safety,
                "citation": f"thesis:{thesis.id}",
            }
            if thesis
            else {"status": "missing"}
        )
        risks = self._risks(context["claims"], context["alerts"])
        price = context["price"]
        price_payload = (
            {
                "close": price.close,
                "date": price.date,
                "source": price.source,
                "citation": f"market_price:{price.id}",
            }
            if price
            else {"status": "missing"}
        )
        if product_type == "comparables":
            return {
                "company": overview,
                "peer_comparison": PeerComparisonService().compare(
                    db,
                    company,
                    limit=8,
                    metrics=DEFAULT_PEER_METRICS,
                    refresh=False,
                ),
            }
        if product_type == "full_thesis":
            thesis_payload["markdown"] = thesis.thesis_markdown if thesis else None
            return {
                "company": overview,
                "thesis": thesis_payload,
                "financial_facts": facts,
                "calculated_metrics": metrics,
                "risks_and_open_questions": risks,
            }
        selected = {
            "earnings_review": set(all_metrics),
            "valuation_memo": {
                "revenue", "free_cash_flow", "eps", "shares_diluted",
                "net_debt", "wacc", "roic",
            },
            "capital_allocation_analysis": {
                "free_cash_flow", "capital_expenditure", "owner_earnings",
                "shares_diluted", "stock_based_compensation", "dividends",
                "buybacks", "roic", "incremental_roic",
            },
            "risk_report": {
                "cash_and_equivalents", "total_debt", "net_debt",
                "interest_coverage", "current_ratio", "shares_diluted",
            },
        }.get(product_type, set(list(all_metrics)[:12]))
        return {
            "company": overview,
            "investment_summary": thesis_payload,
            "market_price": price_payload,
            "metrics": {
                key: value for key, value in all_metrics.items() if key in selected
            },
            "risks": risks[:20],
        }

    @staticmethod
    def _observations(rows: list[Any], entity_type: str) -> dict[str, Any]:
        result = {}
        for row in rows:
            result.setdefault(
                row.metric,
                {
                    "value": row.value,
                    "unit": row.unit,
                    "period": row.period,
                    "confidence": row.confidence,
                    "citation": f"{entity_type}:{row.id}",
                },
            )
        return result

    @staticmethod
    def _risks(claims: list[Claim], alerts: list[ResearchAlert]) -> list[dict]:
        return [
            {
                "kind": "claim",
                "statement": row.statement,
                "status": row.status,
                "confidence": row.confidence,
                "citation": f"claim:{row.id}",
            }
            for row in claims
            if row.status in {"contradicted", "stale", "uncertain", "unverified"}
        ] + [
            {
                "kind": "alert",
                "title": row.title,
                "severity": row.severity,
                "status": row.status,
                "citation": f"alert:{row.id}",
            }
            for row in alerts
        ]

    @staticmethod
    def _manifest_sources(
        company: Company,
        facts: list[FinancialFact],
        metrics: list[CalculatedMetric],
        documents: list[Document],
        thesis: ThesisVersion | None,
        price: MarketPrice | None,
    ) -> list[dict[str, Any]]:
        sources = [
            {
                "citation": f"document:{row.id}",
                "type": "document",
                "id": row.id,
                "title": row.title,
                "source_type": row.source_type,
                "source_url": row.source_url,
                "data_date": row.published_at or row.created_at,
            }
            for row in documents
        ]
        sources.extend(
            {
                "citation": f"financial_fact:{row.id}",
                "type": "financial_fact",
                "id": row.id,
                "title": f"{row.metric} · {row.period}",
                "source_type": row.source_type,
                "source_document_id": row.source_id,
                "data_date": row.updated_at,
            }
            for row in facts
        )
        sources.extend(
            {
                "citation": f"calculated_metric:{row.id}",
                "type": "calculated_metric",
                "id": row.id,
                "title": f"{row.metric} · {row.period}",
                "source_fact_ids": row.source_fact_ids,
                "data_date": row.updated_at,
            }
            for row in metrics
        )
        if thesis:
            sources.append(
                {
                    "citation": f"thesis:{thesis.id}",
                    "type": "thesis",
                    "id": thesis.id,
                    "title": f"Thesis v{thesis.version}",
                    "data_date": thesis.created_at,
                }
            )
        if price:
            sources.append(
                {
                    "citation": f"market_price:{price.id}",
                    "type": "market_price",
                    "id": price.id,
                    "title": f"{company.ticker} close",
                    "source_type": price.source,
                    "data_date": price.date,
                }
            )
        return list({source["citation"]: source for source in sources}.values())

    @staticmethod
    def _portfolio_manifest(db: Session) -> tuple[list[dict[str, Any]], date | None]:
        prices = list(
            db.scalars(select(MarketPrice).order_by(desc(MarketPrice.date)).limit(500)).all()
        )
        return (
            [
                {
                    "citation": f"market_price:{row.id}",
                    "type": "market_price",
                    "id": row.id,
                    "title": f"Company {row.company_id} close",
                    "source_type": row.source,
                    "data_date": row.date,
                }
                for row in prices
            ],
            max((row.date for row in prices), default=None),
        )

    @staticmethod
    def _as_date(value: date | datetime) -> date:
        return value.date() if isinstance(value, datetime) else value

    def _markdown(
        self,
        title: str,
        sections: dict[str, Any],
        manifest: dict[str, Any],
        currency: str | None = None,
    ) -> str:
        data_as_of = manifest["data_as_of"]
        lines = [
            f"# {title}",
            "",
            f"Datos a fecha de: {_format(data_as_of) if data_as_of else 'fecha no disponible'}",
        ]
        warnings = manifest.get("warnings") or []
        if warnings:
            lines.extend(("", "## Avisos", ""))
            lines.extend(
                f"- {_WARNING_LABELS.get(warning, warning)}" for warning in warnings
            )
        for name, payload in sections.items():
            lines.extend(("", f"## {_SECTION_LABELS.get(name, _label(name))}", ""))
            _render_payload(payload, lines, currency)
        lines.extend(("", "## Fuentes", ""))
        sources = manifest["sources"]
        if sources:
            lines.extend(
                f"- [{source['citation']}] {source['title']}"
                for source in sources
            )
        else:
            lines.append("_Sin fuentes canónicas._")
        return "\n".join(lines)
