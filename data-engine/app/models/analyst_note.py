"""Notas de analista estructuradas (entrada del experto en analistas).

Tabla ``analyst_notes`` (migracion 0130; feature aprobada por Nico el
4-nov-2026). Cada fila es una nota publicada por una firma sobre un valor:
firma, analista, fecha, accion (initiate/reiterate/upgrade/downgrade/maintain),
rating y precio objetivo antes -> despues, precio de la accion ese dia,
argumentos clave, sentimiento, cita literal y su fuente (URL + tipo).

La tarjeta de nota de Nico es el MINIMO: cuando una fuente gratuita lo dice,
tambien se guardan estimaciones por ano (``estimates``), metodo y parametros
de valoracion (``valuation``), supuestos por segmento/KPI
(``segment_assumptions``), casos alcista/bajista (``bull_*``/``bear_*``),
catalizadores, riesgos, cambios desde la nota anterior y enlaces. Lo que no
encaja va en ``extras`` (JSON) para no perder nada.

``verification``: ``verificado`` (cita encontrada en la fuente),
``fragmento`` (solo el esqueleto de un agregador, sin cita) o
``rumor_no_verificado`` (redes sociales; obligatorio para ``source_type
='social'``). ``driver_refs`` (nullable) es la costura para enlazar cada
argumento con los impulsores de valor (lane posterior).

Idempotencia: ``dedupe_key`` = sha256(tenant | ticker | firma normalizada |
fecha | accion), unico. Columnas identicas a la migracion (rachet de deriva).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin

ANALYST_NOTE_ACTIONS: tuple[str, ...] = (
    "initiate",
    "reiterate",
    "upgrade",
    "downgrade",
    "maintain",
    "other",
)
ANALYST_NOTE_SOURCE_TYPES: tuple[str, ...] = (
    "yahoo_upgrades_downgrades",
    "news",
    "press",
    "social",
    "other",
)
ANALYST_NOTE_SENTIMENTS: tuple[str, ...] = ("positive", "neutral", "negative")
ANALYST_NOTE_VERIFICATIONS: tuple[str, ...] = ("verificado", "fragmento", "rumor_no_verificado")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class AnalystNote(TenantOwnedMixin, Base, TimestampMixin):
    """Una nota de analista con sus datos, su cita y su fuente."""

    __tablename__ = "analyst_notes"
    __table_args__ = (
        CheckConstraint(_in_list("action", ANALYST_NOTE_ACTIONS), name="ck_analyst_note_action"),
        CheckConstraint(
            _in_list("source_type", ANALYST_NOTE_SOURCE_TYPES), name="ck_analyst_note_source_type"
        ),
        CheckConstraint(
            "sentiment IS NULL OR " + _in_list("sentiment", ANALYST_NOTE_SENTIMENTS),
            name="ck_analyst_note_sentiment",
        ),
        CheckConstraint(
            _in_list("verification", ANALYST_NOTE_VERIFICATIONS), name="ck_analyst_note_verification"
        ),
        UniqueConstraint("dedupe_key", name="uq_analyst_notes_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    firm: Mapped[str] = mapped_column(String(200))
    firm_key: Mapped[str] = mapped_column(String(200))
    analyst: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note_date: Mapped[date] = mapped_column(Date)
    action: Mapped[str] = mapped_column(String(20))
    rating_old: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rating_new: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pt_old: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    pt_new: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price_at_note: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    key_arguments: Mapped[list[str]] = mapped_column(JSON, default=list)
    sentiment: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30))
    verification: Mapped[str] = mapped_column(String(30))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    estimates: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    valuation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    segment_assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    bull_target: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    bear_target: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    bull_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    bear_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalysts: Mapped[list[str]] = mapped_column(JSON, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    changes_since_previous: Mapped[str | None] = mapped_column(Text, nullable=True)
    links: Mapped[list[str]] = mapped_column(JSON, default=list)
    extras: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    driver_refs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(64))
