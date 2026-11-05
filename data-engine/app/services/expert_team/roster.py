"""Plantilla del equipo: cada experto con su prompt versionado y su lista blanca."""

from __future__ import annotations

import re

from app.services.expert_team.coordinator import fold, is_broad_question, keyword_hit
from app.services.expert_team.experts import ExpertSpec
from app.services.expert_team.models import RunContext

#: «tax » solo como palabra entera («taxonomy» no es fiscal); «taxes», «taxation»… por prefijo.
_TAX_KEYWORDS = ("irpf", "impuesto", "hacienda", "fiscal", "tributa", "plusvalia", "tax ", "taxes", "taxed",
                 "taxation", "taxable")
#: «año fiscal», «fiscal 2024», «FY»: el periodo contable de la empresa, no tus impuestos.
_FISCAL_PERIOD_RE = re.compile(
    r"\b(?:ano|anos|ejercicio|ejercicios|periodo|trimestre|cierre)\s+fiscal(?:es)?\b"
    r"|\bfiscal\s+(?:year|years|quarter|quarters|period|q[1-4]|\d{2,4})\b"
)
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
    if any(keyword_hit(_FISCAL_PERIOD_RE.sub(" ", question), k) for k in _TAX_KEYWORDS):
        return True
    if is_broad_question(question):
        return ctx.holds_position and bool(_HOLD_SELL_RE.search(question))
    # Sin palabra fiscal (o solo «año fiscal» de la empresa): el fiscal no entra.
    return False


def default_experts() -> list[ExpertSpec]:
    return [
        ExpertSpec(
            name="fundamental",
            typical_s=14.0,
            broad=True,
            prompt_name="expert_fundamental",
            tools=("financial_facts",),
            keywords=("fundamental", "ingresos", "ventas", "margen", "beneficio", "caja", "balance",
                      "crecimiento", "revenue", "margin", "earnings", "cash flow", "growth"),
        ),
        ExpertSpec(
            name="valuation",
            typical_s=5.0,
            broad=True,
            prompt_name="expert_valuation",
            tools=("valuation_engine",),
            keywords=("valoracion", "valorar", "dcf", "multiplo", "precio objetivo", "valor razonable",
                      "margen de seguridad", "cara ", "caras ", "caro ", "caros ", "barat", "valuation", "fair value", "cheap", "expensive",
                      "sobrevalor", "infravalor", "overvalu", "undervalu"),
        ),
        ExpertSpec(
            name="risk",
            typical_s=11.0,
            broad=True,
            prompt_name="expert_risk",
            tools=("risk_events", "portfolio_concentration"),
            keywords=("riesgo", "peligro", "concentracion", "deuda", "risk", "downside", "concentration",
                      "arriesgad", "volatil"),
        ),
        ExpertSpec(
            name="news",
            typical_s=6.0,
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
            typical_s=12.0,
            prompt_name="expert_tax",
            tools=("user_position", "irpf_savings_bands", "sale_tax_estimate"),
            broad=True,
            keywords=_TAX_KEYWORDS,
            applies=_tax_applies,
        ),
    ]


def recopilador_expert() -> ExpertSpec:
    """«Recopilador»: inventario de impulsores de valor (etapa 1 del pipeline de la tesis).

    No entra en ``default_experts``: no responde preguntas ni opina, produce el
    inventario que leen el valorador, la mezcla de analistas y el escéptico. Lo
    corre ``expert_team.recopilador.run_recopilador`` (con EXPERT_TEAM_ENABLED).
    """
    from app.services.expert_team.recopilador import RECOPILADOR_NAME, RECOPILADOR_TOOLS

    return ExpertSpec(
        name=RECOPILADOR_NAME,
        typical_s=25.0,
        prompt_name="expert_recopilador",
        tools=RECOPILADOR_TOOLS,
        max_tokens=8000,
    )


def analyst_blend_expert() -> ExpertSpec:
    """«Mezcla de analistas»: rellena los huecos del modelo con las mejores firmas.

    Etapa del pipeline de la tesis tras el Recopilador y la detección de huecos.
    No entra en ``default_experts``. La corre
    ``expert_team.analyst_blend.run_analyst_blend`` (con EXPERT_TEAM_ENABLED).
    """
    from app.services.expert_team.analyst_blend import BLEND_NAME, BLEND_TOOLS

    return ExpertSpec(
        name=BLEND_NAME,
        typical_s=20.0,
        prompt_name="expert_mezcla_analistas",
        tools=BLEND_TOOLS,
        max_tokens=6000,
    )


def pipeline_experts() -> list[ExpertSpec]:
    """Roles del pipeline automático de la tesis, en orden: Recopilador y mezcla de analistas."""
    return [recopilador_expert(), analyst_blend_expert()]
