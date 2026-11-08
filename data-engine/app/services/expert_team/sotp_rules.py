"""Reglas deterministas del SOTP de los agentes (8-nov-2026).

«Son datos y luego expertos que los van colocando»: el modelo solo CLASIFICA
(qué segmentos hay, en qué estado está cada uno, de qué tipo de negocio es y
qué cifra de la evidencia ancla sus ingresos, copiada con su cita). Todo lo
numérico lo calcula este módulo con tablas fijas y fórmulas que se muestran
(traza) en la ficha. Una cifra del modelo que no aparece en el pasaje citado
no se usa: el segmento pasa a «sin valorar».

Mismas entradas → mismo número: la clasificación se guarda con la huella de
la evidencia (``fingerprint``) y se reutiliza mientras la huella no cambie.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

#: Sube cuando cambie cualquier tabla o fórmula: invalida la caché de clasificaciones.
RULES_VERSION = "sotp-rules-v2"
#: Versión de lo que se pide y se valida al CLASIFICAR (entra en la huella de la caché).
#: Las reglas numéricas (RULES_VERSION) no: el modelo se recalcula siempre con las vigentes.
CLASSIFIER_VERSION = "sotp-classifier-v1"

#: Años desde hoy hasta el año de madurez que se valora (fijo, no lo elige el modelo).
HORIZON_YEARS = 4

#: Estado de cada segmento → probabilidad de que llegue a la madurez valorada.
STATUS_PROBABILITY: dict[str, float] = {
    "idea": 0.15,
    "beta": 0.35,
    "contratado": 0.60,
    "comercial": 0.90,
}
STATUS_ORDER = ("idea", "beta", "contratado", "comercial")

#: Crecimiento anual máximo de unos ingresos ya facturados, por estado (tope del histórico).
STATUS_GROWTH_CAP: dict[str, float] = {"idea": 0.0, "beta": 0.0, "contratado": 0.25, "comercial": 0.15}

#: Tipo de negocio → (margen EBITDA a madurez, múltiplo EV/EBITDA a madurez). Referencias
#: de sector redondeadas y conservadoras; las mismas para cualquier empresa.
BUSINESS_TABLE: dict[str, tuple[float, float, str]] = {
    "telecom_mayorista": (0.45, 8.0, "operador mayorista / reparto de ingresos con operadoras"),
    "telecom_infraestructura": (0.55, 9.0, "torres, satélites o redes alquiladas"),
    "contratos_gobierno": (0.15, 11.0, "contratista de defensa o gobierno"),
    "hardware_equipos": (0.15, 9.0, "fabricación y venta de equipos"),
    "servicios_ingenieria": (0.12, 8.0, "servicios de ingeniería e integración"),
    "software_saas": (0.30, 18.0, "software por suscripción"),
    "internet_consumo": (0.30, 15.0, "plataformas y servicios de internet al consumidor"),
    "semiconductores": (0.35, 14.0, "diseño o fabricación de chips"),
    "industrial": (0.18, 10.0, "industria y bienes de equipo"),
    "consumo": (0.18, 12.0, "bienes de consumo y marcas"),
    "distribucion_minorista": (0.10, 9.0, "distribución y comercio minorista"),
    "salud_servicios": (0.15, 11.0, "servicios de salud y dispositivos"),
    "farmaceutica_biotech": (0.35, 12.0, "fármacos comercializados"),
    "servicios_financieros": (0.35, 10.0, "servicios financieros"),
    "energia_utilities": (0.40, 8.0, "energía y servicios públicos"),
    "materiales_mineria": (0.35, 6.0, "materias primas y minería"),
    "medios_contenido": (0.25, 10.0, "medios y contenidos"),
    "inmobiliario": (0.60, 15.0, "inmobiliario con rentas"),
    "otro": (0.20, 8.0, "otro (tabla por defecto)"),
}

ANCHOR_TYPES = ("reportado", "guia", "backlog", "contrato", "estimacion_analista")
#: Años en que se reparte un backlog o un contrato total cuando la cita no da el plazo.
DEFAULT_CONTRACT_YEARS = 5
#: Años de quema que se financian con acciones nuevas antes de que las partes la cubran.
BURN_YEARS = 2

#: Escenarios fijos (mismos para todas las empresas).
SCENARIOS = (
    {"key": "bear", "label": "Bajista (regla fija)", "revenue_factor": 0.5, "multiple_factor": 0.7, "delay_years": 2.0,
     "note": "Regla fija: la mitad de ingresos, múltiplos −30 % y dos años de retraso."},
    {"key": "bull", "label": "Alcista (regla fija)", "revenue_factor": 1.5, "multiple_factor": 1.2, "delay_years": 0.0,
     "note": "Regla fija: ingresos +50 % y múltiplos +20 %, sin retraso."},
)

_SCALE = {
    "billion": 1000.0, "billones": 1000.0, "bn": 1000.0, "b": 1000.0, "mil millones": 1000.0, "mm": 1.0,
    "million": 1.0, "millones": 1.0, "mn": 1.0, "m": 1.0, "thousand": 0.001, "k": 0.001,
}
_NUMBER = re.compile(
    r"(\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(mil millones|billion|billones|million|millones|thousand|bn|mn|mm|[bmk](?![a-z]))?",
    re.IGNORECASE,
)


def _as_float(token: str) -> float | None:
    token = token.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return float(re.sub(r"[.,]", "", token))
    if "," in token and "." in token:
        token = token.replace(",", "") if token.rfind(".") > token.rfind(",") else token.replace(".", "").replace(",", ".")
    else:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def figures_in_text(text: str) -> list[float]:
    """Cifras del texto en millones (y también tal cual, para cuentas de acciones o precios)."""
    out: list[float] = []
    for match in _NUMBER.finditer(text or ""):
        value = _as_float(match.group(1))
        if value is None:
            continue
        scale = (match.group(2) or "").lower()
        out.append(value * _SCALE[scale] if scale in _SCALE else value)
        if not scale:
            out.append(value / 1_000_000.0)  # unidades → millones (hechos SEC en dólares o acciones)
            out.append(value / 1_000.0)  # miles → millones (tablas de los 10-Q)
    return out


def figure_supported(amount: float, texts: Iterable[str], *, tolerance: float = 0.015) -> bool:
    """¿La cifra (en millones) aparece en alguno de los textos citados?"""
    if amount is None or not math.isfinite(amount) or amount <= 0:
        return False
    for text in texts:
        for value in figures_in_text(text):
            if value > 0 and abs(value - amount) <= tolerance * amount:
                return True
    return False


def evidence_text(data: Any) -> str:
    return data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)


#: Un ancla de ingresos tiene que hablar de ingresos o de un contrato de servicio...
REVENUE_WORDS = ("revenue", "revenues", "sales", "billings", "backlog", "contracted", "contract value", "bookings",
                 "service agreement", "commercial agreement", "ingresos", "ventas", "facturación", "cartera de pedidos",
                 "contrato de servicio", "acuerdo comercial")
#: ...y no de dinero que entra sin venta: financiación, préstamo, subvención o inversión de un tercero.
FUNDING_WORDS = ("funding", "financing", "loan", "grant", "subsidy", "investment in", "equity investment",
                 "non-dilutive", "prepayment", "financiación", "financiacion", "préstamo", "prestamo", "subvención",
                 "subvencion", "inversión de", "no dilutiv")
ANCHOR_WINDOW = 240


def _windows_with(amount: float, text: str) -> list[str]:
    out = []
    for match in _NUMBER.finditer(text or ""):
        value = _as_float(match.group(1))
        if value is None:
            continue
        scale = (match.group(2) or "").lower()
        candidates = [value * _SCALE[scale]] if scale in _SCALE else [value, value / 1_000_000.0, value / 1_000.0]
        if any(c > 0 and abs(c - amount) <= 0.015 * amount for c in candidates):
            # La frase que contiene la cifra (hasta ANCHOR_WINDOW caracteres a cada lado).
            lo = max(0, match.start() - ANCHOR_WINDOW)
            hi = match.end() + ANCHOR_WINDOW
            before = max(text.rfind(". ", lo, match.start()), text.rfind("\n", lo, match.start()))
            after = [i for i in (text.find(". ", match.end(), hi), text.find("\n", match.end(), hi)) if i != -1]
            out.append(text[(before + 1) if before != -1 else lo: min(after) if after else hi])
    return out


def revenue_context(amount: float, texts: Iterable[str], quote: str | None = None) -> str | None:
    """None si la cifra se cita como ingresos o contrato; si no, el motivo (financiación o sin palabra de ingresos)."""
    pieces = [quote] if quote else []
    for text in texts:
        pieces += _windows_with(amount, text)
    blob = " ".join(p for p in pieces if p).casefold()
    if not blob:
        return "sin contexto de la cifra"
    funding = [w for w in FUNDING_WORDS if w in blob]
    if funding and not (quote and any(w in quote.casefold() for w in REVENUE_WORDS)
                        and not any(w in quote.casefold() for w in FUNDING_WORDS)):
        return f"la cifra es financiación o inversión ({funding[0]}), no ingresos"
    if not any(w in blob for w in REVENUE_WORDS):
        return "el pasaje citado no habla de ingresos ni de un contrato de servicio"
    return None


#: Ancla que no es una previsión de ingresos: el segmento puede quedar infravalorado.
NON_FORECAST_ANCHORS = ("reportado", "backlog", "contrato")


def fingerprint(evidence: Iterable[Mapping[str, Any]], *, prompt_version: str | None) -> dict[str, Any]:
    """Huella de las entradas del modelo (sin el precio: el % frente al precio lo rehace el código)."""
    items = []
    for item in evidence:
        if item.get("tool") == "sotp_anchors":
            data = item.get("data") or {}
            data = {k: v for k, v in data.items() if k not in ("price", "price_as_of")} if isinstance(data, dict) else data
        else:
            data = item.get("data")
        source = item.get("source") or {}
        key = "|".join(str(source.get(k) or "") for k in ("table", "id", "document_id", "url", "date", "title"))
        items.append({"key": key, "tool": item.get("tool"), "data": data})
    items.sort(key=lambda x: (str(x["tool"]), x["key"], evidence_text(x["data"])))
    blob = json.dumps({"rules": CLASSIFIER_VERSION, "prompt": prompt_version, "items": items}, ensure_ascii=False,
                      sort_keys=True, default=str)
    return {
        "hash": hashlib.sha256(blob.encode()).hexdigest(),
        "rules_version": CLASSIFIER_VERSION,
        "prompt_version": prompt_version,
        "sources": sorted({f"{i['tool']}:{i['key']}" for i in items}),
    }


def fingerprint_changes(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> list[str]:
    """Qué dato nuevo cambió la huella (fuentes nuevas o retiradas, reglas o prompt)."""
    if not previous:
        return []
    out = []
    if previous.get("rules_version") != current.get("rules_version"):
        out.append(f"reglas {previous.get('rules_version')} → {current.get('rules_version')}")
    if previous.get("prompt_version") != current.get("prompt_version"):
        out.append(f"prompt {previous.get('prompt_version')} → {current.get('prompt_version')}")
    before, after = set(previous.get("sources") or []), set(current.get("sources") or [])

    def title(key: str) -> str:
        return key.split("|")[-1] or key

    def date_of(key: str) -> str:
        parts = key.split("|")
        return parts[-2] if len(parts) >= 2 else ""

    added, removed = sorted(after - before), sorted(before - after)
    removed_titles = {title(k) for k in removed}
    updated = [k for k in added if title(k) in removed_titles]
    out += [f"actualizado: {title(k)}" + (f" ({date_of(k)})" if date_of(k) else "") for k in updated][:6]
    out += [f"nuevo: {title(k)}" for k in added if k not in updated][:8]
    updated_titles = {title(k) for k in updated}
    out += [f"retirado: {title(k)}" for k in removed if title(k) not in updated_titles][:4]
    if not out and previous.get("hash") != current.get("hash"):
        out.append("cambió el contenido de una fuente ya usada (hechos SEC, documentos o noticias)")
    return out


def pct(value: float) -> str:
    """Porcentaje a la española («15 %»)."""
    return f"{value * 100:.0f} %"


def _fmt(value: float) -> str:
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def revenue_rule(anchor: Mapping[str, Any], status: str, *, base_year: int, valuation_year: int,
                 historical_growth: float | None) -> tuple[float, str]:
    """Ingresos en el año de madurez desde el ancla citada. Devuelve (millones, fórmula)."""
    kind = anchor["type"]
    amount = float(anchor["amount_millions"])
    period = anchor.get("period") or "anual"
    year = int(anchor.get("year") or base_year)
    if kind in ("backlog", "contrato"):
        years = int(anchor.get("years") or DEFAULT_CONTRACT_YEARS)
        years = max(1, min(years, 15))
        value = amount / years
        return value, f"{kind} {_fmt(amount)} M ÷ {years} años = {_fmt(value)} M/año (plano)"
    annual = amount * 4 if period == "trimestral" else amount
    base_txt = f"{_fmt(amount)} M × 4 trimestres" if period == "trimestral" else f"{_fmt(amount)} M"
    if kind == "reportado":
        cap = STATUS_GROWTH_CAP.get(status, 0.0)
        growth = cap if historical_growth is None else max(0.0, min(historical_growth, cap))
        years = max(0, valuation_year - year)
        value = annual * (1 + growth) ** years
        hist = "sin histórico" if historical_growth is None else f"histórico {pct(historical_growth)}"
        return value, (f"{base_txt} ({year}) × (1 + {pct(growth)})^{years} = {_fmt(value)} M "
                       f"(crecimiento: {hist}, tope {pct(cap)} por estado «{status}»)")
    # guía de la empresa o estimación de analista para un año concreto
    if year > valuation_year:
        span = max(1, year - base_year)
        value = annual * max(0, valuation_year - base_year) / span
        return value, f"{base_txt} en {year} × {valuation_year - base_year}/{span} (rampa lineal) = {_fmt(value)} M"
    return annual, f"{base_txt} en {year}, plano hasta {valuation_year} = {_fmt(annual)} M"


def historical_growth(revenue_actuals: Iterable[Mapping[str, Any]]) -> float | None:
    """CAGR de ingresos anuales SEC (hasta 3 años); None si no hay dos años positivos."""
    rows = sorted((r for r in revenue_actuals if (r.get("revenue_millions") or 0) > 0),
                  key=lambda r: str(r.get("period_end")))[-4:]
    if len(rows) < 2:
        return None
    first, last = float(rows[0]["revenue_millions"]), float(rows[-1]["revenue_millions"])
    years = len(rows) - 1
    return (last / first) ** (1 / years) - 1


def code_dilution(anchors: Mapping[str, Any], years: int) -> list[dict[str, Any]]:
    """Dilución que sale de los datos: SBC al precio de hoy y el hueco de financiación si quema caja."""
    out: list[dict[str, Any]] = []
    price = anchors.get("price")
    url = f"/research/{anchors.get('ticker')}?view=valuation"
    if not price or price <= 0:
        return out
    sbc = anchors.get("sbc_annual_millions")
    if sbc and sbc > 0:
        shares = sbc * years / price
        out.append({"label": "Remuneración en acciones (SBC) hasta el año valorado", "shares": shares,
                    "why": {"shares": f"SBC {_fmt(sbc)} M$/año × {years} años ÷ precio {price:.2f} = {_fmt(shares)} M"},
                    "sources": [{"label": "SBC anual (SEC)", "url": url, "date": anchors.get("sbc_period_end")}]})
    burn = anchors.get("annual_burn_millions")
    if anchors.get("burns_cash") and burn and burn > 0:
        liquid = (anchors.get("cash_millions") or 0.0) + (anchors.get("short_term_investments_millions") or 0.0)
        gap = burn * BURN_YEARS - liquid
        if gap > 0:
            shares = gap / price
            out.append({"label": "Ampliaciones para cubrir la quema", "shares": shares,
                        "why": {"shares": (f"(quema {_fmt(burn)} M$/año × {BURN_YEARS} años − liquidez {_fmt(liquid)} M) "
                                           f"÷ precio {price:.2f} = {_fmt(shares)} M")},
                        "sources": [{"label": "Flujo de caja libre anual (SEC)", "url": url,
                                     "date": anchors.get("burn_period_end")}]})
        else:
            out.append({"label": "Ampliaciones para cubrir la quema", "shares": 0.0,
                        "why": {"shares": (f"quema {_fmt(burn)} M$/año × {BURN_YEARS} años = {_fmt(burn * BURN_YEARS)} M "
                                           f"≤ liquidez {_fmt(liquid)} M: sin ampliación por regla")},
                        "sources": [{"label": "Flujo de caja libre anual (SEC)", "url": url,
                                     "date": anchors.get("burn_period_end")}]})
    return out


def conservative_status(statuses: Iterable[str]) -> str:
    ranks = [STATUS_ORDER.index(s) for s in statuses if s in STATUS_ORDER]
    return STATUS_ORDER[min(ranks)] if ranks else "idea"


__all__ = [
    "CLASSIFIER_VERSION",
    "FUNDING_WORDS",
    "NON_FORECAST_ANCHORS",
    "REVENUE_WORDS",
    "revenue_context",
    "ANCHOR_TYPES",
    "BURN_YEARS",
    "BUSINESS_TABLE",
    "DEFAULT_CONTRACT_YEARS",
    "HORIZON_YEARS",
    "RULES_VERSION",
    "SCENARIOS",
    "STATUS_GROWTH_CAP",
    "STATUS_ORDER",
    "STATUS_PROBABILITY",
    "code_dilution",
    "conservative_status",
    "evidence_text",
    "figure_supported",
    "figures_in_text",
    "fingerprint",
    "fingerprint_changes",
    "historical_growth",
    "pct",
    "revenue_rule",
]
