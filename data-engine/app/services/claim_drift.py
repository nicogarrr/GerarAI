"""Deriva entre la cifra de un claim de tesis y el hecho vivo del mismo periodo.

Una tesis guardada es una foto: si despues se reingesta un hecho (p. ej. KO FY2025
deuda total 42,12 en la tesis frente a 45,436 mil M vivos, medido por el Piloto),
la cifra guardada y la viva dejan de coincidir. Aqui solo se detecta y se AVISA;
nunca se edita la tesis (se regenera por el flujo LLM) ni se oculta la cifra.

Clave comparable: (metrica, periodo, unidad). Sin unidad, sin periodo, con unidades
distintas o con varios hechos vivos que no coinciden entre si, no se afirma deriva.
Los claims guardan al generarse el valor, la metrica, el periodo y la unidad
(``claim_drift_metadata``); los hechos vivos se leen de FinancialFact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

#: Diferencia relativa a partir de la cual una cifra deja de ser la misma.
DRIFT_TOLERANCE = 0.005

DRIFT_WARNING_ES = "cifra desactualizada, regenerar"

Key = tuple[str, str, str]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, str) or number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def claim_drift_metadata(payload: dict) -> dict[str, Any]:
    """Campos a guardar en Claim.metadata_ para poder medir la deriva despues.

    Vacio si el claim no tiene cifra numerica, metrica, periodo y unidad: sin la
    clave completa no hay comparacion posible y no se inventa ninguna.
    """
    value = _number(payload.get("object"))
    metric = str(payload.get("predicate") or "").strip()
    period = str(payload.get("period") or "").strip()
    unit = str(payload.get("unit") or "").strip()
    if value is None or not metric or not period or not unit:
        return {}
    return {
        "claim_value": value,
        "claim_metric": metric,
        "claim_period": period,
        "claim_unit": unit,
    }


def live_fact_map(facts: Iterable[Any]) -> dict[Key, float | None]:
    """{(metrica, periodo, unidad): valor}; None si hay varios valores distintos."""
    seen: dict[Key, set[float]] = {}
    for fact in facts:
        value = _number(getattr(fact, "value", None))
        key = (
            str(getattr(fact, "metric", "") or ""),
            str(getattr(fact, "period", "") or ""),
            str(getattr(fact, "unit", "") or ""),
        )
        if value is None or not all(key):
            continue
        seen.setdefault(key, set()).add(value)
    return {key: next(iter(values)) if len(values) == 1 else None for key, values in seen.items()}


def claim_drift(
    claims: Iterable[Mapping[str, Any]],
    live_facts: Mapping[Key, float | None],
    *,
    tolerance: float = DRIFT_TOLERANCE,
) -> list[dict[str, Any]]:
    """Claims cuya cifra guardada difiere del hecho vivo de su (metrica, periodo, unidad).

    ``claims``: metadatos de Claim (con claim_value/metric/period/unit). Sin hecho
    vivo comparable (otra unidad, otro periodo, ambiguo) o sin cifra guardada no
    se afirma deriva.
    """
    drifted: list[dict[str, Any]] = []
    reported: set[Key] = set()
    for claim in claims:
        stored = _number(claim.get("claim_value"))
        key = (
            str(claim.get("claim_metric") or ""),
            str(claim.get("claim_period") or ""),
            str(claim.get("claim_unit") or ""),
        )
        live = _number(live_facts.get(key))
        if stored is None or live is None or not all(key) or key in reported:
            continue
        base = max(abs(stored), abs(live))
        if base == 0:
            continue
        delta = abs(stored - live) / base
        if delta > tolerance:
            reported.add(key)
            drifted.append(
                {
                    "metric": key[0],
                    "period": key[1],
                    "unit": key[2],
                    "stored_value": stored,
                    "live_value": live,
                    "relative_difference": round(delta, 4),
                    "warning": DRIFT_WARNING_ES,
                }
            )
    return drifted


def thesis_drift(claims: Iterable[Any], facts: Iterable[Any], thesis_id: int | None) -> list[dict[str, Any]]:
    """Deriva de los claims de UNA tesis frente a una lista de hechos vivos."""
    if thesis_id is None:
        return []
    metas = [
        claim.metadata_
        for claim in claims
        if getattr(claim, "thesis_version_id", None) == thesis_id
        and getattr(claim, "status", None) != "superseded"
        and isinstance(getattr(claim, "metadata_", None), dict)
    ]
    return claim_drift(metas, live_fact_map(facts))


def thesis_claim_drift(db: Session, thesis: Any) -> list[dict[str, Any]]:
    """Lee claims de la tesis y sus hechos vivos (misma empresa y tenant) y mide la deriva."""
    from app.models.entities import Claim, FinancialFact

    tenant_id = db.info.get("tenant_id")
    claim_stmt = select(Claim).where(Claim.thesis_version_id == thesis.id)
    if tenant_id is not None:
        claim_stmt = claim_stmt.where(Claim.tenant_id == tenant_id)
    claims = [c for c in db.scalars(claim_stmt).all() if (c.metadata_ or {}).get("claim_metric")]
    if not claims:
        return []
    # Lectura acotada a las claves de los claims (metrica, periodo, unidad): no
    # depende de "el ultimo hecho por metrica" que enseña el chat, asi una tesis
    # FY2025 se compara con el hecho FY2025 aunque ya exista el FY2026.
    metas = [c.metadata_ for c in claims]
    fact_stmt = select(FinancialFact).where(
        FinancialFact.company_id == thesis.company_id,
        FinancialFact.metric.in_({m["claim_metric"] for m in metas}),
        FinancialFact.period.in_({m.get("claim_period") for m in metas if m.get("claim_period")}),
        FinancialFact.unit.in_({m.get("claim_unit") for m in metas if m.get("claim_unit")}),
    )
    if tenant_id is not None:
        fact_stmt = fact_stmt.where(FinancialFact.tenant_id == tenant_id)
    return thesis_drift(claims, db.scalars(fact_stmt).all(), thesis.id)


def drift_notice_es(drift: list[dict[str, Any]], labels: Mapping[str, str] | None = None) -> str:
    """Aviso para el usuario: dice que cifras no coinciden, sin ocultar ni reescribir la tesis."""
    if not drift:
        return ""
    names = sorted({(labels or {}).get(item["metric"], item["metric"]) for item in drift})
    listed = ", ".join(names)
    return (
        f"Aviso: {listed} de esta tesis ya no coincide con los datos actuales "
        f"({DRIFT_WARNING_ES} la tesis)."
        if len(names) == 1
        else f"Aviso: {listed} de esta tesis ya no coinciden con los datos actuales "
        f"({DRIFT_WARNING_ES} la tesis)."
    )
