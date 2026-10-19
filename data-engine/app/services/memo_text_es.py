"""Textos del memorando de la tesis en español de UI.

Mapa central de claves internas (métricas, motores, marcos, fuentes) y
formato de cifras es-ES. Una clave desconocida se muestra con espacios en
lugar de guiones bajos: nunca se inventa su significado.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

TERMS_ES: dict[str, str] = {
    # Hechos financieros canónicos
    "revenue": "Ingresos",
    "gross_profit": "Beneficio bruto",
    "operating_income": "Resultado operativo",
    "net_income": "Beneficio neto",
    "ebitda": "EBITDA",
    "free_cash_flow": "Flujo de caja libre",
    "operating_cash_flow": "Flujo de caja operativo",
    "capex": "Capex",
    "total_debt": "Deuda total",
    "cash": "Caja",
    "total_assets": "Activos totales",
    "total_equity": "Patrimonio neto",
    "shares_diluted": "Acciones diluidas",
    "income_tax_expense": "Impuesto de sociedades",
    "income_before_tax": "Resultado antes de impuestos",
    # Inputs del modelo
    "capex_to_revenue": "Capex sobre ingresos",
    "effective_tax_rate": "Tipo impositivo efectivo",
    "traceable_wacc": "WACC trazable",
    "wacc": "WACC",
    "terminal_growth": "Crecimiento terminal",
    "revenue_growth": "Crecimiento de ingresos",
    "fcf_margin": "Margen FCF",
    "gross_margin": "Margen bruto",
    "operating_margin": "Margen operativo",
    "net_margin": "Margen neto",
    "ebitda_margin": "Margen EBITDA",
    "net_debt": "Deuda neta",
    "satellites_on_orbit": "Satélites en órbita",
    # Motores, marcos y fuentes
    "standard_dcf": "DCF estándar",
    "generic_fcf": "FCF genérico",
    "pre_revenue": "Pre-ingresos",
    "revenue_driver": "Motor de ingresos",
    "research_candidate": "Candidata de análisis",
    "financial_facts": "Datos financieros",
    "insufficient_data": "Datos insuficientes",
    "probability_weighted_scenarios": "Escenarios ponderados por probabilidad",
    "space_telecom_pre_fcf": "Telecomunicaciones espaciales antes de caja libre",
    "sec_filing": "Informe SEC",
    "unknown": "desconocido",
}


def term_es(key: object) -> str:
    """Etiqueta ES de una clave interna; desconocida -> con espacios."""
    text = str(key)
    return TERMS_ES.get(text) or TERMS_ES.get(text.lower()) or text.replace("_", " ")


def number_es(value: object, unit: object = None) -> str:
    """Cifra legible en es-ES: miles con punto, decimales con coma."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    magnitude = abs(number)
    if magnitude >= 1000:
        text = f"{number:,.0f}"
    elif magnitude >= 1:
        text = f"{number:,.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{float(number):.3g}"
    text = text.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{text} {unit}" if unit else text


# Estados y ratings persistidos (enums internos) -> español de UI. Mismo
# vocabulario que la ficha (STATUS_LABELS / RATING_LABELS del front).
STATUS_ES: dict[str, str] = {
    "draft": "borrador",
    "review": "en revisión",
    "final": "final",
    "approved": "aprobada",
    "published": "publicada",
    "rejected": "rechazada",
    "changes_requested": "cambios pedidos",
    "stale": "desactualizada",
    "superseded": "sustituida",
    "insufficient_data": "datos insuficientes",
    "draft_failed_audit": "borrador (auditoría no superada)",
}

RATING_ES: dict[str, str] = {
    "buy": "compra",
    "accumulate": "acumular",
    "overweight": "sobreponderar",
    "hold": "mantener",
    "underweight": "infraponderar",
    "trim": "recortar",
    "sell": "venta",
    "avoid": "evitar",
    "watch": "seguimiento",
    "attractive": "atractiva",
    "expensive": "cara",
    "incomplete_price": "precio incompleto",
    "blocked": "bloqueada",
    "insufficient_data": "datos insuficientes",
}


def label_es(mapping: dict[str, str], value: str | None) -> str:
    """Enum interno -> etiqueta es-ES; desconocido se muestra legible, nunca inventado."""
    if not value:
        return "desconocido"
    return mapping.get(value, value.replace("_", " "))


def percent_es(value: float, decimals: int = 1) -> str:
    """Fracción (-0,649) -> «-64,9 %»: coma decimal y espacio antes del signo."""
    return f"{value * 100:.{decimals}f}".replace(".", ",") + " %"


def money_thesis(value: float, currency: str | None) -> str:
    """Dólares en escala inglesa («$343.46»); otras divisas en es-ES con su código."""
    if currency == "USD":
        return f"${value:,.2f}" if value >= 0 else f"-${abs(value):,.2f}"
    if currency and len(currency) == 3 and currency.isupper():
        number = f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
        return f"{number} {currency}"
    return f"{value:,.2f}"


_MESES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def date_es(value: object) -> str:
    """Fecha ISO («2026-10-17» o datetime ISO) -> «17 de octubre de 2026».

    Una frase en español nunca lleva la fecha en formato ISO. Si el valor no
    es una fecha reconocible se devuelve tal cual: nunca se inventa un día.
    """
    text = str(value or "").strip()
    if not text:
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return f"{parsed.day} de {_MESES_ES[parsed.month - 1]} de {parsed.year}"
