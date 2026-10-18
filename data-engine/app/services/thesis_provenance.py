"""Procedencia de los inputs de la tesis.

Cada input del modelo se etiqueta como dato / derivado / estimacion_llm /
supuesto, con metodo, cita (fact ids) y confianza. Determinista: traduce lo
que el motor fundamental ya persiste (source_type, basis, source_fact_ids,
confidence) a las etiquetas que ve el usuario. Nunca inventa procedencia:
lo no clasificable (source_type "missing") no se etiqueta; lo lista la
seccion de datos pendientes.
"""

from __future__ import annotations

import math
import re
from typing import Any

LABEL_DATO = "dato"
LABEL_DERIVADO = "derivado"
LABEL_ESTIMACION_LLM = "estimacion_llm"
LABEL_SUPUESTO = "supuesto"

ORIGEN_OFICIAL = "OFICIAL"
ORIGEN_INFERIDO = "INFERIDO"

# Hosts de fuente primaria oficial; mismo conjunto que la ingesta primaria.
OFFICIAL_HOSTS = frozenset(
    {"www.sec.gov", "sec.gov", "www.itu.int", "itu.int", "www.fcc.gov", "fcc.gov"}
)
OFFICIAL_DOC_SOURCE_TYPE = "primary_official"
# XBRL de la SEC (companyfacts / archivos presentados): la propia SEC es la
# fuente; solo cuenta con host oficial, URL https y fecha, como el resto.
OFFICIAL_DOC_SOURCE_TYPES = frozenset({OFFICIAL_DOC_SOURCE_TYPE, "SEC"})
# Unica lectura directa de un hecho reportado: linea de driver_model con
# status sourced (valor = FinancialFact.value de UN fact). Las assumptions
# (medianas de ratios, clamps, politica, overrides, LLM) son siempre calculo o
# supuesto => INFERIDO, sea cual sea su label/source_type declarado.
DIRECT_READING_SOURCE_TYPE = "driver_sourced"

LABELS = (LABEL_DATO, LABEL_DERIVADO, LABEL_ESTIMACION_LLM, LABEL_SUPUESTO)

# Assumptions del modelo: todo lo que el motor calcula a partir de facts es
# un derivado (lleva formula/metodo + inputs); las constantes de politica y
# los supuestos (usuario u override) son supuestos; las estimaciones LLM
# llegan etiquetadas como tales desde su productor.
_ASSUMPTION_LABELS = {
    "financial_facts": LABEL_DERIVADO,
    "calculated_metric": LABEL_DERIVADO,
    "model_policy": LABEL_SUPUESTO,
    "inferred_input": LABEL_SUPUESTO,
    "assumption_override": LABEL_SUPUESTO,
    "user_provided": LABEL_SUPUESTO,
    "llm_estimate": LABEL_ESTIMACION_LLM,
}


def label_for_assumption(source_type: str | None) -> str | None:
    """Etiqueta de una assumption del modelo; None = sin dato (pendiente)."""
    if not source_type or source_type == "missing":
        return None
    return _ASSUMPTION_LABELS.get(source_type)


def _item(
    key: str,
    label: str,
    value: Any,
    unit: str | None,
    method: str | None,
    source_fact_ids: list[int],
    confidence: Any,
    source_type: str | None = None,
    period: str | None = None,
    source_urls: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source_urls": list(source_urls or []),
        "source_type": source_type,
        "period": period,
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "method": method,
        "source_fact_ids": source_fact_ids,
        "confidence": confidence,
    }


def build_inputs_provenance(long_term_model: dict[str, Any]) -> list[dict[str, Any]]:
    """Inputs etiquetados a partir del payload del motor fundamental.

    - assumptions: derivado/supuesto/estimacion_llm segun source_type.
    - driver_model sourced: dato (linea reportada con cita al fact).
    """
    items: list[dict[str, Any]] = []
    assumptions = long_term_model.get("assumptions") or {}
    for key, assumption in sorted(assumptions.items()):
        if not isinstance(assumption, dict):
            continue
        label = label_for_assumption(assumption.get("source_type"))
        if label is None:
            continue
        items.append(
            _item(
                key,
                label,
                assumption.get("value"),
                assumption.get("unit"),
                assumption.get("basis"),
                list(assumption.get("source_fact_ids") or []),
                assumption.get("confidence"),
                assumption.get("source_type"),
                source_urls=list(assumption.get("source_urls") or []),
            )
        )
    for driver in long_term_model.get("driver_model") or []:
        if not isinstance(driver, dict) or driver.get("status") != "sourced":
            continue
        trace = driver.get("trace") or {}
        period = trace.get("period")
        method = f"{driver.get('driver_type', 'driver')} reportado"
        if period:
            method = f"{method} (periodo {period})"
        items.append(
            _item(
                str(driver.get("key")),
                LABEL_DATO,
                driver.get("value"),
                driver.get("unit"),
                method,
                list(driver.get("source_fact_ids") or []),
                driver.get("confidence"),
                DIRECT_READING_SOURCE_TYPE,
                period,
            )
        )
    return items


def inputs_provenance_from_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Read-back desde FundamentalModelVersion.model_snapshot persistido."""
    return build_inputs_provenance(snapshot or {})


def _is_official_source(src: dict[str, Any] | None) -> bool:
    """Fuente verificable: documento primary_official, host oficial, con URL
    http(s) y fecha. Sin cualquiera de ellos no se presenta como oficial."""
    if not src or src.get("source_type") not in OFFICIAL_DOC_SOURCE_TYPES:
        return False
    url = src.get("url") or ""
    if not url.startswith("https://") or not src.get("date"):
        return False
    host = url.split("/", 3)[2].lower() if url.count("/") >= 2 else ""
    return host in OFFICIAL_HOSTS


def _metric_key(metric: str) -> str:
    return re.sub(r"\s+", "_", metric.strip().lower().replace("&", "and").replace("/", "_").replace("-", "_"))


def _matches_fact(item: dict[str, Any], src: dict[str, Any] | None) -> bool:
    """El input debe ser el propio fact: misma metrica, valor, unidad y periodo."""
    if not src or src.get("fact_value") is None or not src.get("is_reported"):
        return False
    try:
        item_value = float(item.get("value"))
        fact_value = float(src["fact_value"])
    except (TypeError, ValueError):
        return False
    return (
        _metric_key(str(src.get("metric") or "")) == _metric_key(str(item.get("key") or ""))
        and math.isclose(item_value, fact_value, rel_tol=1e-9, abs_tol=1e-9)
        and (item.get("unit") or "") == (src.get("unit") or "")
        and bool(item.get("period"))
        and item.get("period") == src.get("period")
    )


def classify_origin(
    items: list[dict[str, Any]], sources: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Anade el origen binario OFICIAL / INFERIDO a cada input.

    Politica del producto: todo numero es OFICIAL (URL oficial + fecha, verificada
    contra el documento persistido) o INFERIDO (base explicita + URLs). No hay
    tercera categoria: lo que no se pueda verificar como oficial es INFERIDO.
    `sources` = fact_id -> {url, date, title, source_type} resuelto desde
    FinancialFact.source_id -> Document; nunca se toma de lo declarado.
    """
    out: list[dict[str, Any]] = []
    for item in items:
        fact_ids = list(item.get("source_fact_ids") or [])
        resolved = [sources.get(fid) for fid in fact_ids]
        cited = [
            {
                "fact_id": fid,
                "url": src.get("url"),
                "fecha": src.get("date"),
                "titulo": src.get("title"),
                "oficial": _is_official_source(src),
            }
            for fid, src in zip(fact_ids, resolved)
            if src
        ]
        official = (
            item.get("source_type") == DIRECT_READING_SOURCE_TYPE
            and len(fact_ids) == 1
            and len(cited) == 1
            and cited[0]["oficial"]
            and _matches_fact(item, resolved[0])
        )
        enriched = dict(item)
        if official:
            enriched["origen"] = ORIGEN_OFICIAL
            enriched["fuentes"] = cited
            enriched["base_inferencia"] = None
            enriched["urls_inferencia"] = []
        else:
            base = (item.get("method") or "").strip() or None
            enriched["origen"] = ORIGEN_INFERIDO
            enriched["fuentes"] = []
            enriched["base_inferencia"] = base
            declared = [
                u for u in (item.get("source_urls") or []) if isinstance(u, str)
            ] if item.get("source_type") == "inferred_input" else []
            enriched["urls_inferencia"] = list(
                dict.fromkeys([c["url"] for c in cited if c.get("url")] + declared)
            )
            # Base o URLs ausentes: se dice, no se rellena.
            enriched["base_documentada"] = bool(base) and bool(
                enriched["urls_inferencia"]
            )
        out.append(enriched)
    return out
