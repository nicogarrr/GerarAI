"""Plantilla del equipo: cada experto con su prompt versionado y su lista blanca."""

from __future__ import annotations

import re

from app.services.expert_team.coordinator import fold, is_broad_question
from app.services.expert_team.experts import ExpertSpec
from app.services.expert_team.models import RunContext

_TAX_KEYWORDS = ("irpf", "impuesto", "hacienda", "fiscal", "tributa", "plusvalia", "tax")
#: «¿merece la pena mantener/vender X?»: decidir sobre una posición que ya tienes.
_HOLD_SELL_RE = re.compile(
    r"\b(?:mantener|mantenerla|mantenerlas|vender|venderla|venderlas|quedarme|salir|seguir\s+con"
    r"|hold|holding|keep|sell|selling)\b"
)


def _tax_applies(ctx: RunContext) -> bool:
    """Tesis: solo con posición. Chat: si pregunta por impuestos o, en una
    pregunta amplia de mantener/vender, si tiene la posición."""
    if ctx.mode != "chat":
        return ctx.holds_position
    question = fold(ctx.question or "")
    if any(re.search(rf"\b{re.escape(k)}", question) for k in _TAX_KEYWORDS):
        return True
    if is_broad_question(question):
        return ctx.holds_position and bool(_HOLD_SELL_RE.search(question))
    return True


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
                      "margen de seguridad", "cara", "barata", "valuation", "fair value", "cheap", "expensive",
                      "sobrevalor", "infravalor", "overvalu", "undervalu"),
        ),
        ExpertSpec(
            name="risk",
            broad=True,
            prompt_name="expert_risk",
            tools=("risk_events", "portfolio_concentration"),
            keywords=("riesgo", "peligro", "concentracion", "deuda", "risk", "downside", "concentration",
                      "arriesgad", "volatil"),
        ),
        ExpertSpec(
            name="news",
            broad=True,
            prompt_name="expert_news",
            tools=("news_events",),
            # Además de «noticia», lo reciente: caídas/subidas, anuncios, «últimamente».
            keywords=("noticia", "prensa", "titular", "sentimiento", "news", "headline", "sentiment",
                      "ha pasado", "ultim", "recient", "esta semana", "anunci", "caido", "cayo", "desplom",
                      "hunde", "se dispara", "subido", "bajado", "what happened", "recent", "lately",
                      "this week", "announc", "dropp", "plung", "soar", "surg", "rall"),
        ),
        ExpertSpec(
            name="tax",
            prompt_name="expert_tax",
            tools=("user_position", "irpf_savings_bands"),
            broad=True,
            keywords=_TAX_KEYWORDS,
            applies=_tax_applies,
        ),
    ]
