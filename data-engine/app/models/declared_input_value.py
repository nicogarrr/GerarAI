"""Inputs declarados por empresa para los modelos que no tienen datos propios.

Tabla ``declared_input_values`` (migracion 0127; feature aprobada por Nico el
4-nov-2026). Cuando el modelo declarado de una empresa (pre-ingresos,
escenarios, red/suscripcion, capacidad) pide inputs que no estan en
``FinancialFact`` ni en un KPI aprobado, el pipeline los rellena aqui, con:

- rango ``low``/``base``/``high`` y unidad;
- ``status``: ``oficial`` (cita verificada en un documento), ``estimado``
  (inferencia acotada con URL, o supuesto de un analista), ``derivado``
  (calculado por codigo a partir de otros inputs), ``supuesto_por_defecto``
  (valor de familia; bloquea la publicacion) o ``manual`` (override auditado);
- ``method``: ``extract``/``infer``/``derive``/``default``/``manual``/``analyst``;
  un supuesto de analista es ``status='estimado'`` + ``method='analyst'`` +
  ``analyst_firm`` («de analista X, estimado»);
- fuente (``source_url``, ``source_quote``, ``document_id``) y ``as_of``.

Historico sin sobrescritura: la fila vigente es la de ``superseded_at IS
NULL``, unica por (tenant, empresa, input, segmento). ``segment_key=''`` es la
empresa entera. Columnas identicas a la migracion (rachet de deriva).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin

DECLARED_INPUT_STATUSES: tuple[str, ...] = (
    "oficial",
    "estimado",
    "derivado",
    "supuesto_por_defecto",
    "manual",
)
DECLARED_INPUT_METHODS: tuple[str, ...] = (
    "extract",
    "infer",
    "derive",
    "default",
    "manual",
    "analyst",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class DeclaredInputValue(TenantOwnedMixin, Base, TimestampMixin):
    """Un input del modelo declarado de una empresa, con rango, estado y fuente."""

    __tablename__ = "declared_input_values"
    __table_args__ = (
        CheckConstraint(_in_list("status", DECLARED_INPUT_STATUSES), name="ck_declared_input_status"),
        CheckConstraint(_in_list("method", DECLARED_INPUT_METHODS), name="ck_declared_input_method"),
        Index(
            "uq_declared_input_current",
            "tenant_id",
            "company_id",
            "input_key",
            "segment_key",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
            sqlite_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    input_key: Mapped[str] = mapped_column(String(120))
    segment_key: Mapped[str] = mapped_column(String(80), default="", server_default="")
    low: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    base: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(20))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    analyst_firm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    model_family: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_set_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
