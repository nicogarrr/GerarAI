"""Control de la tesis frente al consenso de analistas.

Aplica la regla ya implementada en ``app.valuation.consensus_sanity``: si el
valor de GerarAI se aleja más de un 35 % del consenso (o queda fuera del rango
de objetivos), la diferencia tiene que estar conciliada dato a dato o la
valoración queda en «revisar» y no se publica. El consenso y los supuestos de
analista salen de fuentes reales; si faltan, el control lo dice y no inventa
una conciliación. Nunca lanza hacia la generación de la tesis.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.valuation.consensus_context import analyst_inputs_for_dcf, load_consensus
from app.valuation.consensus_sanity import (
    REVIEW_BLOCKER,
    apply_consensus_sanity,
    consensus_sanity_for_dcf,
)

#: Unidad mayor de cada subunidad que Yahoo usa en algunos listados.
_MAJOR = {
    "GBP": "GBP",
    "GBX": "GBP",
    "GBPENCE": "GBP",
    "ZAR": "ZAR",
    "ZAC": "ZAR",
    "ILS": "ILS",
    "ILA": "ILS",
}
#: Cuántas subunidades hay en una unidad mayor (solo para normalizar el consenso).
_SUBUNITS = {"GBX", "GBPENCE", "ZAC", "ILA"}


def _unit(value: Any) -> str | None:
    if isinstance(value, dict):
        value = (
            value.get("value_currency")
            or value.get("price_currency")
            or value.get("reporting_currency")
        )
    text = str(value or "").strip()
    return text or None


def _major(unit: str | None) -> str | None:
    if unit is None:
        return None
    return _MAJOR.get(unit.upper(), unit.upper())


def _scale(unit: str | None) -> float:
    return 100.0 if unit and unit.upper() in _SUBUNITS else 1.0


def _our_currency(valuation: dict[str, Any]) -> str | None:
    trace = valuation.get("trace") or {}
    candidates = (
        valuation.get("value_currency"),
        valuation.get("price_currency"),
        (valuation.get("currency") or {}).get("value_currency")
        if isinstance(valuation.get("currency"), dict)
        else None,
        (valuation.get("currency") or {}).get("price_currency")
        if isinstance(valuation.get("currency"), dict)
        else None,
        trace.get("value_currency"),
        trace.get("price_currency"),
        valuation.get("currency"),
    )
    for candidate in candidates:
        unit = _unit(candidate)
        if unit:
            return unit
    return None


def _our_value(valuation: dict[str, Any]) -> float | None:
    for key in ("base_value", "expected_value"):
        value = valuation.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if number > 0:
            return number
    return None


def apply_consensus_control(
    db: Session,
    company: Any,
    valuation: dict[str, Any],
    *,
    enabled: bool | None = None,
    block_publication: bool = True,
) -> dict[str, Any]:
    """Contrasta ``valuation`` con el consenso y deja el blocker si toca."""
    if enabled is None:
        settings = get_settings()
        # En test/CI no se hace red por defecto; los tests del control pasan
        # enabled=True explícitamente. En producción/local queda encendido.
        enabled = bool(settings.consensus_control_enabled) and settings.app_env.strip().lower() not in {
            "test",
            "ci",
        }
    if not enabled:
        return {"status": "disabled"}
    snapshot = load_consensus(db, company)
    if snapshot is None:
        return {
            "status": "sin_consenso",
            "reason": "no se pudo obtener el consenso de analistas",
            "threshold": 0.35,
        }
    our_unit = _our_currency(valuation)
    our_major = _major(our_unit)
    consensus_major = _major(snapshot.currency)
    if our_major and consensus_major and our_major != consensus_major:
        return {
            "status": "no_comparable",
            "reason": (
                f"consenso en {snapshot.currency} y valor en {our_unit}: "
                "no se comparan magnitudes de divisas distintas"
            ),
            "consensus": snapshot.as_dict(),
            "threshold": 0.35,
        }
    # Yahoo puede dar el consenso en peniques/centavos (GBp/GBX, ZAc, ILa)
    # mientras la valoración está en la unidad mayor. Se normaliza al valor
    # primero; la ficha conserva la unidad original del consenso.
    factor = _scale(our_unit) / _scale(snapshot.currency)
    consensus_value = snapshot.mean if snapshot.mean is not None else snapshot.median
    if consensus_value is not None:
        consensus_value = float(consensus_value) * factor
    low = snapshot.low * factor if snapshot.low is not None else None
    high = snapshot.high * factor if snapshot.high is not None else None
    analyst_inputs = analyst_inputs_for_dcf(db, company)
    sanity = consensus_sanity_for_dcf(
        valuation,
        consensus=consensus_value,
        analyst_inputs=analyst_inputs.inputs,
        our_value=_our_value(valuation),
        labels=analyst_inputs.labels,
        sources=analyst_inputs.sources,
        target_low=low,
        target_high=high,
        consensus_source=snapshot.source,
    )
    apply_consensus_sanity(valuation, sanity, enabled=True, block_publication=block_publication)
    result = sanity.as_dict()
    result["block_publication"] = block_publication
    result["consensus"] = snapshot.as_dict()
    result["consensus_basis"] = "mean" if snapshot.mean is not None else "median"
    result["comparison"] = {
        "unit": our_unit,
        "consensus_unit": snapshot.currency,
        "factor": factor,
        "consensus_mean": consensus_value,
        "consensus_low": low,
        "consensus_high": high,
    }
    result["analyst_inputs"] = analyst_inputs.as_dict()
    result["our_value_basis"] = (
        "base_value" if valuation.get("base_value") is not None else "expected_value"
    )
    result["data_rows"] = [
        {
            "input": "valor_gerarai",
            "name": "valor por acción de GerarAI",
            "value": _our_value(valuation),
            "unit": our_unit,
            "source": "motor de valoración",
            "method": (valuation.get("trace") or {}).get("engine") or "model",
        },
        {
            "input": "precio_actual",
            "name": "precio de mercado usado por el modelo",
            "value": valuation.get("current_price"),
            "unit": our_unit,
            "source": (valuation.get("trace") or {}).get("price_source"),
            "method": "market_price",
        },
        {
            "input": "consenso_media",
            "name": f"consenso de analistas ({result['consensus_basis']})",
            "value": consensus_value,
            "unit": our_unit,
            "source": snapshot.source,
            "method": "analyst_consensus",
        },
        {
            "input": "consenso_rango",
            "name": "rango de objetivos (bajo/alto)",
            "value": (low, high),
            "unit": our_unit,
            "source": snapshot.source,
            "method": "analyst_consensus",
        },
        *analyst_inputs.rows,
    ]
    if block_publication and sanity.needs_review and REVIEW_BLOCKER not in (valuation.get("publication_blockers") or []):
        blockers = list(valuation.get("publication_blockers") or [])
        blockers.append(REVIEW_BLOCKER)
        valuation["publication_blockers"] = blockers
        valuation["publishable"] = False
    return result


__all__ = ["apply_consensus_control"]
