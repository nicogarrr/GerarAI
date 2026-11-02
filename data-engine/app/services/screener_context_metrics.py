"""Metricas de contexto del screener: valoracion, tesis y nivel DCA.

El motor de screener solo veia CalculatedMetric/FinancialFact. Estos nombres
conectan el screener con el resto de la app y se pueden usar en cualquier
criterio o formula de ranking:

- ``margen_seguridad``: margen de seguridad del motor de valoracion persistido
  (``ValuationModel`` mas reciente de la empresa; decimal, 0.25 = 25 %). Si la
  ultima valoracion es ``insufficient_data`` o no trae margen, falta el dato:
  no se reutiliza una valoracion anterior.
- ``tiene_tesis``: 1 si la empresa tiene alguna version de tesis con datos
  (cualquier estado salvo ``insufficient_data`` y ``rejected``), 0 si no.
- ``tesis_publicada``: 1 si tiene una tesis ``published``, 0 si no.
- ``nivel_dca``: nivel del motor DCA (4..1 compra, -1/-2 recorte) leido de
  ``dca_signal_states``. Degrada limpio: si la tabla no existe (el motor DCA
  aun no esta mergeado) o el ticker no tiene nivel, el dato FALTA (la empresa no
  casa y el screener lo lista en ``metrics_without_data``), nunca es un 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy import desc, inspect, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, ThesisVersion, ValuationModel, ValuationOutput
from app.valuation.margin_convention import margin_convention_known

MARGIN_OF_SAFETY = "margen_seguridad"
HAS_THESIS = "tiene_tesis"
PUBLISHED_THESIS = "tesis_publicada"
DCA_LEVEL = "nivel_dca"
CONTEXT_METRICS: tuple[str, ...] = (MARGIN_OF_SAFETY, HAS_THESIS, PUBLISHED_THESIS, DCA_LEVEL)

_NOT_A_THESIS = ("insufficient_data", "rejected")
_DCA_TABLE = "dca_signal_states"


def _observation_cls():
    # Import diferido: screener_service importa este modulo.
    from app.services.screener_service import Observation

    return Observation


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _margin_of_safety(db: Session) -> dict[int, Any]:
    Observation = _observation_cls()
    latest: dict[int, ValuationModel] = {}
    for model in db.scalars(
        select(ValuationModel).where(*tenant_filters(db, ValuationModel)).order_by(ValuationModel.company_id, desc(ValuationModel.version))
    ).all():
        latest.setdefault(model.company_id, model)
    result: dict[int, Any] = {}
    for company_id, model in latest.items():
        if model.status == "insufficient_data":
            continue
        outputs = list(
            db.scalars(
                select(ValuationOutput).where(
                    *tenant_filters(db, ValuationOutput),
                    ValuationOutput.valuation_model_id == model.id,
                )
            ).all()
        )
        outputs.sort(key=lambda row: row.scenario != "base")
        value = None
        for output in outputs:
            payload = output.output_payload or {}
            if not margin_convention_known(payload.get("trace")):
                continue
            value = _decimal(payload.get("margin_of_safety"))
            if value is not None:
                break
        if value is None:
            continue
        result[company_id] = Observation(
            value,
            Decimal("0.70"),
            model.updated_at or model.created_at,
            f"v{model.version}",
            f"motor de valoración v{model.version} ({model.status})",
            [model.id],
        )
    return result


def _thesis_flags(db: Session, company_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    Observation = _observation_cls()
    rows = db.execute(
        select(ThesisVersion.company_id, ThesisVersion.status, ThesisVersion.id).where(
            *tenant_filters(db, ThesisVersion)
        )
    ).all()
    has: dict[int, int] = {}
    published: dict[int, int] = {}
    for company_id, status, thesis_id in rows:
        if status not in _NOT_A_THESIS:
            has.setdefault(company_id, thesis_id)
        if status == "published":
            published.setdefault(company_id, thesis_id)
    result: dict[int, dict[str, Any]] = {}
    for company_id in company_ids:
        result[company_id] = {
            HAS_THESIS: Observation(
                Decimal(1 if company_id in has else 0), Decimal("1"), None, "actual",
                "tesis", [has[company_id]] if company_id in has else [],
            ),
            PUBLISHED_THESIS: Observation(
                Decimal(1 if company_id in published else 0), Decimal("1"), None, "actual",
                "tesis", [published[company_id]] if company_id in published else [],
            ),
        }
    return result


def dca_table_available(db: Session) -> bool:
    try:
        return inspect(db.get_bind()).has_table(_DCA_TABLE)
    except Exception:  # noqa: BLE001 - sin tabla legible = sin nivel DCA, nunca rompe el screener
        return False


def _dca_levels(db: Session, companies: list[Company]) -> dict[int, Any]:
    """Nivel DCA por empresa; {} si el motor DCA no esta desplegado."""
    if not dca_table_available(db):
        return {}
    Observation = _observation_cls()
    table = sa.table(
        _DCA_TABLE,
        sa.column("id"),
        sa.column("tenant_id"),
        sa.column("symbol"),
        sa.column("company_id"),
        sa.column("level"),
        sa.column("status"),
        sa.column("period"),
        sa.column("signal_date"),
    )
    statement = select(
        table.c.id, table.c.symbol, table.c.company_id, table.c.level,
        table.c.status, table.c.period, table.c.signal_date,
    )
    tenant_id = db.info.get("tenant_id")
    if tenant_id is not None:
        statement = statement.where(table.c.tenant_id == tenant_id)
    try:
        rows = db.execute(statement).all()
    except Exception:  # noqa: BLE001 - esquema distinto al esperado: se degrada a "sin nivel"
        return {}
    by_company = {row.company_id: row for row in rows if row.company_id is not None}
    by_symbol = {str(row.symbol).upper(): row for row in rows}
    result: dict[int, Any] = {}
    for company in companies:
        row = by_company.get(company.id) or by_symbol.get(company.ticker.upper())
        if row is None or row.level is None:
            continue
        # as_of=None: la fecha va en la fuente. Mezclar date/str con los
        # datetime de las metricas romperia el max() de latest_data_at.
        result[company.id] = Observation(
            Decimal(int(row.level)),
            Decimal("1"),
            None,
            str(row.period),
            f"motor DCA ({row.status}, cierre {row.signal_date})",
            [int(row.id)],
        )
    return result


def context_observations(
    db: Session,
    names: Iterable[str],
    companies: list[Company] | None = None,
) -> dict[int, dict[str, Any]]:
    """Observaciones de contexto por company_id, solo para los nombres pedidos."""
    wanted = set(names) & set(CONTEXT_METRICS)
    if not wanted:
        return {}
    if companies is None:
        companies = list(db.scalars(select(Company)).all())
    result: dict[int, dict[str, Any]] = {}
    if MARGIN_OF_SAFETY in wanted:
        for company_id, observation in _margin_of_safety(db).items():
            result.setdefault(company_id, {})[MARGIN_OF_SAFETY] = observation
    if wanted & {HAS_THESIS, PUBLISHED_THESIS}:
        for company_id, flags in _thesis_flags(db, [c.id for c in companies]).items():
            for name, observation in flags.items():
                if name in wanted:
                    result.setdefault(company_id, {})[name] = observation
    if DCA_LEVEL in wanted:
        for company_id, observation in _dca_levels(db, companies).items():
            result.setdefault(company_id, {})[DCA_LEVEL] = observation
    return result


def _any_real_thesis(db: Session) -> bool:
    """Existe alguna tesis con datos (cualquier estado salvo insufficient/rejected)."""
    return (
        db.scalar(
            select(ThesisVersion.id)
            .where(*tenant_filters(db, ThesisVersion), ThesisVersion.status.not_in(_NOT_A_THESIS))
            .limit(1)
        )
        is not None
    )


def _any_margin_of_safety(db: Session) -> bool:
    """Alguna empresa tiene margen conocido en su ultima valoracion.

    Misma semantica que _margin_of_safety, pero de existencia: en vez de una
    consulta de outputs POR empresa (N+1), proyecta IDs/estado de modelos y
    solo margen/convenio de los outputs en consultas IN acotadas. No hidrata
    los traces ni las proyecciones completas para una prueba de existencia.
    Conserva la seleccion de ultima version y validacion decimal original.
    """
    latest = {}
    for model in db.execute(select(
        ValuationModel.id, ValuationModel.company_id,
        ValuationModel.version, ValuationModel.status,
    ).where(*tenant_filters(db, ValuationModel))
      .order_by(ValuationModel.company_id, desc(ValuationModel.version))).all():
        latest.setdefault(model.company_id, model)
    ids = [model.id for model in latest.values() if model.status != "insufficient_data"]
    # Existence only: no calculation_trace, scenario projections or full output
    # payloads need to cross the database connection. The convention still
    # comes from the stored trace, never from the numeric column or its date.
    margin_type = (
        sa.func.json_type(ValuationOutput.output_payload, "$.margin_of_safety")
        if db.get_bind().dialect.name == "sqlite"
        else sa.func.json_typeof(ValuationOutput.output_payload["margin_of_safety"])
    )
    for start in range(0, len(ids), 5000):
        rows = db.execute(select(
            ValuationOutput.output_payload["margin_of_safety"],
            ValuationOutput.output_payload["trace"]["margin_of_safety_convention"],
            margin_type,
        ).where(*tenant_filters(db, ValuationOutput),
                ValuationOutput.valuation_model_id.in_(ids[start:start + 5000]))).all()
        for margin, convention, value_type in rows:
            if value_type in {"boolean", "true", "false"}:
                continue
            if (margin_convention_known({"margin_of_safety_convention": convention})
                    and _decimal(margin) is not None):
                return True
    return False


def context_metrics_with_data(db: Session) -> list[str]:
    """Nombres de contexto que al menos una empresa tiene (para las sugerencias de la UI)."""
    companies = list(db.scalars(select(Company)).all())
    if not companies:
        return []
    names: set[str] = set()
    # tiene_tesis/tesis_publicada solo se ofrecen si alguna empresa tiene
    # tesis real, para no sugerir un filtro que no filtra (misma regla que
    # antes: publicada se mantiene aunque nadie la tenga publicada).
    if _any_real_thesis(db):
        names |= {HAS_THESIS, PUBLISHED_THESIS}
    if _any_margin_of_safety(db):
        names.add(MARGIN_OF_SAFETY)
    # Nivel DCA: {} si la tabla no existe o nadie tiene nivel (degrada limpio).
    if _dca_levels(db, companies):
        names.add(DCA_LEVEL)
    return sorted(names)
