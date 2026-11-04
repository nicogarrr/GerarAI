"""Public provider data only. Never reuse tenant documents or their identifiers."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities import Base, TimestampMixin


class PublicSourceDocument(Base, TimestampMixin):
    __tablename__ = "public_source_documents"
    __table_args__ = (UniqueConstraint("company_id", "listing_key", "provider", "source_url", "checksum", name="uq_public_source_identity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    listing_key: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(40))
    source_url: Mapped[str] = mapped_column(String(2000))
    checksum: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    official: Mapped[bool] = mapped_column(Boolean)


class PublicFinancialFact(Base, TimestampMixin):
    __tablename__ = "public_financial_facts"
    __table_args__ = (UniqueConstraint("source_document_id", "metric", "period_end", "unit", "concept_name", name="uq_public_fact_source_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("public_source_documents.id"), index=True)
    metric: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(30, 8))
    unit: Mapped[str] = mapped_column(String(40))
    period_end: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    fiscal_quarter: Mapped[str] = mapped_column(String(10))
    filed: Mapped[date | None] = mapped_column(Date, nullable=True)
    concept_namespace: Mapped[str | None] = mapped_column(String(100), nullable=True)
    concept_name: Mapped[str] = mapped_column(String(200), default="")
    accession: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    derived: Mapped[bool] = mapped_column(Boolean, default=False)
    derived_from_refs: Mapped[list[str]] = mapped_column(JSON, default=list)


class PublicFinancialStatement(Base, TimestampMixin):
    __tablename__ = "public_financial_statements"
    __table_args__ = (UniqueConstraint("source_document_id", "statement_type", "period_end", "unit", name="uq_public_statement_source_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("public_source_documents.id"), index=True)
    statement_type: Mapped[str] = mapped_column(String(40))
    period_end: Mapped[date] = mapped_column(Date)
    unit: Mapped[str] = mapped_column(String(40))
    # Normalized metric -> numeric string. No provider payload or user metadata.
    metrics: Mapped[dict[str, str]] = mapped_column(JSON)


class PublicAnalystTargets(Base, TimestampMixin):
    __tablename__ = "public_analyst_targets"
    __table_args__ = (UniqueConstraint("source_document_id", "firm", "published_on", name="uq_public_analyst_source_firm_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("public_source_documents.id"), index=True)
    firm: Mapped[str] = mapped_column(String(200))
    published_on: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(30, 8))
    unit: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
