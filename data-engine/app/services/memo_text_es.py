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
    "capital_expenditure": "Gasto de capital (capex)",
    "cash_and_equivalents": "Caja y equivalentes",
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
    # Claves del DCF inverso (long_term_model_service): sin ellas la tarjeta
    # mostraria la clave cruda con guiones bajos.
    "maintenance_capex": "capex de mantenimiento",
    "normalized_working_capital": "capital de trabajo normalizado",
    "m_and_a_purchase_price_and_post_deal_returns": (
        "precio de compra de M&A y retornos post-operación"
    ),
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
    # Drivers del modelo a largo plazo (mismo vocabulario que lib/research/metric-labels.ts)
    "addressable_subscribers": "suscriptores direccionables",
    "capacity_per_satellite": "capacidad por satélite",
    "monthly_arpu": "ARPU mensual",
    "normalized_fcf_or_fcf_margin": "FCF normalizado o margen FCF",
    "normalized_fcf_margin": "margen FCF normalizado",
    "penetration": "penetración",
    "price_per_gb": "precio por GB",
    "revenue_share": "reparto de ingresos",
    "satellites": "satélites",
    "utilization": "utilización",
    "organic_growth": "crecimiento orgánico",
    "working_capital": "capital circulante",
    "share_count": "número de acciones",
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
    # Inputs faltantes de los motores de valoración (thesis/red team: "faltan ...")
    "fiscal_year": "año fiscal",
    "adr_ratio": "ratio ADR",
    "non_negative_fcf_margin": "margen FCF no negativo",
    "book_value": "valor contable",
    "tangible_book_value": "valor contable tangible",
    "roe": "ROE",
    "cost_of_equity": "coste del capital propio",
    "combined_ratio": "ratio combinado",
    "book_value_growth": "crecimiento del valor contable",
    "aum": "AUM",
    "nav": "NAV",
    "fee_rate": "tasa de comisión",
    "holdco_debt": "deuda del holding",
    "asset_value": "valor de los activos",
    "positive_cap_rate_and_shares": "tasa de capitalización positiva y acciones",
    "valid_shares_and_cost_of_equity_spread": "acciones válidas y diferencial sobre el coste del capital",
    "cost_of_equity_above_book_value_growth": "coste del capital propio por encima del crecimiento del valor contable",
    "consistent_period_volume_cost_price": "volumen, coste y precio de un mismo período",
    "valid_effective_tax_rate_and_commodity_earnings_multiple": "tipo impositivo efectivo válido y múltiplo de beneficios",
    # Claves que emiten los motores/snapshots y llegaban crudas a la UI.
    # term_es normaliza espacios->guiones bajos: una entrada snake_case cubre
    # tambien las frases sueltas ("book value growth" -> "book_value_growth").
    "free_cash_flow_or_fcf_margin": "flujo de caja libre o margen FCF",
    "current_price": "precio actual",
    "peer_multiples": "múltiplos de comparables",
    "cash_cost_per_unit": "coste de caja por unidad",
    "holding_company_discount": "descuento de holding",
    "retention_ratio_or_payout_ratio": "ratio de retención o de payout",
    "maintenance_vs_growth_capex_split": "desglose de capex de mantenimiento frente a crecimiento",
    "market_opportunity": "oportunidad de mercado",
    "working_capital_and_absorption": "capital circulante y absorción",
    "annual_revenue_missing": "ingresos anuales",
    "no_revenue_reported": "ingresos reportados",
    "revenue_history_two_periods": "histórico de ingresos de dos períodos",
    "unknown": "desconocido",
    # Motores, marcos y riesgos que llegaban en inglés al memo (prueba real
    # ASTS/BABA, 2026-10-27). Las claves compuestas con «+» se traducen por
    # partes en `term_es`.
    "dilution": "dilución",
    "sotp": "suma de partes (SOTP)",
    "buyback_adjusted_dcf": "DCF ajustado por recompras",
    "holding_company": "holding",
    "china_adr_holding": "holding china cotizada como ADR",
    "space_network": "red espacial",
    "spectrum": "espectro",
    "execution": "ejecución",
    "funding": "financiación",
    # Marco advertising_platform (Meta y ads/social): drivers y KPIs reales
    # que la empresa desglosa en resultados, en español para memo y UI.
    "advertising_platform": "Plataforma publicitaria / de atención",
    "daily_active_people": "personas activas al día (DAP)",
    "family_arpu": "ingreso medio por persona (Family ARPU)",
    "ad_impressions": "impresiones publicitarias",
    "price_per_ad": "precio medio por anuncio",
    "ad_impressions_yoy": "variación interanual de impresiones publicitarias",
    "price_per_ad_yoy": "variación interanual del precio por anuncio",
    "reality_labs_operating_loss": "pérdida operativa de Reality Labs",
    "operating_margin": "margen operativo",
    "ad_load_ceiling": "techo de carga publicitaria",
    "competition_attention": "competencia por la atención",
    "family_of_apps": "Family of Apps",
    "reality_labs": "Reality Labs",
}


def term_es(key: object) -> str:
    """Etiqueta ES de una clave interna; desconocida -> con espacios.

    Las claves llegan en dos formas (snake_case y frases con espacios, segun
    el motor que las emite): se prueba la clave tal cual, en minusculas y
    normalizada a snake_case para que una sola entrada cubra ambas formas."""
    text = str(key)
    if "+" in text and text not in TERMS_ES:
        # Combinaciones de motores ("sotp+buyback adjusted dcf"): cada parte
        # con su etiqueta, en vez de dejar la cadena entera en inglés.
        parts = [part.strip() for part in text.split("+") if part.strip()]
        if len(parts) > 1:
            return " + ".join(term_es(part) for part in parts)
    return (
        TERMS_ES.get(text)
        or TERMS_ES.get(text.lower())
        or TERMS_ES.get(text.lower().replace(" ", "_"))
        or text.replace("_", " ")
    )


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


# Unidades de hechos financieros que no son divisa ISO.
UNIT_ES: dict[str, str] = {
    "shares": "acciones",
    "decimal": "fracción",
    "ratio": "ratio",
    "pure": "ratio",
}


def unit_es(unit: object) -> str:
    text = str(unit or "").strip()
    if not text:
        return "N/D"
    return UNIT_ES.get(text.lower(), text)


# Sectores GICS (11) tal y como llegan del dato maestro. Un valor desconocido se
# muestra tal cual: nunca se inventa una traduccion.
SECTOR_ES: dict[str, str] = {
    "information technology": "Tecnología de la información",
    "technology": "Tecnología",
    "communication services": "Servicios de comunicación",
    "consumer discretionary": "Consumo discrecional",
    "consumer staples": "Consumo básico",
    "energy": "Energía",
    "financials": "Finanzas",
    "financial services": "Servicios financieros",
    "health care": "Salud",
    "healthcare": "Salud",
    "industrials": "Industriales",
    "materials": "Materiales",
    "basic materials": "Materiales básicos",
    "real estate": "Inmobiliario",
    "utilities": "Servicios públicos",
}

INDUSTRY_ES: dict[str, str] = {
    "technology": "Tecnología",
    "telecommunication": "Telecomunicaciones",
    "telecommunications": "Telecomunicaciones",
    "software": "Software",
    "application software": "Software de aplicaciones",
    "semiconductors": "Semiconductores",
    "consumer electronics": "Electrónica de consumo",
    "aerospace & defense": "Aeroespacial y defensa",
    "biotechnology": "Biotecnología",
    "banks": "Banca",
    "insurance": "Seguros",
    "oil & gas": "Petróleo y gas",
    "retail": "Comercio minorista",
}


def sector_es(value: object) -> str:
    text = str(value or "").strip()
    return SECTOR_ES.get(text.lower(), text) if text else "N/D"


def industry_es(value: object) -> str:
    text = str(value or "").strip()
    return INDUSTRY_ES.get(text.lower(), text) if text else "N/D"


# Pregunta primaria de cada marco (company_framework.py, en ingles) en espanol.
PRIMARY_QUESTION_ES: dict[str, str] = {
    "can physical network capacity, monetization and funding support the revenue ramp": "¿Pueden la capacidad física de la red, la monetización y la financiación sostener el aumento de ingresos?",
    "does backlog convert into a profitable, scalable space systems and launch business": "¿La cartera de pedidos se convierte en un negocio rentable y escalable de sistemas espaciales y lanzamientos?",
    "can engagement, volume and take rate compound without losing quality or share": "¿Pueden el engagement, el volumen y la comisión por transacción crecer de forma compuesta sin perder calidad ni cuota?",
    "can subscriber growth, retention and arpu support durable fcf and reinvestment": "¿Pueden el crecimiento de suscriptores, la retención y el ARPU sostener un FCF duradero y la reinversión?",
    "can seats, usage, pricing and retention grow faster than compute and go-to-market costs": "¿Pueden los puestos, el uso, los precios y la retención crecer más rápido que los costes de computación y de comercialización?",
    "can capacity, utilization and pricing earn an acceptable return on heavy investment": "¿Pueden la capacidad, la utilización y los precios dar un retorno aceptable sobre una inversión elevada?",
    "can the asset base compound nav and cash earnings through disciplined capital allocation": "¿Puede la base de activos aumentar el NAV y los beneficios en caja con una asignación de capital disciplinada?",
    "can the deposit franchise earn returns above its cost of equity through the credit cycle": "¿Puede la franquicia de depósitos rentar por encima de su coste de capital a lo largo del ciclo de crédito?",
    "can underwriting discipline and investment returns compound book value above the cost of equity": "¿Pueden la disciplina de suscripción y la rentabilidad de las inversiones aumentar el valor contable por encima del coste de capital?",
    "can same-store noi and accretive investment outgrow financing and cap-rate pressure": "¿Pueden el NOI en mismos activos y la inversión creadora de valor superar la presión de financiación y de las tasas de capitalización?",
    "what is the normalized cash return across price, volume, reserves and reinvestment cycles": "¿Cuál es el retorno de caja normalizado a lo largo de los ciclos de precio, volumen, reservas y reinversión?",
    "can the pipeline or platform reach durable revenue before the cash runway and dilution capacity run out": "¿Puede el pipeline o la plataforma alcanzar ingresos duraderos antes de que se agote la caja y la capacidad de dilución?",
    "can organic growth, margins and reinvestment compound owner earnings at attractive returns": "¿Pueden el crecimiento orgánico, los márgenes y la reinversión aumentar el beneficio del propietario con retornos atractivos?",
    "can ad impressions, price per ad and daily engagement compound advertising revenue without eroding the user experience": "¿Pueden las impresiones publicitarias, el precio por anuncio y el engagement diario hacer crecer los ingresos publicitarios de forma compuesta sin erosionar la experiencia de usuario?",
}


def primary_question_es(question: object) -> str:
    text = str(question or "").strip().rstrip(" .?!")
    if not text:
        return "desconocida"
    es = PRIMARY_QUESTION_ES.get(text.lower())
    return es.rstrip(" .?!") if es else text
