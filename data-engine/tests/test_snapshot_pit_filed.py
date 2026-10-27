"""Hermetic tests: el corte as_of filtra hechos por fecha de PUBLICACION (V1).

Antes del fix, ``ValuationEngine.build_context`` pasaba ``as_of`` al contexto
pero ``FinancialSnapshotBuilder.build`` seleccionaba los hechos mas recientes
sin mirar ``filed``: un replay con corte 2025-06-30 consumia facts FY2024
publicados en 2026-03-01 (informacion del futuro) y el guard de periodos
pasaba porque el CIERRE del periodo era anterior al corte.

El fix filtra por ``filed <= as_of``. Hechos con ``filed`` NULL no pueden
demostrar cuando fueron conocibles: con corte explicito se excluyen y se
cuentan (``filed_excluded_unknown``), nunca se adivina disponibilidad.
Sin ``as_of`` el comportamiento no cambia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.financial_snapshot import FinancialSnapshotBuilder

AS_OF = date(2025, 6, 30)


def _db_with_facts(filed: date | None) -> tuple[Session, Company]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="SYNTH",
        name="Synthetic",
        currency="USD",
        exchange="NYSE",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    for metric, value, unit in [
        ("revenue", "1000", "USD"),
        ("shares_diluted", "100", "shares"),
        ("free_cash_flow", "100", "USD"),
        ("net_debt", "0", "USD"),
    ]:
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(value),
                unit=unit,
                period="2024-12-31:FY",
                fiscal_year=2024,
                fiscal_quarter="FY",
                filed=filed,
                source_type="synthetic",
                is_reported=True,
                confidence=Decimal("1"),
            )
        )
    db.commit()
    return db, company


def test_facts_filed_after_cutoff_are_excluded_from_replay():
    """Repro V1: facts FY2024 publicados 2026-03-01, corte 2025-06-30.

    Antes: snapshot coherente y valoracion con datos del futuro. Ahora: los
    hechos no entran y el snapshot declara la entrada ausente.
    """
    db, company = _db_with_facts(filed=date(2026, 3, 1))
    try:
        snapshot = FinancialSnapshotBuilder().build(db, company, as_of=AS_OF)
    finally:
        db.close()
    assert not snapshot.coherent
    assert "revenue" in snapshot.missing_inputs
    assert snapshot.filed_cutoff == AS_OF.isoformat()
    # Sin ancla solo se consultan revenue + los testigos de ausencia
    # (shares/FCF/margen): 3 hechos excluidos por futuros, net_debt no llega
    # a consultarse. El conteo es de hechos excluidos ENTRE los consultados.
    assert snapshot.filed_excluded_future == 3
    assert snapshot.filed_excluded_unknown == 0
    assert any("Corte point-in-time" in w for w in snapshot.warnings)


def test_facts_filed_before_cutoff_feed_the_valuation():
    db, company = _db_with_facts(filed=date(2025, 3, 1))
    try:
        engine = StandardDCFEngine()
        context = engine.build_context(db, company, 10, as_of=AS_OF)
        result = engine.value(context)
    finally:
        db.close()
    assert context.snapshot.coherent
    assert context.snapshot.filed_excluded_future == 0
    assert result["expected_value"] is not None


def test_facts_without_filed_are_unknown_availability_not_assumed():
    db, company = _db_with_facts(filed=None)
    try:
        snapshot = FinancialSnapshotBuilder().build(db, company, as_of=AS_OF)
    finally:
        db.close()
    assert not snapshot.coherent
    assert "revenue" in snapshot.missing_inputs
    assert snapshot.filed_excluded_unknown == 3
    assert snapshot.filed_excluded_future == 0
    assert any("sin fecha de publicacion demostrable" in w for w in snapshot.warnings)


def test_without_cutoff_behavior_is_unchanged():
    """Valoracion actual (sin as_of): filed no filtra nada."""
    db, company = _db_with_facts(filed=date(2026, 3, 1))
    try:
        snapshot = FinancialSnapshotBuilder().build(db, company)
    finally:
        db.close()
    assert snapshot.coherent
    assert snapshot.filed_cutoff is None
    assert snapshot.filed_excluded_future == 0
    assert snapshot.filed_excluded_unknown == 0


def test_mixed_availability_uses_only_what_was_public():
    """Un hecho publicado a tiempo convive con otro del futuro."""
    db, company = _db_with_facts(filed=date(2025, 3, 1))
    try:
        db.add(
            FinancialFact(
                company_id=company.id,
                metric="revenue",
                value=Decimal("2000"),
                unit="USD",
                period="2025-12-31:FY",
                fiscal_year=2025,
                fiscal_quarter="FY",
                filed=date(2026, 2, 1),  # posterior al corte
                source_type="synthetic",
                is_reported=True,
                confidence=Decimal("1"),
            )
        )
        db.commit()
        snapshot = FinancialSnapshotBuilder().build(db, company, as_of=AS_OF)
    finally:
        db.close()
    # El ancla es el FY2024 publicado antes del corte, no el FY2025 futuro.
    assert snapshot.coherent
    assert snapshot.as_of_period == "2024-12-31:FY"
    assert float(snapshot.facts["revenue"].value) == 1000.0
    assert snapshot.filed_excluded_future == 1
