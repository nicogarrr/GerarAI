"""Inputs declarados: huecos del modelo de una empresa y su almacén por tenant.

Primera pieza del pipeline automático de inputs que faltan (feature aprobada
por Nico, 4-nov-2026: «debe ser capaz Cerebro de hacer esto»). Sirve para
CUALQUIER empresa cuyo marco declare una fórmula de drivers (red/suscripción,
capacidad, plataforma...); no hay nada por ticker.

Este módulo NO llama a ningún LLM ni a la red. Hace tres cosas:

1. ``detect_gaps``: toma el marco resuelto de la empresa
   (``resolve_company_framework``) y los inputs de su fórmula
   (``FORMULAS[marco].inputs`` + ``required_fact_metrics``). Un input está
   CUBIERTO si existe, para ese tenant y esa empresa, (a) un ``FinancialFact``
   anual numérico (el mismo criterio que usa ``DriverOperatingModel``), (b) un
   KPI aprobado (``KPIExtractionCandidate`` en ``approved`` con valor), o
   (c) una fila vigente y válida de ``declared_input_values``. Si no, es un
   hueco (``InputGap``) con su dimensión esperada, sus límites y el porqué.
2. ``upsert``: guarda un input declarado con rango, estado, método y fuente,
   validado (límites, unidad, fuente según el estado). Es idempotente (el
   mismo contenido no crea fila nueva) y no sobrescribe: la fila anterior
   queda con ``superseded_at``. Precedencia por estado:
   manual > oficial > derivado > estimado > supuesto_por_defecto; un valor de
   menor precedencia no desplaza al vigente.
3. ``current`` / ``retire``: lectura de lo vigente y baja auditada.

Costuras para las PRs siguientes: el extractor oficial (``method='extract'``,
cita + documento), el inferidor acotado (``'infer'``, URL https), la mezcla de
analistas de Nico (``'analyst'`` + ``analyst_firm``: «de analista X,
estimado»), los derivados por código (``'derive'``), los valores por defecto
de familia (``'default'``, bloquean la publicación) y el motor de
red/suscripción, que leerá ``current`` para rellenar lo que ``detect_gaps``
marque. ``extra_inputs`` permite al motor añadir sus propias claves
(``segments.*``, ``deployment.*``...) sin tocar este módulo.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import session_tenant_id
from app.models import Company, FinancialFact, KPIExtractionCandidate
from app.models.declared_input_value import (
    DECLARED_INPUT_METHODS,
    DECLARED_INPUT_STATUSES,
    DeclaredInputValue,
)
from app.services.company_framework import CompanyFramework, resolve_company_framework
from app.services.driver_dimensions import (
    ANNUAL_CURRENCY,
    DRIVER_DIMENSIONS,
    PERCENT_UNITS,
    Dimension,
    _parse_explicit_unit,
    _unit_tokens,
)
from app.services.driver_operating_model import FORMULAS, DriverOperatingModel
from app.services.inferred_input_service import is_valid_https_url

# Cada método produce exactamente un estado. Un supuesto de analista es un
# ESTIMADO (no un dato oficial) que además nombra la firma.
METHOD_STATUS: dict[str, str] = {
    "extract": "oficial",
    "infer": "estimado",
    "analyst": "estimado",
    "derive": "derivado",
    "default": "supuesto_por_defecto",
    "manual": "manual",
}

# Mayor número = gana. Un valor nuevo solo desplaza al vigente si su estado
# tiene igual o mayor precedencia (manual siempre gana y queda auditado).
STATUS_PRECEDENCE: dict[str, int] = {
    "manual": 5,
    "oficial": 4,
    "derivado": 3,
    "estimado": 2,
    "supuesto_por_defecto": 1,
}

# Límites por clave: (mínimo exclusivo, máximo inclusivo). Las tasas siguen el
# contrato decimal (5 % = 0.05). Una clave con punto (``segments.us.penetration``)
# usa los límites de su último componente. Claves sin entrada: solo número finito.
INPUT_BOUNDS: dict[str, tuple[float, float]] = {
    "penetration": (0.0, 0.6),
    "penetration_target": (0.0, 0.6),
    "revenue_share": (0.0, 1.0),
    "utilization": (0.0, 1.0),
    "take_rate": (0.0, 1.0),
    "churn": (0.0, 1.0),
    "retention": (0.0, 1.0),
    "occupancy": (0.0, 1.0),
    "royalty_rate": (0.0, 1.0),
    "backlog_conversion": (0.0, 1.0),
    "fee_rate": (0.0, 0.1),
    "combined_ratio": (0.0, 2.0),
    "return_on_tangible_equity": (-1.0, 1.0),
    "organic_growth": (-1.0, 3.0),
    "monthly_arpu": (0.0, 100.0),
    "retail_arpu_month": (0.0, 100.0),
    "life_years": (3.0, 20.0),
    "addressable_subscribers": (0.0, 1e10),
    "addressable_subs": (0.0, 1e10),
    "subscribers": (0.0, 1e10),
    "satellites": (0.0, 1e5),
    "capacity_per_satellite": (0.0, 1e15),
    "price_per_gb": (0.0, 1e3),
}

STATUSES_BLOCKING_PUBLICATION = frozenset({"supuesto_por_defecto"})
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
_QUANT = Decimal("0.00000001")
_DIMENSIONLESS_UNITS = {"decimal", "ratio"}


class DeclaredInputError(ValueError):
    """Input declarado inválido; ``problems`` lista cada motivo en español."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class DeclaredInput:
    """Valor a declarar para un input del modelo de una empresa."""

    input_key: str
    base: float | Decimal
    unit: str
    method: str
    low: float | Decimal | None = None
    high: float | Decimal | None = None
    segment_key: str = ""
    source_url: str | None = None
    source_quote: str | None = None
    document_id: int | None = None
    analyst_firm: str | None = None
    as_of: date | None = None
    model_family: str | None = None
    input_set_version: str | None = None
    fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return METHOD_STATUS.get(self.method, "")


@dataclass(frozen=True)
class InputGap:
    """Un input que el modelo necesita y que nadie cubre todavía."""

    key: str
    segment_key: str
    expected_dimension: str | None
    bounds: tuple[float, float] | None
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "segment_key": self.segment_key,
            "expected_dimension": self.expected_dimension,
            "bounds": list(self.bounds) if self.bounds else None,
            "why": self.why,
        }


@dataclass(frozen=True)
class InputCoverage:
    """De dónde sale un input cubierto (la primera fuente por precedencia)."""

    key: str
    source: str  # financial_fact | approved_kpi | declared_input
    record_ids: tuple[int, ...]
    status: str | None = None
    blocks_publication: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "record_ids": list(self.record_ids),
            "status": self.status,
            "blocks_publication": self.blocks_publication,
        }


@dataclass(frozen=True)
class GapReport:
    framework_key: str
    formula_key: str | None
    required: tuple[str, ...]
    covered: tuple[InputCoverage, ...]
    gaps: tuple[InputGap, ...]

    @property
    def gap_keys(self) -> list[str]:
        return [gap.key for gap in self.gaps]

    def as_dict(self) -> dict[str, Any]:
        return {
            "framework_key": self.framework_key,
            "formula_key": self.formula_key,
            "required": list(self.required),
            "covered": [item.as_dict() for item in self.covered],
            "gaps": [gap.as_dict() for gap in self.gaps],
        }


@dataclass(frozen=True)
class UpsertResult:
    row: DeclaredInputValue
    changed: bool
    reason: str  # created | replaced | unchanged | kept_higher_precedence


def _bounds_for(key: str) -> tuple[float, float] | None:
    return INPUT_BOUNDS.get(key) or INPUT_BOUNDS.get(key.rsplit(".", 1)[-1])


def _dimension_for(key: str) -> Dimension | None:
    return DRIVER_DIMENSIONS.get(key) or DRIVER_DIMENSIONS.get(key.rsplit(".", 1)[-1])


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number.quantize(_QUANT)


def _require_tenant(tenant_id: Any, db: Session | None = None) -> int:
    if type(tenant_id) is not int or tenant_id <= 0:
        raise DeclaredInputError(["hace falta un tenant válido: los inputs declarados son privados"])
    session_tenant = session_tenant_id(db) if db is not None else None
    if session_tenant is not None and session_tenant != tenant_id:
        raise DeclaredInputError(["el tenant pedido no es el de la sesión"])
    return tenant_id


def _unit_problems(key: str, unit: str) -> list[str]:
    raw = (unit or "").strip()
    if not raw:
        return ["falta la unidad"]
    tokens = _unit_tokens(raw)
    if tokens and tokens[0] in PERCENT_UNITS:
        return ["unidad en porcentaje: las tasas van en decimal (5 % = 0.05, unidad 'ratio')"]
    expected = _dimension_for(key)
    if expected is None:
        return []
    explicit = _parse_explicit_unit(raw)
    if explicit is None:
        return []
    if explicit == expected:
        return []
    if explicit == Dimension.of(currency=1) and expected == ANNUAL_CURRENCY:
        return []
    return [f"unidad incompatible: {raw} es {explicit.render()} y {key} espera {expected.render()}"]


class DeclaredInputService:
    """Huecos del modelo declarado y almacén de inputs declarados (por tenant)."""

    # ------------------------------------------------------------------ validación
    def validate(self, item: DeclaredInput) -> list[str]:
        problems: list[str] = []
        if not _KEY_RE.match(item.input_key or ""):
            problems.append(f"clave de input no válida: {item.input_key!r}")
        if item.segment_key and not _KEY_RE.match(item.segment_key):
            problems.append(f"segmento no válido: {item.segment_key!r}")
        if item.method not in DECLARED_INPUT_METHODS:
            problems.append(f"método desconocido: {item.method!r}")
        elif item.status not in DECLARED_INPUT_STATUSES:
            problems.append(f"estado desconocido para el método {item.method!r}")

        base = _decimal(item.base)
        low = _decimal(item.low) if item.low is not None else None
        high = _decimal(item.high) if item.high is not None else None
        if base is None:
            problems.append("el valor base no es un número finito")
        if item.low is not None and low is None:
            problems.append("el valor bajo no es un número finito")
        if item.high is not None and high is None:
            problems.append("el valor alto no es un número finito")
        if base is not None:
            if low is not None and low > base:
                problems.append("bajo > base")
            if high is not None and high < base:
                problems.append("alto < base")
            bounds = _bounds_for(item.input_key or "")
            if bounds is not None:
                floor, ceiling = bounds
                for label, value in (("base", base), ("bajo", low), ("alto", high)):
                    if value is not None and not (floor < float(value) <= ceiling):
                        problems.append(f"{label} fuera de rango ({floor}, {ceiling}]: {value.normalize()}")
        problems.extend(_unit_problems(item.input_key or "", item.unit))

        url = (item.source_url or "").strip() or None
        if url is not None and not is_valid_https_url(url):
            problems.append("la fuente debe ser una URL https pública")
        quote = (item.source_quote or "").strip()
        if item.method == "extract":
            if not quote:
                problems.append("un dato oficial necesita la cita literal del documento")
            if url is None and item.document_id is None:
                problems.append("un dato oficial necesita el documento o la URL de origen")
        if item.method in {"infer", "analyst"} and url is None:
            problems.append("un estimado necesita una URL https de la que salga")
        if item.method == "analyst" and not (item.analyst_firm or "").strip():
            problems.append("un supuesto de analista necesita el nombre de la firma")
        if item.method != "analyst" and (item.analyst_firm or "").strip():
            problems.append("analyst_firm solo vale con method='analyst'")
        return problems

    # ------------------------------------------------------------------ lectura
    def current(
        self,
        db: Session,
        *,
        company_id: int,
        tenant_id: int,
        keys: Iterable[str] | None = None,
    ) -> dict[tuple[str, str], DeclaredInputValue]:
        """Filas vigentes por (input_key, segment_key) del tenant y la empresa."""
        tenant = _require_tenant(tenant_id, db)
        statement = select(DeclaredInputValue).where(
            DeclaredInputValue.tenant_id == tenant,
            DeclaredInputValue.company_id == company_id,
            DeclaredInputValue.superseded_at.is_(None),
        )
        wanted = list(keys) if keys is not None else None
        if wanted is not None:
            if not wanted:
                return {}
            statement = statement.where(DeclaredInputValue.input_key.in_(wanted))
        rows = db.scalars(statement.order_by(DeclaredInputValue.id)).all()
        return {(row.input_key, row.segment_key or ""): row for row in rows}

    def history(
        self,
        db: Session,
        *,
        company_id: int,
        tenant_id: int,
        input_key: str,
        segment_key: str = "",
    ) -> list[DeclaredInputValue]:
        """Todas las revisiones (vigente incluida), de la más antigua a la última."""
        tenant = _require_tenant(tenant_id, db)
        return list(
            db.scalars(
                select(DeclaredInputValue)
                .where(
                    DeclaredInputValue.tenant_id == tenant,
                    DeclaredInputValue.company_id == company_id,
                    DeclaredInputValue.input_key == input_key,
                    DeclaredInputValue.segment_key == segment_key,
                )
                .order_by(DeclaredInputValue.id)
            ).all()
        )

    def row_is_valid(self, row: DeclaredInputValue) -> bool:
        """Una fila guardada sigue siendo utilizable con las reglas de hoy."""
        return not self.validate(self._as_item(row))

    # ------------------------------------------------------------------ escritura
    def upsert(
        self,
        db: Session,
        *,
        company: Company,
        tenant_id: int,
        item: DeclaredInput,
        now: datetime | None = None,
    ) -> UpsertResult:
        tenant = _require_tenant(tenant_id, db)
        problems = self.validate(item)
        if problems:
            raise DeclaredInputError(problems)
        segment = item.segment_key or ""
        existing = self.current(db, company_id=company.id, tenant_id=tenant, keys=[item.input_key]).get(
            (item.input_key, segment)
        )
        if existing is not None:
            if self._content(existing) == self._content_of_item(item):
                return UpsertResult(existing, False, "unchanged")
            if STATUS_PRECEDENCE[item.status] < STATUS_PRECEDENCE.get(existing.status, 0):
                return UpsertResult(existing, False, "kept_higher_precedence")
            existing.superseded_at = now or datetime.now(UTC)
            db.flush()
        row = DeclaredInputValue(
            tenant_id=tenant,
            company_id=company.id,
            input_key=item.input_key,
            segment_key=segment,
            low=_decimal(item.low),
            base=_decimal(item.base),
            high=_decimal(item.high),
            unit=item.unit.strip(),
            status=item.status,
            method=item.method,
            source_url=(item.source_url or "").strip() or None,
            source_quote=(item.source_quote or "").strip() or None,
            document_id=item.document_id,
            analyst_firm=(item.analyst_firm or "").strip() or None,
            as_of=item.as_of,
            model_family=item.model_family,
            input_set_version=item.input_set_version,
            fingerprint=item.fingerprint,
            metadata_=dict(item.metadata),
        )
        db.add(row)
        db.flush()
        return UpsertResult(row, True, "replaced" if existing is not None else "created")

    def retire(
        self,
        db: Session,
        *,
        company_id: int,
        tenant_id: int,
        input_key: str,
        segment_key: str = "",
        now: datetime | None = None,
    ) -> bool:
        """Baja: la fila vigente queda como histórico (``superseded_at``)."""
        row = self.current(db, company_id=company_id, tenant_id=tenant_id, keys=[input_key]).get(
            (input_key, segment_key)
        )
        if row is None:
            return False
        row.superseded_at = now or datetime.now(UTC)
        db.flush()
        return True

    # ------------------------------------------------------------------ huecos
    @staticmethod
    def required_inputs(framework: CompanyFramework, extra_inputs: Iterable[str] = ()) -> tuple[str, ...]:
        """Inputs que pide el modelo declarado, en el orden de su fórmula."""
        definition = FORMULAS.get(framework.key)
        ordered = list(definition.inputs) if definition else []
        ordered += [metric.strip().lower() for metric in framework.required_fact_metrics]
        ordered += list(extra_inputs)
        return tuple(dict.fromkeys(key for key in ordered if key))

    def detect_gaps(
        self,
        db: Session,
        *,
        company: Company,
        tenant_id: int,
        framework: CompanyFramework | None = None,
        extra_inputs: Iterable[str] = (),
    ) -> GapReport:
        tenant = _require_tenant(tenant_id, db)
        resolved = framework or resolve_company_framework(company)
        definition = FORMULAS.get(resolved.key)
        required = self.required_inputs(resolved, extra_inputs)
        if not required:
            return GapReport(resolved.key, definition.key if definition else None, (), (), ())

        facts = db.scalars(
            select(FinancialFact).where(
                FinancialFact.tenant_id == tenant,
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(required),
            )
        ).all()
        fact_ids: dict[str, list[int]] = {}
        for fact in facts:
            if DriverOperatingModel._annual_points([fact]):
                fact_ids.setdefault(fact.metric, []).append(fact.id)

        kpis = db.scalars(
            select(KPIExtractionCandidate).where(
                KPIExtractionCandidate.tenant_id == tenant,
                KPIExtractionCandidate.company_id == company.id,
                KPIExtractionCandidate.metric_key.in_(required),
                KPIExtractionCandidate.status == "approved",
                KPIExtractionCandidate.normalized_value.is_not(None),
            )
        ).all()
        kpi_ids: dict[str, list[int]] = {}
        for candidate in kpis:
            kpi_ids.setdefault(candidate.metric_key, []).append(candidate.id)

        declared: dict[str, list[DeclaredInputValue]] = {}
        for (key, _segment), row in self.current(
            db, company_id=company.id, tenant_id=tenant, keys=required
        ).items():
            if self.row_is_valid(row):
                declared.setdefault(key, []).append(row)

        covered: list[InputCoverage] = []
        gaps: list[InputGap] = []
        formula_label = definition.key if definition else resolved.key
        for key in required:
            if key in fact_ids:
                covered.append(InputCoverage(key, "financial_fact", tuple(sorted(fact_ids[key]))))
            elif key in kpi_ids:
                covered.append(InputCoverage(key, "approved_kpi", tuple(sorted(kpi_ids[key]))))
            elif key in declared:
                rows = declared[key]
                best = max(rows, key=lambda row: STATUS_PRECEDENCE.get(row.status, 0))
                covered.append(
                    InputCoverage(
                        key,
                        "declared_input",
                        tuple(row.id for row in rows),
                        status=best.status,
                        blocks_publication=all(row.status in STATUSES_BLOCKING_PUBLICATION for row in rows),
                    )
                )
            else:
                dimension = _dimension_for(key)
                gaps.append(
                    InputGap(
                        key=key,
                        segment_key="",
                        expected_dimension=dimension.render() if dimension else None,
                        bounds=_bounds_for(key),
                        why=(
                            f"El modelo «{formula_label}» lo necesita y no hay dato oficial, "
                            "KPI aprobado ni input declarado vigente para esta empresa."
                        ),
                    )
                )
        return GapReport(
            resolved.key,
            definition.key if definition else None,
            required,
            tuple(covered),
            tuple(gaps),
        )

    # ------------------------------------------------------------------ internos
    @staticmethod
    def _content(row: DeclaredInputValue) -> tuple[Any, ...]:
        return (
            _decimal(row.low),
            _decimal(row.base),
            _decimal(row.high),
            row.unit,
            row.status,
            row.method,
            row.source_url,
            row.source_quote,
            row.document_id,
            row.analyst_firm,
            row.as_of,
            row.model_family,
            row.input_set_version,
            row.fingerprint,
            row.metadata_ or {},
        )

    @staticmethod
    def _content_of_item(item: DeclaredInput) -> tuple[Any, ...]:
        return (
            _decimal(item.low),
            _decimal(item.base),
            _decimal(item.high),
            item.unit.strip(),
            item.status,
            item.method,
            (item.source_url or "").strip() or None,
            (item.source_quote or "").strip() or None,
            item.document_id,
            (item.analyst_firm or "").strip() or None,
            item.as_of,
            item.model_family,
            item.input_set_version,
            item.fingerprint,
            dict(item.metadata),
        )

    @staticmethod
    def _as_item(row: DeclaredInputValue) -> DeclaredInput:
        return DeclaredInput(
            input_key=row.input_key,
            segment_key=row.segment_key or "",
            low=row.low,
            base=row.base,
            high=row.high,
            unit=row.unit,
            method=row.method,
            source_url=row.source_url,
            source_quote=row.source_quote,
            document_id=row.document_id,
            analyst_firm=row.analyst_firm,
            as_of=row.as_of,
            model_family=row.model_family,
            input_set_version=row.input_set_version,
            fingerprint=row.fingerprint,
            metadata=dict(row.metadata_ or {}),
        )


__all__ = [
    "INPUT_BOUNDS",
    "METHOD_STATUS",
    "STATUS_PRECEDENCE",
    "DeclaredInput",
    "DeclaredInputError",
    "DeclaredInputService",
    "GapReport",
    "InputCoverage",
    "InputGap",
    "UpsertResult",
]
