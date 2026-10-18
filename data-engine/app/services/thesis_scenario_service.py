"""Vista de escenarios persistidos: solo lectura, sin motores ni LLM.

La tabla anual es la fuente numerica; la traza de ESA version aporta el
linaje. Nunca se mezclan versiones ni se recalcula una tesis al abrirla.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, ThesisProjectionYear, ValuationModel
from app.services.thesis_projection_service import MODEL_TYPE, MODEL_VERSION, SCENARIOS

TITLES = {"bear": "Pesimista", "base": "Central", "bull": "Optimista"}
METRICS = {"ingresos": "revenue", "fcf": "fcf", "bps": "eps"}
TARGET_REASON = (
    "La traza guardada no acredita el origen no LLM de todos los inputs "
    "del precio objetivo; el lector no recalcula ni publica ese valor."
)


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() and isfinite(float(result)) else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _official(fact: dict, cutoff: date) -> bool:
    known = _date(fact.get("fuente_fecha"))
    url = fact.get("fuente_url")
    return bool(
        fact.get("etiqueta") == "OFICIAL"
        and isinstance(url, str) and url.startswith("https://")
        and known and known <= cutoff
        and _number(fact.get("valor")) is not None
    )


def _rate_allowed(rate: dict, kind: str, cutoff: date) -> bool:
    if _number(rate.get("valor")) is None:
        return False
    if _official(rate, cutoff):
        return True
    # El CAGR v1 solo guarda un texto y el resultado, no los facts de sus
    # extremos ni su procedencia. Ningun prefijo prueba que fueran no LLM.
    # Tampoco se reconstruye desde facts actuales: podria cambiar el snapshot.
    if kind == "crecimiento":
        return False
    # El margen FCF derivado usa exactamente las dos anclas del snapshot,
    # cuya oficialidad y coincidencia de ejercicio se comprueban aparte.
    base = rate.get("base")
    return bool(
        rate.get("etiqueta") == "INFERIDO"
        and isinstance(base, str)
        and base.startswith("margen FCF derivado de facts FY")
    )


class ThesisScenarioService:
    def read(self, db: Session, company: Company) -> dict:
        tenant = db.info.get("tenant_id")
        if tenant is None:
            raise ValueError("Se necesita el contexto del usuario para leer sus escenarios.")
        # Evita incluso un autoflush accidental si el caller tiene cambios pendientes.
        with db.no_autoflush:
            model = db.scalar(
                select(ValuationModel).where(
                    ValuationModel.company_id == company.id,
                    ValuationModel.tenant_id == tenant,
                    ValuationModel.model_type == MODEL_TYPE,
                ).order_by(desc(ValuationModel.version), desc(ValuationModel.id)).limit(1)
            )
            rows = [] if model is None else list(db.scalars(
                select(ThesisProjectionYear).where(
                    ThesisProjectionYear.company_id == company.id,
                    ThesisProjectionYear.tenant_id == tenant,
                    ThesisProjectionYear.valuation_model_id == model.id,
                ).order_by(ThesisProjectionYear.fiscal_year)
            ).all())
            return self._view(company, model, rows)

    def _view(self, company: Company, model: ValuationModel | None, rows: list) -> dict:
        trace = _mapping(model.calculation_trace) if model else {}
        cutoff = _date(trace.get("as_of"))
        base = _mapping(trace.get("base"))
        trace_scenarios = _mapping(trace.get("escenarios"))
        reason = None
        if model is None:
            reason = "No hay una proyección thesis-5y guardada para esta acción."
        elif trace.get("model_version") != MODEL_VERSION or trace.get("model_type") != MODEL_TYPE:
            reason = "Versión de proyección sin contrato de procedencia compatible."
        elif cutoff is None or cutoff > date.today():
            reason = "La fecha de corte falta, es invalida o es futura."
        elif not rows:
            reason = "La última versión no tiene filas anuales; no se usa una versión anterior."
        source = {
            "tabla": "thesis_projection_years",
            "valuation_model_id": model.id if model else None,
            "version": model.version if model else None,
            "modelo": trace.get("model_version"),
            "fecha": cutoff.isoformat() if cutoff else None,
        }
        scenarios = {}
        for scenario in SCENARIOS:
            saved = _mapping(trace_scenarios.get(scenario))
            raw_years = saved.get("proyecciones")
            raw_years = raw_years if isinstance(raw_years, list) else []
            projections = []
            for row in rows:
                if row.scenario != scenario:
                    continue
                matches = [r for r in raw_years if isinstance(r, dict) and r.get("ejercicio") == row.fiscal_year]
                raw = matches[0] if len(matches) == 1 else {}
                row_reason = reason
                if not row_reason and (not raw or row.as_of != cutoff):
                    row_reason = "Fila anual sin traza unica de la misma versión y fecha de corte."
                values = {}
                for metric, column in METRICS.items():
                    blocked = row_reason or self._lineage_reason(metric, raw, base, cutoff)
                    # Un crecimiento LLM en un ano anterior contamina toda la
                    # cadena de ingresos, incluso si este ano usa el CAGR.
                    predecessors = [r for r in raw_years if isinstance(r, dict)
                                    and isinstance(r.get("ejercicio"), int)
                                    and r["ejercicio"] <= row.fiscal_year]
                    base_year = _mapping(base.get("ingresos")).get("ejercicio")
                    chain_years = sorted(r["ejercicio"] for r in predecessors)
                    if not blocked and (
                        not isinstance(base_year, int)
                        or not 1 <= row.fiscal_year - base_year <= 10
                        or chain_years != list(range(base_year + 1, row.fiscal_year + 1))
                    ):
                        blocked = "La cadena anual de ingresos esta incompleta o duplicada."
                    if not blocked and cutoff is not None and any(
                        not _rate_allowed(_mapping(r.get("crecimiento")), "crecimiento", cutoff)
                        for r in predecessors
                    ):
                        blocked = "Un ejercicio anterior usa crecimiento sin linaje determinista acreditado."
                    value = _number(getattr(row, column))
                    expected = _number(raw.get(metric))
                    tolerance = Decimal("0.00000001" if metric == "bps" else "0.000001")
                    if not blocked and (value is None or expected is None):
                        blocked = "Falta el valor persistido o su valor en la traza."
                    if not blocked and value is not None and expected is not None and abs(value - expected) > tolerance:
                        blocked = "La cifra anual no coincide con la traza de esta versión."
                    if not blocked and row.label != "INFERIDO":
                        blocked = "La fila no esta etiquetada como proyección inferida."
                    values[metric] = {
                        "valor": float(value) if not blocked and value is not None else None,
                        "etiqueta": "N/D" if blocked else "INFERIDO",
                        "fuente": {**source, "fila_id": row.id, "detalle": row.source},
                        "fecha": source["fecha"],
                        "fuentes_base": self._sources(base),
                        "motivo": blocked,
                        "metodo": {
                            "ingresos": "Cadena de ingresos por crecimiento guardado en thesis-5y.",
                            "fcf": "Ingresos proyectados por margen FCF guardado en thesis-5y.",
                            "bps": "Ingresos proyectados por margen neto y dividido por acciones de thesis-5y.",
                        }[metric],
                    }
                projections.append({"ejercicio": row.fiscal_year, **values})
            scenarios[scenario] = {
                "nombre": TITLES[scenario],
                "proyecciones": projections,
                "motivo": reason or (None if projections else "Faltan filas anuales de este escenario."),
                "precio_objetivo_5y": {
                    "valor": None, "etiqueta": "N/D", "fuente": source,
                    "fecha": source["fecha"], "motivo": reason or TARGET_REASON,
                },
            }
        return {
            "ticker": company.ticker,
            "estado": "N/D" if reason else "persistido",
            "motivo": reason,
            "fuente": source,
            "escenarios": scenarios,
            "aviso_coherencia": trace.get("aviso_coherencia"),
            "disclaimer": "Escenarios del modelo, no datos oficiales ni recomendaciones de inversión. "
                          "Vista de solo lectura: no genera cifras ni consume cuota o servicios de pago.",
        }

    @staticmethod
    def _sources(base: dict) -> list[dict]:
        return [
            {"metrica": key, "url": fact.get("fuente_url"), "fecha": fact.get("fuente_fecha")}
            for key, fact in base.items()
            if isinstance(fact, dict) and fact.get("fuente_url")
        ]

    @staticmethod
    def _lineage_reason(metric: str, raw: dict, base: dict, cutoff: date | None) -> str | None:
        if cutoff is None:
            return "Falta la fecha de corte."
        if not _official(_mapping(base.get("ingresos")), cutoff):
            return "Falta el ancla de ingresos OFICIAL con fuente y fecha."
        if not _rate_allowed(_mapping(raw.get("crecimiento")), "crecimiento", cutoff):
            return "Crecimiento sin linaje completo persistido: faltan la procedencia de los extremos historicos del CAGR o una tasa OFICIAL con fuente y fecha."
        if metric == "fcf":
            if not _official(_mapping(base.get("fcf")), cutoff):
                return "Falta el ancla FCF OFICIAL con fuente y fecha."
            if _mapping(base.get("fcf")).get("ejercicio") != _mapping(base.get("ingresos")).get("ejercicio"):
                return "Las anclas de FCF e ingresos no corresponden al mismo ejercicio."
            if not _rate_allowed(_mapping(raw.get("margen_fcf")), "margen_fcf", cutoff):
                return "Margen FCF ausente o sin linaje determinista acreditado (puede incluir inputs LLM)."
        if metric == "bps" and any(
            not _official(_mapping(base.get(key)), cutoff) for key in ("resultado_neto", "acciones")
        ):
            return "Faltan resultado neto o acciones OFICIALES con fuente y fecha."
        return None
