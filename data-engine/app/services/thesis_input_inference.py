"""Inputs antes de generar la tesis: fuentes cruzadas, calculo y, al final, modelo.

0. FMP como segunda fuente de deuda, caja, acciones y FCF (Yahoo entra en la
   evidencia de cada tesis): el snapshot las cruza siempre.

Owner 3-nov-2026: «si falta algun dato concreto, intentar sacarlo con el LLM
haciendo los calculos necesarios o inferencias». Corre FUERA del SAVEPOINT de
la tesis (la inferencia hace commit) y nunca rompe la generacion:

1. WACC trazable ausente -> se recalcula la metrica (CalculatedMetric) con el
   motor de metricas; en perdidas usa escudo fiscal 0 % etiquetado.
2. Quema de caja o margen FCF ausente -> margen FCF OBJETIVO inferido por el
   modelo SOLO sobre extractos de documentos ya ingeridos, con base y URLs
   (``inferred_input_llm_service``: cuota diaria por tenant y presupuesto).
   El motor lo usa para la senda a rentabilidad, siempre orientativa.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Company

logger = logging.getLogger(__name__)

NEEDS_FCF_TARGET = frozenset({"non_negative_fcf_margin", "normalized_fcf_or_fcf_margin"})


FMP_FRESH_DAYS = 7


def refresh_fmp_for_cross_check(db: Session, company: Company) -> str:
    """Segunda fuente para el cruce (owner 3-nov-2026: «Yahoo y FMP» siempre).

    Solo con clave configurada y si los datos FMP de la empresa tienen mas de
    una semana (el plan gratuito tiene cuota diaria). El plan gratuito no
    cubre fuera de EE. UU. (402): se anota y se sigue. El texto de error de
    httpx lleva la URL con la clave: nunca se registra, solo el codigo.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.core.config import get_settings
    from app.models import FinancialFact

    if not get_settings().fmp_api_key:
        return "sin_clave"
    newest = db.scalar(
        select(func.max(FinancialFact.created_at)).where(
            FinancialFact.company_id == company.id, FinancialFact.source_type == "FMP"
        )
    )
    db.rollback()
    if newest is not None:
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=UTC)
        if datetime.now(UTC) - newest < timedelta(days=FMP_FRESH_DAYS):
            return "reciente"
    try:
        from app.services.async_bridge import run_from_any_context
        from app.services.financial_ingestion_service import FinancialIngestionService

        run_from_any_context(FinancialIngestionService().refresh_from_fmp(db=db, company=company))
        db.commit()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - fuente opcional
        db.rollback()
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 402:
            return "plan_no_cubre"
        return f"error:{type(exc).__name__}" + (f":{status}" if status else "")


def _prepare_sector_inputs(db: Session, company: Company, valuation: dict[str, Any]) -> Any:
    """Inputs de motores sectoriales (cap rate, ratio combinado, descuento de
    holding) del carril sector-inputs: ``sector_inputs.prepare_sector_inputs``
    nunca lanza y devuelve un dict de estado. Se resuelve en tiempo de
    ejecucion para no acoplar el orden de los dos cambios."""
    import importlib

    try:
        module = importlib.import_module("app.services.sector_inputs")
    except ImportError:
        return "no_disponible"
    fn = getattr(module, "prepare_sector_inputs", None)
    if fn is None:
        return "no_disponible"
    try:
        result = fn(db, company, valuation)
        db.commit()
        return result
    except Exception as exc:  # noqa: BLE001 - opcional
        db.rollback()
        return f"error:{type(exc).__name__}"


def prepare_missing_inputs(db: Session, company: Company) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["fmp"] = refresh_fmp_for_cross_check(db, company)
    try:
        from app.valuation.engines.base import traceable_wacc

        if traceable_wacc(db, company) is None:
            from app.services.metric_calculation_service import MetricCalculationService

            metric = MetricCalculationService().calculate(db, company, "wacc", persist=True)
            db.commit()
            out["wacc"] = metric.status
    except Exception as exc:  # noqa: BLE001 - opcional
        db.rollback()
        out["wacc"] = f"error:{type(exc).__name__}"
    try:
        from app.services.inferred_input_service import InferredInputService
        from app.services.valuation_service import ValuationService

        valuation = ValuationService().value_company(db, company)
        db.rollback()  # value_company solo lee; no arrastrar la tx a la llamada LLM
        out["sector_inputs"] = _prepare_sector_inputs(db, company, valuation)
        missing = set(valuation.get("missing_inputs") or [])
        if valuation.get("status") != "insufficient_data" or not (missing & NEEDS_FCF_TARGET):
            out["fcf_margin_target"] = "no_aplica"
            return out
        if InferredInputService().latest_valid(db, company.id, "fcf_margin") is not None:
            out["fcf_margin_target"] = "ya_inferido"
            return out
        from app.services.async_bridge import run_from_any_context
        from app.services.inferred_input_llm_service import infer_input

        row = run_from_any_context(infer_input(db, company.ticker, input_key="fcf_margin"))
        db.commit()
        out["fcf_margin_target"] = {"status": "inferido", "value": float(row.value)}
    except Exception as exc:  # noqa: BLE001 - cuota, presupuesto, sin extractos: N/D honesto
        db.rollback()
        reason = getattr(exc, "reason", None) or str(exc)[:120] or type(exc).__name__
        logger.info("inferencia de margen FCF omitida para %s: %s", company.ticker, reason)
        out["fcf_margin_target"] = f"omitido:{reason}"
    return out
