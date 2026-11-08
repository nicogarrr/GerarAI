"""«Valorador SOTP»: el experto del equipo que propone el desglose por partes.

Nico (8-nov-2026, 11:11): el ejemplo de ASTS que pegó «son un ejemplo de
valoración… quiero que quede ahí con nuestros agentes expertos y demás, saca una
valoración más realista». Y a las 11:15: que salga al generar la tesis.

Es un rol más del equipo de expertos (``expert_team``), con sus mismas piezas:
herramientas de SOLO lectura filtradas por tenant, el ledger de evidencia de
la corrida (``ev-N``), el prompt versionado (``expert_sotp``) y el razonador
de la app (``provider_reasoner``: el LLM configurado, con presupuesto).

Reparto de papeles (general, nunca por ticker):

* Determinista («las matemáticas están detrás de todo», Nico 8-nov-2026): el
  MODELO solo clasifica — qué segmentos hay, su estado (idea / beta /
  contratado / comercial), su tipo de negocio y la cifra de la evidencia que
  ancla sus ingresos, con su cita. Todo número lo pone el CÓDIGO
  (``sotp_rules``): probabilidad por estado, margen y múltiplo por tipo,
  ingresos por regla desde el ancla, acciones/caja/deuda/SBC/quema de la SEC,
  CAPM de ``resolve_rates`` (#4729), escenarios fijos. Cada cifra lleva su
  fórmula (traza) en «¿De dónde sale?».
* Una cifra del modelo que no aparece en la evidencia citada no se usa: el
  segmento pasa a «sin valorar». Estado o tipo fuera de tabla: reintento.
* Caché por huella: misma evidencia + mismo prompt + mismas reglas → la misma
  clasificación guardada, sin llamar al modelo. Con varias lecturas, gana la
  más conservadora (la de menor valor) y se guardan todas.

Lo que guarda es un BORRADOR etiquetado «propuesta de los agentes» con fecha y
precio, en ``declared_input_values`` (``sotp_user_model``, segmento
``agents``): no entra en ningún motor ni en el valor justo.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.llm.json import parse_json_response
from app.models.entities import Company
from app.services.expert_team import sotp_rules
from app.services.expert_team.experts import ExpertSpec, Reasoner, gather_evidence
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec
from app.valuation.sotp import run_user_sotp

logger = logging.getLogger(__name__)

SOTP_VALUER_NAME = "valorador_sotp"
SOTP_VALUER_TOOLS: tuple[str, ...] = (
    "sotp_anchors",
    "share_count_documents",
    "balance_asset_documents",
    "analyst_estimates",
    "companies_house",
    "value_drivers",
    "financial_facts",
    "valuation_engine",
    "company_documents",
    "news_events",
    "risk_events",
)
MAX_ATTEMPTS = 2
#: Rechazo por contenido (forma válida, ninguna cifra comprobable): con la misma evidencia se repetiría.
NO_SEGMENTS = "ningún segmento tiene una cifra de ingresos comprobable en la evidencia"
MAX_SEGMENTS = 12
MAX_ASSET_PARTS = 4
AGENTS_LABEL = "Propuesta de los agentes"
AGENTS_AUTHOR = "Agentes expertos de GerarAI"

SOTP_CONTRACT = (
    'Responde SOLO con JSON: {"summary": str (máx. 5 frases, SIN cifras: qué segmentos pesan, qué está sin '
    'probar y qué dato lo cambiaría), "segments": [{"group": str, "name": str, "status": "idea"|"beta"|'
    '"contratado"|"comercial", "why_status": str (por qué ese estado, con la cita), "business_type": uno de '
    + ", ".join(f'"{k}"' for k in sotp_rules.BUSINESS_TABLE)
    + ', "anchor": {"type": "reportado"|"guia"|"backlog"|"contrato"|"estimacion_analista", "amount_millions": '
    'número (millones de la divisa, COPIADO de la evidencia), "period": "anual"|"trimestral"|"total", "year": '
    'entero|null (año al que se refiere la cifra), "years": entero|null (plazo de un contrato o backlog si la '
    'cita lo da), "quote": str (frase exacta de la evidencia que contiene la cifra), "citation": "ev-N"} | null, '
    '"guidance_anchor": {mismo formato, "type": "guia"|"estimacion_analista"} | null (si el ancla no es una previsión '
    'y la empresa o un analista dan una cifra de ingresos futuros para ese segmento)}], '
    '"assets": [{"name": str, "status": ..., "value_millions": número copiado de la evidencia, "quote": str, '
    '"citation": "ev-N", "why": str, "mhz": número de MHz COPIADO de la evidencia | null (solo espectro: lo valora '
    'el código con transacciones comparables), "band": "mss" (satélite, con o sin uso terrestre) | "terrestre" | '
    'null}], "dilution": [{"label": str, "shares_millions": número de acciones NUEVAS '
    'copiado de la evidencia (otras clases canjeables, emisiones pactadas, warrants), "quote": str, "citation": '
    '"ev-N", "why": str}]}. No pongas probabilidades, márgenes, múltiplos, años de madurez ni tasas: los pone el '
    "código con tablas fijas. Un segmento sin cifra en la evidencia va con \"anchor\": null (queda «sin valorar»). "
    "No incluyas la caja, la deuda, los convertibles ni la remuneración en acciones: también los pone el código."
)


def _verified(raw: Mapping[str, Any], amount_key: str, ledger: EvidenceLedger, expert: str
              ) -> tuple[float | None, list[dict[str, Any]], str | None, str | None]:
    """(cifra, fuentes, cita textual, motivo si no vale). La cifra tiene que estar en la evidencia citada."""
    amount = _num(raw.get(amount_key))
    cid = raw.get("citation")
    cites = [cid] if isinstance(cid, str) else [c for c in raw.get("citations") or () if isinstance(c, str)]
    quote = _text(raw.get("quote"), 240) or None
    if amount is None or amount <= 0:
        return None, [], quote, "sin cifra"
    items = [ledger.get(c) for c in cites]
    if not cites or any(ev is None or ev.expert != expert for ev in items):
        return None, [], quote, "sin cita válida de esta corrida"
    texts = [sotp_rules.evidence_text(ev.data) for ev in items if ev is not None]
    if not sotp_rules.figure_supported(amount, texts):
        return None, [], quote, f"la cifra {amount:,.1f} no aparece en la evidencia citada"
    return amount, _sources_for(cites, ledger), quote, None


def _cited_texts(raw: Mapping[str, Any], ledger: EvidenceLedger) -> list[str]:
    cid = raw.get("citation")
    cites = [cid] if isinstance(cid, str) else [c for c in raw.get("citations") or () if isinstance(c, str)]
    return [sotp_rules.evidence_text(ev.data) for c in cites if (ev := ledger.get(c)) is not None]


_DIGITS_OUTSIDE_YEARS = re.compile(r"(?<!\d)(?!(?:19|20)\d{2}(?!\d))\d")


def _summary_without_numbers(text: str) -> str:
    """El texto explica, no aporta cifras: fuera las frases con números (salvo años)."""
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    return " ".join(s for s in sentences if s and not _DIGITS_OUTSIDE_YEARS.search(s))[:1500]


def parse_classification(parsed: Any, ledger: EvidenceLedger, *, expert: str = SOTP_VALUER_NAME
                         ) -> tuple[dict[str, Any] | None, list[str]]:
    """JSON del modelo → clasificación validada (sin un solo número del modelo sin comprobar).

    Problemas de forma (estado o tipo fuera de tabla, sin segmentos): None + problemas (reintento).
    Cifras que no se pueden comprobar: el elemento pasa a ``unvalued`` con el motivo.
    """
    if not isinstance(parsed, dict):
        return None, ["la respuesta no es un objeto JSON"]
    problems: list[str] = []
    raw_segments = parsed.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None, ["faltan los segmentos («segments»)"]
    if len(raw_segments) > MAX_SEGMENTS:
        problems.append(f"máximo {MAX_SEGMENTS} segmentos")
    segments: list[dict[str, Any]] = []
    unvalued: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_segments[:MAX_SEGMENTS]):
        if not isinstance(raw, dict):
            problems.append(f"segmento {index + 1}: no es un objeto")
            continue
        name = _text(raw.get("name"), 120)
        label = f"«{name}»" if name else f"segmento {index + 1}"
        status = raw.get("status")
        btype = raw.get("business_type")
        if not name:
            problems.append(f"{label}: falta el nombre")
        if status not in sotp_rules.STATUS_PROBABILITY:
            problems.append(f"{label}: estado {status!r} fuera de la tabla")
        if btype not in sotp_rules.BUSINESS_TABLE:
            problems.append(f"{label}: tipo de negocio {btype!r} fuera de la tabla")
        anchor_raw = raw.get("anchor") if isinstance(raw.get("anchor"), dict) else None
        entry = {"group": _text(raw.get("group"), 60) or None, "name": name, "status": status,
                 "business_type": btype, "why_status": _text(raw.get("why_status"), 200)}
        if anchor_raw is None:
            unvalued.append({"name": name, "status": status, "reason": "sin cifra de ingresos en la evidencia"})
            continue
        kind = anchor_raw.get("type")
        if kind not in sotp_rules.ANCHOR_TYPES:
            problems.append(f"{label}: tipo de ancla {kind!r} fuera de la tabla")
            continue
        amount, sources, quote, reason = _verified(anchor_raw, "amount_millions", ledger, expert)
        if reason is None and amount is not None:
            reason = sotp_rules.revenue_context(amount, _cited_texts(anchor_raw, ledger), quote)
        if reason:
            unvalued.append({"name": name, "status": status, "reason": f"ancla {kind}: {reason}"})
            continue
        period = anchor_raw.get("period") if anchor_raw.get("period") in ("anual", "trimestral", "total") else "anual"
        year = _num(anchor_raw.get("year"))
        years = _num(anchor_raw.get("years"))
        entry["anchor"] = {"type": kind, "amount_millions": amount, "period": period,
                           "year": int(year) if year else None, "years": int(years) if years else None,
                           "quote": quote, "sources": sources}
        guidance = raw.get("guidance_anchor") if isinstance(raw.get("guidance_anchor"), dict) else None
        if guidance and guidance.get("type") in ("guia", "estimacion_analista"):
            g_amount, g_sources, g_quote, g_reason = _verified(guidance, "amount_millions", ledger, expert)
            if g_reason is None and g_amount is not None:
                g_reason = sotp_rules.revenue_context(g_amount, _cited_texts(guidance, ledger), g_quote)
            if g_reason is None:
                g_year = _num(guidance.get("year"))
                entry["guidance_anchor"] = {"type": guidance["type"], "amount_millions": g_amount, "period": "anual",
                                            "year": int(g_year) if g_year else None, "years": None,
                                            "quote": g_quote, "sources": g_sources}
        segments.append(entry)
    assets: list[dict[str, Any]] = []
    for raw in (parsed.get("assets") or [])[:MAX_ASSET_PARTS]:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("name"), 120)
        status = raw.get("status") if raw.get("status") in sotp_rules.STATUS_PROBABILITY else "idea"
        # Espectro con sus MHz en la cita: lo valora el código por comparables (sotp_rules.spectrum_value).
        if _num(raw.get("mhz")) is not None:
            mhz, sources, quote, reason = _verified(raw, "mhz", ledger, expert)
            if not reason and mhz is not None:
                band = raw.get("band") if raw.get("band") in sotp_rules.SPECTRUM_BANDS else "mss"
                assets.append({"name": name, "status": status, "value_millions": None, "mhz": mhz, "band": band,
                               "quote": quote, "why": _text(raw.get("why"), 200), "sources": sources})
                continue
        value, sources, quote, reason = _verified(raw, "value_millions", ledger, expert)
        if reason:
            unvalued.append({"name": name or "activo", "status": status, "reason": f"activo: {reason}"})
            continue
        assets.append({"name": name, "status": status, "value_millions": value, "quote": quote,
                       "why": _text(raw.get("why"), 200), "sources": sources})
    dilution: list[dict[str, Any]] = []
    for raw in parsed.get("dilution") or []:
        if not isinstance(raw, dict):
            continue
        label = _text(raw.get("label"), 120) or "Dilución"
        shares, sources, quote, reason = _verified(raw, "shares_millions", ledger, expert)
        reason = reason or sotp_rules.dilution_reason(label, quote)
        if reason:
            unvalued.append({"name": label, "status": None, "reason": f"dilución: {reason}"})
            continue
        dilution.append({"label": label, "shares_millions": shares, "quote": quote,
                         "why": _text(raw.get("why"), 200), "sources": sources})
    if problems:
        return None, problems
    if not segments:
        return None, [NO_SEGMENTS]
    return {
        "segments": segments,
        "assets": assets,
        "dilution": dilution,
        "unvalued": unvalued,
        "summary": _summary_without_numbers(_text(parsed.get("summary"), 2000)),
    }, []


def _cut(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_model(classification: Mapping[str, Any], anchors: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Clasificación validada + cifras del código → modelo SOTP (función pura: mismas entradas, mismo modelo)."""
    from app.valuation.sotp import normalize_user_sotp

    problems: list[str] = []
    if anchors.get("discount_rate") is None:
        problems.append("sin tasa de descuento CAPM de GerarAI para esta empresa")
    if not anchors.get("shares_current_millions"):
        problems.append("sin acciones actuales de la SEC")
    if problems:
        return None, problems
    base_year = int(anchors["base_year"])
    year = base_year + sotp_rules.HORIZON_YEARS
    growth = sotp_rules.historical_growth(anchors.get("revenue_actuals") or [])
    burns_cash = anchors.get("burns_cash") is True
    parts: list[dict[str, Any]] = []
    warnings: list[str] = []
    unvalued = list(classification.get("unvalued") or [])
    if anchors.get("price_fx_note"):
        warnings.append(f"Cifras en {anchors.get('currency')} (moneda de los informes SEC); el precio se convierte: "
                        f"{anchors['price_fx_note']}.")
    if anchors.get("debt_millions") is None:
        warnings.append("Falta la deuda en los datos SEC: «caja menos deuda» no la resta y el valor puede estar "
                        "sobreestimado.")
    if anchors.get("discount_rate_source") == "tag_default":
        warnings.append("Sin CAPM calculable para esta empresa (faltan beta o tipos): se usa la tasa por defecto.")
    if anchors.get("shares_basis") != "shares_outstanding":
        warnings.append("Faltan clases de acciones: la SEC solo da la media diluida de la clase cotizada; "
                        "si hay otras clases canjeables, el recuento diluido es más alto y el $/acción más bajo.")
    discount = (1 + float(anchors["discount_rate"])) ** (year - base_year)
    shares_total = float(anchors["shares_current_millions"])
    for seg in classification.get("segments") or []:
        status, btype, anchor = seg["status"], seg["business_type"], seg["anchor"]
        # Las reglas vigentes también valen para una clasificación guardada (la cita se conserva).
        if anchor.get("quote"):
            # Al clasificar ya se exigió hablar de ingresos con el pasaje entero; aquí solo queda la cita.
            reason = sotp_rules.funding_reason(anchor["quote"])
            if reason:
                unvalued.append({"name": seg["name"], "status": status, "reason": f"ancla {anchor['type']}: {reason}"})
                continue
        anchor, period_note = sotp_rules.quarterly_report_anchor(anchor)
        margin, multiple, desc = sotp_rules.BUSINESS_TABLE[btype]
        probability = sotp_rules.STATUS_PROBABILITY[status]
        revenue, formula = sotp_rules.revenue_rule(anchor, status, base_year=base_year, valuation_year=year,
                                                   historical_growth=growth)
        if anchor["type"] in sotp_rules.NON_FORECAST_ANCHORS and status != "comercial":
            guidance = seg.get("guidance_anchor")
            if guidance:
                g_rev, g_formula = sotp_rules.revenue_rule(guidance, status, base_year=base_year, valuation_year=year,
                                                           historical_growth=growth)
                g_ps = g_rev * margin * multiple * probability / discount / shares_total
                warnings.append(f"«{seg['name']}»: infravalorado por falta de estimaciones (ancla {anchor['type']}); "
                                f"con la guía de la empresa ({g_formula}) pesaría {g_ps:,.2f} $/acción antes de dilución.")
            else:
                warnings.append(f"«{seg['name']}»: infravalorado por falta de estimaciones: su ancla es {anchor['type']}, "
                                "no una previsión de ingresos, y no hay guía de la empresa citada.")
        quote = f" Cita: «{anchor['quote']}»" if anchor.get("quote") else ""
        if period_note:
            quote = f" ({period_note}).{quote}"
        parts.append({
            "group": seg.get("group"),
            "name": seg["name"],
            "kind": "operating",
            "commercial": status == "comercial",
            "revenue": revenue,
            "ebitda_margin": margin,
            "multiple": multiple,
            "probability": probability,
            "why": {
                "revenue": _cut(f"Regla «{anchor['type']}»: {formula}.{quote}"),
                "margin": f"Tabla «{btype}» ({desc}): margen EBITDA {sotp_rules.pct(margin)} a madurez.",
                "multiple": f"Tabla «{btype}»: {multiple:g}x EBITDA a madurez.",
                "probability": _cut(f"Estado «{status}» → {sotp_rules.pct(probability)} (tabla fija). {seg.get('why_status') or ''}"),
            },
            "sources": anchor.get("sources") or [],
        })
    for asset in classification.get("assets") or []:
        probability = sotp_rules.STATUS_PROBABILITY[asset["status"]]
        quote = f" Cita: «{asset['quote']}»" if asset.get("quote") else ""
        if asset.get("mhz"):
            low, value, high, formula, comps = sotp_rules.spectrum_value(float(asset["mhz"]), asset.get("band") or "mss")
            parts.append({
                "group": "Activos",
                "name": asset["name"],
                "kind": "asset",
                "value": value,
                "discounted": False,
                "probability": probability,
                "why": {"value": _cut(f"Regla «espectro por comparables»: {formula}. Bajo {low:,.0f} M / alto "
                                      f"{high:,.0f} M.{quote}", 600),
                        "probability": f"Estado «{asset['status']}» → {sotp_rules.pct(probability)} (tabla fija)."},
                "sources": (asset.get("sources") or []) + comps,
            })
            continue
        parts.append({
            "group": "Activos",
            "name": asset["name"],
            "kind": "asset",
            "value": asset["value_millions"],
            "discounted": False,
            "probability": probability,
            "why": {"value": _cut(f"{asset['value_millions']:,.1f} M copiados de la evidencia × probabilidad ÷ acciones "
                                  f"(sin descontar: es valor de hoy).{quote}"),
                    "probability": f"Estado «{asset['status']}» → {sotp_rules.pct(probability)} (tabla fija)."},
            "sources": asset.get("sources") or [],
        })
    cash = anchors.get("cash_millions")
    short_term = anchors.get("short_term_investments_millions")
    debt = anchors.get("debt_millions")
    if cash is not None or debt is not None:
        liquid = (cash or 0.0) + (short_term or 0.0)
        liquid_text = f"caja {cash or 0:,.0f} M" + (f" + inversiones a corto {short_term:,.0f} M" if short_term else "")
        parts.append({
            "group": "Balance de hoy",
            "name": "Caja menos deuda (último balance SEC)",
            "kind": "asset",
            "value": liquid - (debt or 0.0),
            "discounted": False,
            "probability": 1.0,
            "why": {"value": ((f"{liquid_text} − deuda SIN DATO (no restada) = {liquid:,.0f} M a " if debt is None else
                               f"{liquid_text} − deuda {debt:,.0f} M = {liquid - debt:,.0f} M a ")
                              + f"{anchors.get('balance_period_end') or 'N/D'} (SEC; la deuda incluye los convertibles).")},
            "sources": [{"label": "Acciones, caja y deuda (SEC)", "url": f"/research/{anchors['ticker']}?view=valuation",
                         "date": anchors.get("balance_period_end")}],
        })
    dilution = [{"label": d["label"], "shares": d["shares_millions"],
                 "why": {"shares": _cut(f"{d['shares_millions']:,.1f} M copiados de la evidencia."
                                        + (f" Cita: «{d['quote']}»" if d.get("quote") else ""))},
                 "sources": d.get("sources") or []}
                for d in classification.get("dilution") or []
                if sotp_rules.dilution_reason(d.get("label"), d.get("quote")) is None]
    dilution += sotp_rules.code_dilution(anchors, sotp_rules.HORIZON_YEARS)
    if burns_cash and not any(d["shares"] > 0 for d in dilution):
        dilution.append({"label": "Sin dilución calculable", "shares": 0.0,
                         "why": {"shares": "La empresa quema caja pero no hay SBC ni hueco de financiación en los datos."}})
    rate = float(anchors["discount_rate"])
    model_raw = {
        "currency": anchors.get("currency"),
        "base_year": base_year,
        "valuation_year": year,
        "discount_rate": rate,
        "discount_rate_source": (f"Tasa por defecto (sin CAPM calculable): {rate:.1%}"
                                 if anchors.get("discount_rate_source") == "tag_default" else
                                 f"CAPM de GerarAI ({anchors.get('discount_rate_source') or 'resolve_rates'}): {rate:.1%}"),
        "shares_current": anchors["shares_current_millions"],
        "shares_why": {"shares": f"{anchors['shares_current_millions']:,.1f} M ({anchors.get('shares_basis')}, "
                                 f"SEC {anchors.get('shares_period_end') or ''}) + la dilución de abajo."},
        "dilution": dilution,
        "parts": parts,
        "scenarios": [dict(s) for s in sotp_rules.SCENARIOS],
        "author": AGENTS_AUTHOR,
        "source": (f"{AGENTS_LABEL} ({anchors.get('today')}, precio {anchors.get('price')} "
                   f"{anchors.get('currency') or ''}). Clasificación de los agentes; cifras por reglas fijas "
                   f"({sotp_rules.RULES_VERSION}), no validadas contra histórico."),
        "summary": classification.get("summary") or None,
        "unvalued": unvalued,
        "warnings": warnings,
        "rules_version": sotp_rules.RULES_VERSION,
    }
    return normalize_user_sotp(model_raw)


def parse_proposal(parsed: Any, ledger: EvidenceLedger, anchors: Mapping[str, Any], *,
                   expert: str = SOTP_VALUER_NAME) -> tuple[dict[str, Any] | None, list[str]]:
    """Clasificación del modelo → modelo SOTP (``parse_classification`` + ``build_model``)."""
    classification, problems = parse_classification(parsed, ledger, expert=expert)
    if classification is None:
        return None, problems
    return build_model(classification, anchors)


def _classification_key(classification: Mapping[str, Any]) -> list[tuple]:
    return sorted(
        (str(s.get("name")), s.get("status"), s.get("business_type"), s["anchor"]["type"],
         round(float(s["anchor"]["amount_millions"]), 3))
        for s in classification.get("segments") or []
    )


@dataclass
class SotpProposalResult:
    """Qué hizo el valorador SOTP en una corrida."""

    status: str  # disabled | no_company | no_data | no_price | stored | rejected | error
    model: dict[str, Any] | None = None
    value_per_share: float | None = None
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_version: str | None = None
    tool_errors: list[str] = field(default_factory=list)
    row_id: int | None = None
    anchors: dict[str, Any] = field(default_factory=dict)
    fingerprint: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None
    cache_hit: bool = False
    readings: list[dict[str, Any]] = field(default_factory=list)
    readings_differ: bool = False
    headlines: list[dict[str, Any]] = field(default_factory=list)
    narrative: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value_per_share": self.value_per_share,
            "problems": list(self.problems)[:20],
            "llm_calls": self.llm_calls,
            "prompt_version": self.prompt_version,
            "tool_errors": list(self.tool_errors),
            "row_id": self.row_id,
            "cache_hit": self.cache_hit,
            "fingerprint": (self.fingerprint or {}).get("hash"),
            "readings": self.readings,
            "readings_differ": self.readings_differ,
            "narrative": (self.narrative or {}).get("status"),
        }


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _millions(point: Mapping[str, Any] | None) -> float | None:
    value = _num((point or {}).get("value"))
    return None if value is None else value / 1_000_000.0


def _fact_millions(db: Session, company: Company, metric: str, *, period_prefix: str | None = None,
                   annual: bool = False, unit: str = "USD") -> tuple[float | None, str | None]:
    """Último hecho SEC en millones (del mismo cierre si se da ``period_prefix``; anual si ``annual``)."""
    from sqlalchemy import desc, select

    from app.models import FinancialFact

    query = select(FinancialFact).where(FinancialFact.company_id == company.id, FinancialFact.metric == metric)
    if period_prefix:
        query = query.where(FinancialFact.period.like(f"{period_prefix}%"))
    if annual:
        query = query.where(FinancialFact.period.like("%:FY"))
    for row in db.scalars(query.order_by(desc(FinancialFact.period), desc(FinancialFact.id))).all():
        if row.value is not None and str(row.unit or unit).upper().startswith(unit.upper()):
            return float(row.value) / 1_000_000.0, str(row.period).split(":")[0]
    return None, None


def _capm_cost_of_equity(db: Session, company: Company) -> tuple[float, str] | None:
    from sqlalchemy import desc, select

    from app.models import FinancialFact

    values: dict[str, float] = {}
    for metric in ("risk_free_rate", "beta", "equity_risk_premium", "country_risk_premium"):
        row = db.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company.id, FinancialFact.metric == metric)
            .order_by(desc(FinancialFact.period), desc(FinancialFact.id))
        ).first()
        if row is not None and row.value is not None:
            values[metric] = float(row.value)
    if not all(k in values for k in ("risk_free_rate", "beta", "equity_risk_premium")):
        return None
    rate = values["risk_free_rate"] + values["beta"] * values["equity_risk_premium"] + values.get("country_risk_premium", 0.0)
    if not (0.03 <= rate <= 0.4):
        return None
    return rate, (f"capm_cost_of_equity: {values['risk_free_rate']:.2%} + {values['beta']:.2f} × "
                  f"{values['equity_risk_premium']:.2%} + {values.get('country_risk_premium', 0.0):.2%}")


def _reporting_currency(db: Session, company: Company) -> str | None:
    from sqlalchemy import desc, select

    from app.models import FinancialFact

    unit = db.scalar(
        select(FinancialFact.unit).where(FinancialFact.company_id == company.id,
                                         FinancialFact.metric.in_(("revenue", "cash_and_equivalents")))
        .order_by(desc(FinancialFact.period), desc(FinancialFact.id)).limit(1)
    )
    unit = str(unit or "").strip().upper()
    return unit if len(unit) == 3 and unit.isalpha() else None


def sotp_anchors(db: Session, company: Company, *, today: date | None = None) -> dict[str, Any]:
    """Cifras que fija el código (en millones), con su procedencia. Pura lectura."""
    from app.services.analyst_report import build_company_report
    from app.services.user_sotp_service import _base_rate, _price
    from app.valuation.engines.base import resolve_rates

    today = today or date.today()
    report = build_company_report(db, company, today=today)
    market = report.get("market") or {}
    price, price_currency, price_as_of = _price(db, company)
    shares_point = market.get("shares_outstanding") or market.get("shares_diluted")
    shares_basis = "shares_outstanding" if market.get("shares_outstanding") else "shares_diluted"
    # Portada SEC por clase (dei:EntityCommonStockSharesOutstanding, suma de clases del carril
    # per-clase): es el recuento de TODAS las clases; la media diluida es solo la clase cotizada.
    all_classes, all_classes_end = _fact_millions(db, company, "shares_outstanding", unit="SHARES")
    if all_classes and (shares_basis != "shares_outstanding" or str(all_classes_end) > str((shares_point or {}).get("period_end") or "")):
        shares_point = {"value": all_classes * 1_000_000.0, "period_end": all_classes_end}
        shares_basis = "shares_outstanding"
    cash = market.get("cash")
    debt = market.get("total_debt")
    try:
        rate, rate_source, *_ = resolve_rates(db, company, as_of=today)
    except Exception as exc:  # noqa: BLE001 - sin tasa no hay propuesta
        logger.warning("sotp anchors: resolve_rates falló para %s: %s", company.ticker, type(exc).__name__)
        rate, rate_source = None, None
    if rate_source in (None, "tag_default"):
        # Sin WACC trazable: coste del capital por CAPM con los mismos insumos SEC/mercado de GerarAI
        # (tipo sin riesgo + beta × prima de mercado + prima país). Si faltan, la tasa por defecto, avisada.
        capm = _capm_cost_of_equity(db, company)
        if capm is not None:
            rate, rate_source = capm
    annual = (report.get("estimates") or {}).get("annual") or []
    revenue_rows = [
        {"period_end": str(row.get("period_end")), "revenue_millions": _millions(row.get("revenue"))}
        for row in annual
        if row.get("revenue")
    ]
    base_rate = _base_rate(db, company)
    balance_end = str((cash or debt or {}).get("period_end") or "")[:10] or None
    # Inversiones a corto del MISMO cierre (ShortTermInvestments del XBRL: ASTS 2T-2026 = 2.300 M$, 10-Q).
    short_term, _ = _fact_millions(db, company, "short_term_investments", period_prefix=balance_end) if balance_end else (None, None)
    sbc, sbc_end = _fact_millions(db, company, "stock_based_compensation", annual=True)
    fcf, fcf_end = _fact_millions(db, company, "free_cash_flow", annual=True)
    # Moneda de los informes (unidad de los hechos SEC; un 40-F canadiense va en CAD) frente a la del precio:
    # todo el modelo va en la de los informes y el precio se convierte con el tipo guardado (BCE).
    reporting = _reporting_currency(db, company)
    price_currency = (price_currency or company.currency or "").upper() or None
    fx_note = fx_missing = None
    if price is not None and reporting and price_currency and reporting != price_currency:
        from app.services.user_sotp_service import convert_amount

        converted = convert_amount(db, float(price), price_currency, reporting, today)
        if converted is None:
            fx_missing = f"tipo de cambio {price_currency}→{reporting}"
        else:
            price, fx_note = converted
        price_currency = reporting
    return {
        "ticker": company.ticker.upper(),
        "company": company.name,
        "today": today.isoformat(),
        "base_year": today.year,
        "currency": price_currency,
        "price": price,
        "price_fx_note": fx_note,
        "fx_missing": fx_missing,
        "price_as_of": price_as_of,
        "shares_current_millions": _millions(shares_point),
        "shares_basis": shares_basis if shares_point else None,
        "shares_period_end": str((shares_point or {}).get("period_end") or "") or None,
        "cash_millions": _millions(cash),
        "short_term_investments_millions": short_term,
        "sbc_annual_millions": sbc,
        "sbc_period_end": sbc_end,
        "annual_burn_millions": -fcf if fcf is not None and fcf < 0 else None,
        "burn_period_end": fcf_end,
        "debt_millions": _millions(debt),
        "balance_period_end": str((cash or debt or {}).get("period_end") or "") or None,
        "discount_rate": rate,
        "discount_rate_source": rate_source,
        "revenue_actuals": revenue_rows,
        "burns_cash": base_rate.get("applies"),
        "base_rate_message": base_rate.get("message_es"),
    }


def _anchor_outputs(anchors: Mapping[str, Any]) -> list[ToolOutput]:
    ticker = str(anchors.get("ticker") or "")
    url = f"/research/{ticker}?view=valuation"
    return [
        ToolOutput(
            source={"table": "market_prices", "date": str(anchors.get("price_as_of") or ""), "url": url,
                    "title": "Precio de cierre usado por GerarAI"},
            data={"price": anchors.get("price"), "currency": anchors.get("currency")},
        ),
        ToolOutput(
            source={"table": "financial_facts", "date": str(anchors.get("shares_period_end") or ""), "url": url,
                    "title": "Acciones, caja y deuda (SEC)"},
            data={
                "shares_current_millions": anchors.get("shares_current_millions"),
                "shares_basis": anchors.get("shares_basis"),
                "cash_millions": anchors.get("cash_millions"),
                "short_term_investments_millions": anchors.get("short_term_investments_millions"),
                "debt_millions": anchors.get("debt_millions"),
                "balance_period_end": anchors.get("balance_period_end"),
            },
        ),
        ToolOutput(
            source={"table": "financial_facts", "date": "", "url": url, "title": "Ingresos reales por ejercicio (SEC)"},
            data={"revenue_actuals": anchors.get("revenue_actuals")},
        ),
        ToolOutput(
            source={"table": "code:resolve_rates", "date": str(anchors.get("today") or ""), "url": url,
                    "title": "Tasa de descuento CAPM de GerarAI"},
            data={"discount_rate": anchors.get("discount_rate"), "source": anchors.get("discount_rate_source")},
        ),
        ToolOutput(
            source={"table": "code:cash_burn_base_rate", "date": "", "url": url,
                    "title": "Lo medido en empresas que queman caja"},
            data={"burns_cash": anchors.get("burns_cash"), "message": anchors.get("base_rate_message")},
        ),
    ]


def value_drivers_tool(db: Session) -> ToolSpec:
    """El inventario de impulsores que dejó el Recopilador (con su fuente y cita literal)."""

    def value_drivers(ctx: RunContext) -> list[ToolOutput]:
        from sqlalchemy import select

        from app.services.value_driver_service import ValueDriverService

        if not ctx.ticker or type(ctx.tenant_id) is not int:
            return []
        company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
        if company is None:
            return []
        rows = ValueDriverService().current(db, company_id=company.id, tenant_id=ctx.tenant_id)
        out = []
        for row in list(rows.values())[:60]:
            out.append(
                ToolOutput(
                    source={"table": "value_drivers", "id": str(row.id), "url": row.source_url or "",
                            "date": row.as_of.isoformat() if row.as_of else "", "title": row.name},
                    data={
                        "name": row.name, "category": row.category, "status": row.status,
                        "economics": row.economics or {}, "timing": row.timing,
                        "evidence": row.evidence, "quote": (row.source_quote or "")[:600],
                    },
                )
            )
        return out

    return ToolSpec(name="value_drivers", fn=value_drivers,
                    description="Impulsores de valor del Recopilador: contratos, segmentos, activos…")


#: Palabras de pasajes que hablan de acciones y dilución (genéricas, es/en).
SHARE_SIGNAL_WORDS: tuple[str, ...] = (
    "shares of class", "shares outstanding", "common stock outstanding", "conversion price", "convertible into",
    "warrant", "at-the-market", "at the market offering", "equity distribution", "redeemable", "exchangeable",
    "acciones en circulación", "precio de conversión", "ampliación de capital",
)
#: Activos de balance no operativos y cambios posteriores al balance (genéricas, es/en).
ASSET_SIGNAL_WORDS: tuple[str, ...] = (
    "spectrum", "mhz", "intangible assets", "usage rights", "license agreement", "patents", "equity method",
    "investment in", "subsequent event", "net proceeds", "espectro", "licencia", "patente", "participación en",
    "hechos posteriores", "ingresos netos de la emisión",
)
PASSAGES_PER_DOC = 3
PASSAGE_DOCUMENTS = 8


def passages_tool(db: Session, name: str, words: tuple[str, ...], description: str) -> ToolSpec:
    """Pasajes de los documentos ingeridos de la empresa que contienen alguna de ``words``.

    Misma consulta que ``company_documents`` del Recopilador (tenant, empresa,
    documentos vivos más recientes), con otra lista de palabras.
    """
    from sqlalchemy import select

    from app.models.entities import Document, DocumentChunk

    def fn(ctx: RunContext) -> list[ToolOutput]:
        if not ctx.ticker:
            return []
        company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
        if company is None:
            return []
        docs = db.scalars(
            select(Document)
            .where(Document.tenant_id == ctx.tenant_id, Document.company_id == company.id,
                   Document.retention_tombstoned_at.is_(None))
            .order_by(Document.published_at.desc().nullslast(), Document.id.desc())
            .limit(PASSAGE_DOCUMENTS)
        ).all()
        out: list[ToolOutput] = []
        for doc in docs:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.tenant_id == ctx.tenant_id, DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            hits = [c for c in chunks if any(w in " ".join((c.text or "").split()).casefold() for w in words)]
            for chunk in hits[:PASSAGES_PER_DOC]:
                out.append(ToolOutput(
                    source={"table": "document_chunks", "document_id": str(doc.id), "title": doc.title or "",
                            "url": doc.source_url or "",
                            "date": doc.published_at.date().isoformat() if doc.published_at else ""},
                    data={"text": (chunk.text or "")[:1500]},
                ))
        return out

    return ToolSpec(name=name, fn=fn, description=description)


def share_count_documents_tool(db: Session) -> ToolSpec:
    """Acciones por clase, convertibles y warrants: lo que lleva a la cifra totalmente diluida.

    Las acciones de la SEC (``financial_facts``) pueden ser solo una clase o la
    media diluida del trimestre.
    """
    return passages_tool(db, "share_count_documents", SHARE_SIGNAL_WORDS,
                         "Pasajes sobre acciones en circulación por clase, convertibles y warrants")


def balance_asset_documents_tool(db: Session) -> ToolSpec:
    """Espectro, licencias, patentes, participaciones y cambios posteriores al balance."""
    return passages_tool(db, "balance_asset_documents", ASSET_SIGNAL_WORDS,
                         "Pasajes sobre activos no operativos y emisiones posteriores al último balance")


def analyst_estimates_tool(db: Session) -> ToolSpec:
    """Lo que dicen los analistas que GerarAI ya guarda: notas (precio objetivo, argumentos)
    y supuestos de analista con firma y fuente (``declared_input_values``, method='analyst')."""
    from sqlalchemy import desc, select

    from app.models.analyst_note import AnalystNote
    from app.models.declared_input_value import DeclaredInputValue

    def analyst_estimates(ctx: RunContext) -> list[ToolOutput]:
        if not ctx.ticker or type(ctx.tenant_id) is not int:
            return []
        company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
        out: list[ToolOutput] = []
        notes = db.scalars(
            select(AnalystNote).where(AnalystNote.tenant_id == ctx.tenant_id, AnalystNote.ticker == ctx.ticker)
            .order_by(desc(AnalystNote.note_date)).limit(20)
        ).all()
        for note in notes:
            out.append(ToolOutput(
                source={"table": "analyst_notes", "id": str(note.id), "title": f"{note.firm} ({note.note_date})",
                        "url": note.source_url or "", "date": note.note_date.isoformat()},
                data={"firm": note.firm, "action": note.action, "rating": note.rating_new,
                      "price_target": float(note.pt_new) if note.pt_new is not None else None,
                      "currency": note.currency, "key_arguments": list(note.key_arguments or [])[:5],
                      "quote": (note.quote or "")[:500], "verification": note.verification,
                      "estimates": note.estimates or {}, "segment_assumptions": note.segment_assumptions or {},
                      "bull_target": _num(note.bull_target), "bear_target": _num(note.bear_target)},
            ))
        if company is not None:
            rows = db.scalars(
                select(DeclaredInputValue).where(
                    DeclaredInputValue.tenant_id == ctx.tenant_id, DeclaredInputValue.company_id == company.id,
                    DeclaredInputValue.method == "analyst", DeclaredInputValue.superseded_at.is_(None))
                .order_by(DeclaredInputValue.as_of.desc().nulls_last(), DeclaredInputValue.id.desc())
                .limit(80)
            ).all()
            for row in rows:
                out.append(ToolOutput(
                    source={"table": "declared_input_values", "id": str(row.id),
                            "title": f"{row.analyst_firm or 'analista'}: {row.input_key}",
                            "url": row.source_url or "", "date": row.as_of.isoformat() if row.as_of else ""},
                    data={"input": row.input_key, "segment": row.segment_key, "low": _num(row.low),
                          "base": _num(row.base), "high": _num(row.high), "unit": row.unit,
                          "firm": row.analyst_firm, "quote": (row.source_quote or "")[:400]},
                ))
            out.extend(_company_guidance_outputs(db, company, ctx.tenant_id))
            out.extend(_analyst_consensus_outputs(db, company, ctx.tenant_id))
            out.extend(_own_consensus_outputs(db, company, ctx.tenant_id))
        return out

    return ToolSpec(name="analyst_estimates", fn=analyst_estimates,
                    description="Precios objetivo y estimaciones de analistas guardados, con firma y fuente, "
                                "y la guía de la propia empresa citada de sus notas de resultados")


def _own_consensus_outputs(db: Session, company: Company, tenant_id: int) -> list[ToolOutput]:
    """Consenso propio por celda (``own_consensus``): la primera fuente del orden fijo que
    pasa las puertas de cordura, con bajo/medio/alto, fórmula, cita y confianza medida.
    Sin red ni modelo; los expertos lo leen como ancla «consenso_propio»."""
    from app.services.own_consensus import build_company_consensus

    try:
        result = build_company_consensus(db, company, tenant_id)
    except Exception as exc:  # noqa: BLE001 - sin consenso propio siguen las demás anclas
        logger.warning("consenso propio no disponible para %s: %s", company.ticker, type(exc).__name__)
        return []
    out: list[ToolOutput] = []
    for cell in result["cells"]:
        if cell["status"] != "estimado":
            continue
        first = (cell.get("citations") or [{}])[0]
        out.append(ToolOutput(
            source={"table": "own_consensus", "id": cell["key"],
                    "title": f"Consenso propio {cell['metric']} {cell['period']} ({cell['source']})",
                    "url": first.get("url") or "", "date": first.get("date") or result["as_of"]},
            data={"kind": "own_consensus", **{k: cell[k] for k in (
                "metric", "period", "period_end", "source", "low", "mid", "high", "formula", "flags",
                "confidence", "version")}},
        ))
    return out


def _analyst_consensus_outputs(db: Session, company: Company, tenant_id: int) -> list[ToolOutput]:
    """Agregado de estimaciones por métrica y año (``analyst_consensus``): cada firma con
    fecha y URL, bajo/mediana/alto, revisiones y el estado de la ponderación por
    precisión (regla prerregistrada). El código no elige: eligen los expertos, con razón."""
    from app.services.analyst_consensus import aggregate, history_for, reported_revenue

    try:
        items = aggregate(history_for(db, company, tenant_id), reported_revenue(db, company))
    except Exception as exc:  # noqa: BLE001 - sin agregado los expertos siguen con las filas sueltas
        logger.warning("agregado de analistas no disponible para %s: %s", company.ticker, type(exc).__name__)
        return []
    out: list[ToolOutput] = []
    for item in items[:24]:
        first = (item["firms"] or [{}])[0]
        out.append(ToolOutput(
            source={"table": "analyst_notes", "id": f"consenso:{item['metric']}:{item['year']}",
                    "title": f"Estimaciones de analistas {item['metric']} {item['year']} ({item['n_firms']} firmas)",
                    "url": first.get("url") or "", "date": first.get("as_of") or ""},
            data={"kind": "analyst_consensus", "unit": "millones", **item},
        ))
    return out


def _company_guidance_outputs(db: Session, company: Company, tenant_id: int) -> list[ToolOutput]:
    """Guía de la empresa (``company_guidance``): dato oficial con su frase literal, URL y fecha.

    Es lo que un segmento aún no comercial puede usar como ``guidance_anchor``
    («guia»); sin ella queda «infravalorado por falta de estimaciones»."""
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue

    rows = db.scalars(
        select(DeclaredInputValue).where(
            DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
            DeclaredInputValue.method == "extract", DeclaredInputValue.input_key.like("guidance.%"),
            DeclaredInputValue.superseded_at.is_(None))
        .order_by(DeclaredInputValue.input_key).limit(20)
    ).all()
    out: list[ToolOutput] = []
    for row in rows:
        meta = row.metadata_ or {}
        if meta.get("kind") != "company_guidance":
            continue
        per_share = str(row.unit or "").endswith("/share")
        scale = 1.0 if per_share else 1e6

        def amount(value: Any, scale: float = scale) -> float | None:
            number = _num(value)
            return None if number is None else round(number / scale, 6)

        out.append(ToolOutput(
            source={"table": "declared_input_values", "id": str(row.id),
                    "title": f"guía de la empresa: {meta.get('metric')} {meta.get('period')}",
                    "url": row.source_url or "", "date": row.as_of.isoformat() if row.as_of else ""},
            data={"kind": "guia", "metric": meta.get("metric"), "period": meta.get("period"),
                  "period_read": meta.get("period_read"),
                  "unit": row.unit if per_share else f"millones de {row.unit}",
                  "low": amount(row.low), "base": amount(row.base), "high": amount(row.high),
                  "quote": (row.source_quote or "")[:600]},
        ))
    return out



def companies_house_outputs(result: Mapping[str, Any] | None) -> list[ToolOutput]:
    """Una salida por filial britanica verificada: sus ultimas cuentas en Companies House,
    citadas con su URL publica, y las cifras del iXBRL cuando las cuentas van etiquetadas."""
    out: list[ToolOutput] = []
    for row in (result or {}).get("members") or []:
        figures = {
            f["metric"]: {"millones": f["value_millions"], "moneda": f["currency"], "cierre": f["period_end"],
                          "concepto": f["concept"]}
            for f in row.get("figures") or []
        }
        made_up = row.get("made_up_to") or ""
        kind = row.get("accounts_type") or "sin cuentas"
        quote = "; ".join(f"{f['label']} {f['value']:,.0f} {f['currency']} a {f['period_end']} ({f['concept']})"
                          for f in row.get("figures") or [])
        out.append(ToolOutput(
            source={"table": "companies_house", "id": str(row.get("company_number") or ""),
                    "url": row.get("ixbrl_url") if figures and row.get("ixbrl_url") else
                    (row.get("document_url") or row.get("company_url") or ""),
                    "date": str(made_up),
                    "title": f"{row.get('company_name')} ({row.get('company_number')}): cuentas «{kind}» "
                             f"a {made_up or 's/f'}, Companies House"},
            data={
                "sociedad": row.get("company_name"), "numero": row.get("company_number"),
                "controladora": row.get("parent"), "por_que_es_del_grupo": row.get("via"),
                "tipo_cuentas": kind, "cierre": made_up, "presentadas": row.get("filed_on"),
                "formatos": row.get("formats"), "paginas": row.get("pages"),
                "cifras": figures or None,
                "nota": None if figures else "cuentas en PDF (sin iXBRL): citables por su enlace, sin cifras extraidas",
                "quote": quote or None, "ficha": row.get("company_url"),
            },
        ))
    return out


def companies_house_tool(db: Session) -> ToolSpec:
    """Filiales britanicas del holding y sus cuentas oficiales (Companies House). Apagada sin clave."""

    def companies_house(ctx: RunContext) -> list[ToolOutput]:
        from sqlalchemy import select

        from app.services.companies_house_evidence import collect_group_accounts, subsidiary_hints

        if not ctx.ticker:
            return []
        company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
        # Solo emisores sin SEC (holdings de Londres, Toronto…): una empresa con CIK ya tiene sus
        # segmentos en el XBRL de la SEC y sus filiales britanicas serian ruido y peticiones.
        if company is None or not company.name or getattr(company, "cik", None):
            return []
        tenant = ctx.tenant_id if type(ctx.tenant_id) is int else None
        result = collect_group_accounts(company.name, subsidiary_hints(db, company, tenant))
        return companies_house_outputs(result)

    return ToolSpec(name="companies_house", fn=companies_house,
                    description="Filiales britanicas verificadas por PSC y sus ultimas cuentas en Companies House")


def build_sotp_tools(db: Session, anchors: Mapping[str, Any]) -> dict[str, ToolSpec]:
    from app.services.expert_team.recopilador import company_documents_tool
    from app.services.expert_team.tools import build_tools

    tools = {k: v for k, v in build_tools(db).items() if k in SOTP_VALUER_TOOLS}
    tools["company_documents"] = company_documents_tool(db)
    tools["value_drivers"] = value_drivers_tool(db)
    tools["share_count_documents"] = share_count_documents_tool(db)
    tools["balance_asset_documents"] = balance_asset_documents_tool(db)
    tools["analyst_estimates"] = analyst_estimates_tool(db)
    tools["companies_house"] = companies_house_tool(db)
    tools["sotp_anchors"] = ToolSpec(name="sotp_anchors", fn=lambda ctx: _anchor_outputs(anchors),
                                     description="Precio, acciones, caja, deuda, ingresos y tasa CAPM fijados por el código")
    return tools


def _text(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def _sources_for(citations: list[str], ledger: EvidenceLedger) -> list[dict[str, Any]]:
    out = []
    seen: set[tuple[str, str]] = set()
    for cid in citations:
        item = ledger.get(cid)
        if item is None:
            continue
        src = item.source
        label = src.get("title") or src.get("source") or src.get("table") or cid
        table = src.get("table") or ""
        if table and table not in label:
            label = f"{label} ({table})"
        key = (_text(label, 160), src.get("url") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": key[0], "url": src.get("url") or None, "date": src.get("date") or None})
    return out


def _citations(raw: Mapping[str, Any], ledger: EvidenceLedger, expert: str) -> tuple[list[str], bool]:
    """(citas, todas_válidas): una cita vale si es evidencia de ESTA corrida y de ESTE experto."""
    cites = [c for c in raw.get("citations") or () if isinstance(c, str)]
    valid = all((ev := ledger.get(c)) is not None and ev.expert == expert for c in cites)
    return cites, valid


async def run_sotp_valuer(
    db: Session,
    *,
    ctx: RunContext,
    reasoner: Reasoner,
    spec: ExpertSpec | None = None,
    tools: Mapping[str, ToolSpec] | None = None,
    anchors: Mapping[str, Any] | None = None,
    today: date | None = None,
    cached: Callable[[str], Mapping[str, Any] | None] | None = None,
    readings: int = 1,
    max_calls: int = 3,
) -> SotpProposalResult:
    """Clasificación (de la caché por huella o del modelo) + reglas → modelo. No escribe en la base."""
    from sqlalchemy import select

    from app.services.expert_team.roster import sotp_valuer_expert
    from app.services.prompt_registry import get_prompt

    if type(ctx.tenant_id) is not int or not ctx.ticker:
        return SotpProposalResult(status="no_company", problems=["hace falta tenant y empresa"])
    company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
    if company is None:
        return SotpProposalResult(status="no_company")
    anchors = dict(anchors) if anchors is not None else sotp_anchors(db, company, today=today)
    spec = spec or sotp_valuer_expert()
    prompt = get_prompt(spec.prompt_name, lang="es")
    result = SotpProposalResult(status="no_data", prompt_version=prompt.version, anchors=anchors)
    if anchors.get("price") is None:
        result.status = "no_price"
        result.problems = ["sin precio de la empresa"]
        return result
    missing = [label for key, label in (("shares_current_millions", "acciones (SEC)"),
                                         ("discount_rate", "tasa de descuento")) if not anchors.get(key)]
    if anchors.get("fx_missing"):
        missing.append(str(anchors["fx_missing"]))
    if missing:
        # Sin estos datos no hay modelo posible: no se gasta una llamada al modelo.
        result.problems = [f"faltan datos: {', '.join(missing)}"]
        return result
    tools = tools if tools is not None else build_sotp_tools(db, anchors)
    ledger = EvidenceLedger()
    evidence, result.tool_errors = await gather_evidence(spec, ctx, tools, ledger)
    if not evidence:
        return result
    result.fingerprint = sotp_rules.fingerprint(evidence, prompt_version=prompt.version)
    result.headlines = [
        {"title": (item.get("source") or {}).get("title"), "date": (item.get("source") or {}).get("date")}
        for item in evidence if item.get("tool") == "news_events" and (item.get("source") or {}).get("title")
    ][:12]
    hit = cached(result.fingerprint["hash"]) if cached is not None else None
    if hit:
        model, problems = build_model(hit, anchors) if hit.get("segments") else (None, [NO_SEGMENTS])
        result.cache_hit, result.classification = True, dict(hit)
        if model is not None:
            result.status, result.model = "ok", model
            result.value_per_share = run_user_sotp(model)["value_per_share"]
            return result
        # Misma huella, misma clasificación: el mismo rechazo, sin volver a llamar al modelo.
        result.status, result.problems = "rejected", problems
        return result
    system = f"{prompt.text}\n\n{SOTP_CONTRACT}"
    payload: dict[str, Any] = {
        "ticker": ctx.ticker,
        "company": company.name,
        "today": anchors.get("today"),
        "currency": anchors.get("currency"),
        "evidence": evidence,
    }
    found: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    rejected_classification: dict[str, Any] | None = None
    for _ in range(max(1, readings)):
        attempt_payload = dict(payload)
        for _attempt in range(MAX_ATTEMPTS):
            if result.llm_calls >= max_calls:
                break
            result.llm_calls += 1
            try:
                text = await reasoner(system, json.dumps(attempt_payload, ensure_ascii=False, default=str),
                                      spec.max_tokens, f"expert_team.{spec.name}")
            except Exception as exc:  # sin LLM o sin presupuesto: no se escribe nada
                result.status = "error"
                result.problems = [f"llm:{type(exc).__name__}"]
                return result
            try:
                parsed = parse_json_response(text)
            except Exception:
                parsed = None
            classification, problems = parse_classification(parsed, ledger, expert=spec.name)
            model = None
            if classification is not None:
                model, problems = build_model(classification, anchors)
            if model is not None and classification is not None:
                found.append((run_user_sotp(model)["value_per_share"], classification, model))
                break
            if classification is not None or problems == [NO_SEGMENTS]:
                rejected_classification = classification or {"segments": [], "assets": [], "dilution": [],
                                                             "unvalued": [], "rejected": NO_SEGMENTS}
            result.problems = problems
            attempt_payload["problems_previous_answer"] = problems[:25]
    if not found:
        result.status = "rejected"
        result.classification = rejected_classification  # válida de forma: se guarda para no repetir la llamada
        return result
    result.readings = [
        {"value_per_share": vps, "segments": [list(k) for k in _classification_key(c)],
         "unvalued": [u.get("name") for u in c.get("unvalued") or []]}
        for vps, c, _m in found
    ]
    result.readings_differ = len({json.dumps(_classification_key(c)) for _v, c, _m in found}) > 1
    value, classification, model = min(found, key=lambda item: item[0])  # la lectura más conservadora
    result.status, result.model, result.classification = "ok", model, classification
    result.value_per_share = value
    result.problems = []
    return result


def _cache_lookup(db: Session, company: Company, tenant_id: int) -> Callable[[str], Mapping[str, Any] | None]:
    """Clasificación guardada con la misma huella (último guardado de los agentes primero)."""
    from app.services.user_sotp_service import (
        AGENTS_REJECTED_SEGMENT,
        AGENTS_SEGMENT,
        SOTP_INPUT_KEY,
        UserSotpService,
    )

    inputs = UserSotpService().inputs
    rows = inputs.history(db, company_id=company.id, tenant_id=tenant_id,
                          input_key=SOTP_INPUT_KEY, segment_key=AGENTS_SEGMENT)
    rejected = inputs.history(db, company_id=company.id, tenant_id=tenant_id,
                              input_key=SOTP_INPUT_KEY, segment_key=AGENTS_REJECTED_SEGMENT)

    def lookup(fingerprint_hash: str) -> Mapping[str, Any] | None:
        for row in [*reversed(rows), *reversed(rejected)]:
            meta = row.metadata_ or {}
            if (meta.get("fingerprint") or {}).get("hash") == fingerprint_hash and meta.get("classification"):
                return meta["classification"]
        return None

    lookup.previous_fingerprint = next(  # type: ignore[attr-defined]
        ((r.metadata_ or {}).get("fingerprint") for r in reversed(rows) if (r.metadata_ or {}).get("fingerprint")),
        None,
    )
    return lookup


def generate_sotp_proposal(
    db: Session,
    company: Company,
    *,
    reasoner: Reasoner | None = None,
    thesis_version_id: int | None = None,
    trigger: str = "button",
    timeout: float = 180.0,
    today: date | None = None,
    use_cache: bool = True,
    readings: int | None = None,
) -> SotpProposalResult:
    """Corre el valorador SOTP y guarda su propuesta (segmento ``agents``). Nunca lanza.

    Pensado para el job de la tesis y para el botón «Generar con expertos»:
    un fallo devuelve el estado y los problemas, sin tocar lo guardado. Con la
    misma huella de entradas devuelve la propuesta guardada sin llamar al modelo.
    """
    from app.core.config import get_settings
    from app.core.i18n import current_language
    from app.services.async_bridge import run_from_any_context
    from app.services.expert_team.service import provider_reasoner
    from app.services.user_sotp_service import UserSotpService

    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return SotpProposalResult(status="no_company", problems=["hace falta tenant"])
    ctx = RunContext(tenant_id=tenant_id, user_id=str(db.info.get("user_id") or "") or None,
                     ticker=company.ticker.strip().upper(), mode="thesis", lang=current_language())
    if reasoner is None:
        # Temperatura 0; el determinismo lo da la caché por huella (el cliente no expone semilla).
        reasoner = provider_reasoner(db=db, commit_usage=False, temperature=0.0)
    lookup = _cache_lookup(db, company, tenant_id)
    if readings is None:
        readings = max(1, int(getattr(get_settings(), "sotp_agents_readings", 1) or 1))
    try:
        # Guía de la empresa citada de sus notas de resultados (sin modelo): evidencia
        # para los segmentos que aún no facturan. Un fallo no toca la valoración.
        from app.services.company_guidance import refresh_company_guidance

        with db.begin_nested():
            refresh_company_guidance(db, company, tenant_id, today=today)
    except Exception as exc:  # noqa: BLE001
        logger.warning("guía de la empresa no disponible para %s: %s", company.ticker, type(exc).__name__)
    # Estimaciones de analistas citadas en prensa (sin modelo): si la recogida diaria no ha
    # pasado por esta empresa en los últimos días, se encola para ella (sin red en esta ruta;
    # entra en la próxima propuesta). Un fallo no toca la valoración.
    try:
        from app.services.analyst_press_estimates import press_estimates_stale

        if press_estimates_stale(db, company, tenant_id, today=today):
            from app.workers.dramatiq_app import collect_analyst_estimates

            collect_analyst_estimates.send(tenant_id, str(db.info.get("user_id") or "") or None, company.ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("estimaciones de prensa no disponibles para %s: %s", company.ticker, type(exc).__name__)
    try:
        result = run_from_any_context(
            run_sotp_valuer(db, ctx=ctx, reasoner=reasoner, today=today, cached=lookup if use_cache else None,
                            readings=readings),
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - nunca rompe a quien llama (la tesis)
        logger.warning("valorador SOTP falló para %s: %s", company.ticker, type(exc).__name__)
        return SotpProposalResult(status="error", problems=[f"{type(exc).__name__}"])
    if result.model is None:
        if (result.status == "rejected" and not result.cache_hit and result.classification is not None
                and result.fingerprint):
            try:
                UserSotpService().save_rejected(db, company, tenant_id, meta={
                    "generated_at": datetime.now(UTC).isoformat(), "trigger": trigger,
                    "prompt_version": result.prompt_version, "rules_version": sotp_rules.RULES_VERSION,
                    "llm_calls": result.llm_calls, "fingerprint": result.fingerprint,
                    "classification": result.classification, "problems": list(result.problems)[:20]})
            except Exception as exc:  # noqa: BLE001 - la caché del rechazo nunca rompe a quien llama
                db.rollback()
                logger.warning("no se pudo guardar el rechazo SOTP de %s: %s", company.ticker, type(exc).__name__)
        return result
    previous = getattr(lookup, "previous_fingerprint", None)
    changed_by = [] if result.cache_hit else sotp_rules.fingerprint_changes(previous, result.fingerprint or {})
    current = UserSotpService().read(db, company, tenant_id, variant="agents") if result.cache_hit else None
    if result.cache_hit and current and current.get("variant") == "agents" and current.get("model") == result.model:
        result.status = "cached"
        result.row_id = (current.get("saved") or {}).get("row_id")
        _attach_narrative(db, company, tenant_id, result, reasoner, timeout=timeout)
        return result
    try:
        row = UserSotpService().save_agents(
            db, company, tenant_id, result.model,
            meta={
                "generated_at": datetime.now(UTC).isoformat(),
                "price": result.anchors.get("price"),
                "price_currency": result.anchors.get("currency"),
                "price_as_of": result.anchors.get("price_as_of"),
                "thesis_version_id": thesis_version_id,
                "trigger": trigger,
                "prompt_version": result.prompt_version,
                "rules_version": sotp_rules.RULES_VERSION,
                "llm_calls": result.llm_calls,
                "fingerprint": result.fingerprint,
                "classification": result.classification,
                "cache_hit": result.cache_hit,
                "readings": result.readings,
                "readings_differ": result.readings_differ,
                "changed_by": changed_by,
            },
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("no se pudo guardar la propuesta SOTP de %s: %s", company.ticker, type(exc).__name__)
        return SotpProposalResult(status="error", problems=[f"guardar:{type(exc).__name__}"],
                                  llm_calls=result.llm_calls, prompt_version=result.prompt_version)
    result.status = "stored"
    result.row_id = row.id
    _attach_narrative(db, company, tenant_id, result, reasoner, timeout=timeout)
    return result


def _previous_narrative(db: Session, company: Company, tenant_id: int, expected: str) -> dict[str, Any] | None:
    from app.services.user_sotp_service import AGENTS_SEGMENT, SOTP_INPUT_KEY, UserSotpService

    rows = UserSotpService().inputs.history(db, company_id=company.id, tenant_id=tenant_id,
                                            input_key=SOTP_INPUT_KEY, segment_key=AGENTS_SEGMENT)
    for row in reversed(rows):
        narrative = (row.metadata_ or {}).get("narrative") or {}
        if narrative.get("fingerprint") == expected and narrative.get("sections"):
            return dict(narrative)
    return None


def _attach_narrative(db: Session, company: Company, tenant_id: int, result: SotpProposalResult,
                      reasoner: Reasoner, *, timeout: float) -> None:
    """Tesis larga con marcadores sobre la propuesta guardada (misma huella → la guardada). Nunca lanza."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.config import get_settings
    from app.models import DeclaredInputValue
    from app.services.async_bridge import run_from_any_context
    from app.services.expert_team.sotp_narrative import narrative_fingerprint, sotp_markers, write_narrative

    if not getattr(get_settings(), "sotp_agents_narrative_enabled", True) or not result.row_id or not result.model:
        return
    try:
        row = db.get(DeclaredInputValue, result.row_id)
        if row is None:
            return
        meta = dict(row.metadata_ or {})
        computed = run_user_sotp(result.model, price=result.anchors.get("price"))
        context = {"ticker": company.ticker, "company": company.name, "headlines": result.headlines,
                   "classification": [{k: s.get(k) for k in ("name", "status", "business_type", "why_status")}
                                      for s in (result.classification or {}).get("segments") or []]}
        cached = meta.get("narrative")
        if not (cached or {}).get("sections"):
            # Versión nueva por reglas nuevas (mismas partes y misma huella): la tesis guardada en una versión
            # anterior sigue valiendo si su huella coincide (los números los pone el cálculo al mostrarla).
            expected = narrative_fingerprint((result.fingerprint or {}).get("hash"), sotp_markers(result.model, computed))
            cached = _previous_narrative(db, company, tenant_id, expected)
        narrative = run_from_any_context(
            write_narrative(reasoner=reasoner, model=result.model, result=computed, context=context,
                            sotp_fingerprint=(result.fingerprint or {}).get("hash"), cached=cached),
            timeout=timeout,
        )
        result.narrative = narrative.as_dict()
        if not narrative.sections or (narrative.status == "cached" and cached is meta.get("narrative")):
            return
        meta["narrative"] = narrative.as_dict()
        row.metadata_ = meta
        flag_modified(row, "metadata_")
        db.commit()
    except Exception as exc:  # noqa: BLE001 - la tesis larga nunca rompe la propuesta
        db.rollback()
        logger.warning("tesis SOTP de %s: %s", company.ticker, type(exc).__name__)
        result.narrative = {"status": "error", "problems": [type(exc).__name__]}


__all__ = [
    "AGENTS_LABEL",
    "SOTP_CONTRACT",
    "SOTP_VALUER_NAME",
    "SOTP_VALUER_TOOLS",
    "SotpProposalResult",
    "build_model",
    "build_sotp_tools",
    "companies_house_outputs",
    "companies_house_tool",
    "generate_sotp_proposal",
    "parse_classification",
    "parse_proposal",
    "run_sotp_valuer",
    "sotp_anchors",
    "value_drivers_tool",
]
