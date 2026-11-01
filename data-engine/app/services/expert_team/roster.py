"""Plantilla del equipo: cada experto con su prompt versionado y su lista blanca."""

from __future__ import annotations

from app.services.expert_team.experts import ExpertSpec
from app.services.expert_team.models import RunContext


def _tax_applies(ctx: RunContext) -> bool:
    # En tesis solo si el usuario tiene posición; en el chat, si lo pregunta.
    return ctx.mode == "chat" or ctx.holds_position


def default_experts() -> list[ExpertSpec]:
    return [
        ExpertSpec(
            name="fundamental",
            broad=True,
            prompt_name="expert_fundamental",
            tools=("financial_facts",),
            keywords=("fundamental", "ingresos", "ventas", "margen", "beneficio", "caja", "balance",
                      "crecimiento", "revenue", "margin", "earnings", "cash flow", "growth"),
        ),
        ExpertSpec(
            name="valuation",
            broad=True,
            prompt_name="expert_valuation",
            tools=("valuation_engine",),
            keywords=("valoracion", "valorar", "dcf", "multiplo", "precio objetivo", "valor razonable",
                      "margen de seguridad", "cara", "barata", "valuation", "fair value", "cheap", "expensive"),
        ),
        ExpertSpec(
            name="risk",
            broad=True,
            prompt_name="expert_risk",
            tools=("risk_events", "portfolio_concentration"),
            keywords=("riesgo", "peligro", "concentracion", "deuda", "risk", "downside", "concentration"),
        ),
        ExpertSpec(
            name="news",
            prompt_name="expert_news",
            tools=("news_events",),
            keywords=("noticia", "prensa", "titular", "sentimiento", "news", "headline", "sentiment"),
        ),
        ExpertSpec(
            name="tax",
            prompt_name="expert_tax",
            tools=("user_position", "irpf_savings_bands"),
            keywords=("irpf", "impuesto", "hacienda", "fiscal", "tributa", "plusvalia", "tax"),
            applies=_tax_applies,
        ),
    ]
