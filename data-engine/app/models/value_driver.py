"""Inventario de impulsores de valor por empresa (etapa «Recopilador»).

Tabla ``value_drivers`` (migración 0129; feature aprobada por Nico el 4-nov-2026:
«al pedir la tesis, Cerebro y su equipo de expertos deben llegar a todas esas
conclusiones», «añade agentes expertos si hace falta, por ejemplo agente
recopilador de todo»). Antes de buscar inputs y valorar, el equipo de expertos
lista TODO lo que mueve el valor de una empresa — líneas de negocio, contratos,
mercados, gobierno, activos, opciones, restricciones, pasivos y catalizadores —
y cada pieza queda aquí con:

- ``category`` y ``status`` (firmado, anunciado oficial, LOI/MoU, pendiente de
  regulador o rumor);
- economía pública si la hay (``economics``: importe, moneda, plazo, economía
  unitaria, importe en USD), ``timing``;
- fuente: URL, cita literal, ``source_type`` y ``as_of``; ``evidence``
  oficial/estimado/rumor;
- ``treatment`` OBLIGATORIO: ``en_modelo`` (+ ``model_link``), ``suelo``,
  ``opcion``, ``riesgo``, ``no_valorado`` (+ motivo) o ``pendiente`` (nadie la
  ha tratado aún: si es firmada y material, bloquea la publicación).

Histórico sin sobrescritura, como ``declared_input_values``: la fila vigente es
la de ``superseded_at IS NULL``, única por (tenant, empresa, ``driver_key``).
Columnas idénticas a la migración (rachet de deriva). Nada por ticker.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
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

VALUE_DRIVER_CATEGORIES: tuple[str, ...] = (
    "linea_negocio",
    "contrato",
    "geografia",
    "gobierno",
    "activo",
    "opcion",
    "restriccion",
    "pasivo",
    "catalizador",
)
VALUE_DRIVER_STATUSES: tuple[str, ...] = (
    "firmado",
    "anunciado_oficial",
    "loi_mou",
    "regulatorio_pendiente",
    "rumor",
)
VALUE_DRIVER_SOURCE_TYPES: tuple[str, ...] = (
    "filing",
    "nota_empresa",
    "nota_socio",
    "regulador",
    "prensa",
    "analista",
    "foro",
    "redes",
)
VALUE_DRIVER_EVIDENCE: tuple[str, ...] = ("oficial", "estimado", "rumor")
VALUE_DRIVER_TREATMENTS: tuple[str, ...] = (
    "en_modelo",
    "suelo",
    "opcion",
    "riesgo",
    "no_valorado",
    "pendiente",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ValueDriver(TenantOwnedMixin, Base, TimestampMixin):
    """Un impulsor de valor de una empresa, con estado, fuente y tratamiento."""

    __tablename__ = "value_drivers"
    __table_args__ = (
        CheckConstraint(_in_list("category", VALUE_DRIVER_CATEGORIES), name="ck_value_driver_category"),
        CheckConstraint(_in_list("status", VALUE_DRIVER_STATUSES), name="ck_value_driver_status"),
        CheckConstraint(
            _in_list("source_type", VALUE_DRIVER_SOURCE_TYPES), name="ck_value_driver_source_type"
        ),
        CheckConstraint(_in_list("evidence", VALUE_DRIVER_EVIDENCE), name="ck_value_driver_evidence"),
        CheckConstraint(_in_list("treatment", VALUE_DRIVER_TREATMENTS), name="ck_value_driver_treatment"),
        Index(
            "uq_value_driver_current",
            "tenant_id",
            "company_id",
            "driver_key",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
            sqlite_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    driver_key: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30))
    economics: Mapped[dict] = mapped_column(JSON, default=dict)
    timing: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[str] = mapped_column(String(20))
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    headline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    treatment: Mapped[str] = mapped_column(String(20), default="pendiente", server_default="pendiente")
    model_link: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason_if_not_valued: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_per_share_marginal: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
