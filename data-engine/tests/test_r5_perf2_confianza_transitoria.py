"""PINS daba 500 en /api/valuation: un hecho transitorio sin confianza.

El puente de fuentes (``_resolve_bridge_gaps``) construye la deuda neta
«deuda total − caja» como ``FinancialFact`` en memoria; el ``default`` de la
columna ``confidence`` solo se aplica en el INSERT, así que llegaba ``None`` y
``StandardDCFEngine`` hacía ``float(None)`` al promediar la confianza de la
evidencia → TypeError → 500. Reglas probadas (generales, para cualquier
empresa):

- el transitorio lleva la confianza de su pieza más débil (deuda o caja), con
  el mismo 0,8 de respaldo que ``_derive_net_debt``;
- cualquier motor que promedie confianzas tolera un hecho sin ella: cuenta 0
  (no se inventa) y el DCF lo deja dicho en ``evidence_confidence_missing``.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.valuation.financial_snapshot import FinancialSnapshotBuilder


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db):
    c = Company(
        ticker="ZZPN", name="Pin Board Inc.", exchange="NYSE", currency="USD", sector="S",
        industry="I", company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


def _fact(db, company, metric, value, period, *, source="SEC", unit="USD", confidence="0.9"):
    doc = db.scalars(
        select(Document).where(Document.company_id == company.id, Document.source_type == source)
    ).first()
    if doc is None:
        doc = Document(company_id=company.id, title=f"doc {source}", source_type=source)
        db.add(doc)
        db.flush()
    quarter = period.split(":")[1]
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit, period=period,
        fiscal_year=int(period[:4]), fiscal_quarter=quarter, source_id=doc.id, source_type=source,
        is_reported=source == "SEC", confidence=Decimal(confidence),
    ))
    db.commit()


def _pins_like(db, *, debt_confidence="0.6", cash_confidence="0.95"):
    """Ancla SEC trimestral; deuda solo en Yahoo y caja SEC del cierre anual."""
    company = _company(db)
    _fact(db, company, "revenue", 4.2e9, "2026-06-30:Q2")
    _fact(db, company, "free_cash_flow", 9e8, "2026-06-30:Q2")
    _fact(db, company, "shares_diluted", 7e8, "2026-06-30:Q2", unit="shares")
    _fact(db, company, "cash_and_equivalents", 1.2e9, "2025-12-31:FY", confidence=cash_confidence)
    _fact(db, company, "total_debt", 2.5e8, "2025-12-31:FY", source="YAHOO_FUNDAMENTALS",
          confidence=debt_confidence)
    return company


def test_deuda_neta_por_cruce_lleva_la_confianza_de_su_pieza_mas_debil(db):
    snap = FinancialSnapshotBuilder().build(db, _pins_like(db))
    net = snap.facts["net_debt"]
    assert net.id is None and snap.bridge_provenance["net_debt"]["method"] == "deuda total − caja"
    assert net.confidence is not None
    assert float(net.confidence) == pytest.approx(0.6)  # min(deuda 0,6 · caja 0,95)


def test_el_dcf_estandar_no_revienta_con_la_deuda_neta_por_cruce(db):
    from app.valuation.engines.standard_dcf import StandardDCFEngine

    company = _pins_like(db)
    engine = StandardDCFEngine()
    out = engine.value(engine.build_context(db, company, 20.0, None))  # en main: TypeError → 500
    trace = out.get("trace") or {}
    assert "net_debt" in trace.get("evidence_confidence_inputs", [])
    assert "evidence_confidence_missing" not in trace
    assert 0.0 < trace["evidence_confidence"] <= 1.0


def test_el_dcf_estandar_dice_que_entrada_no_traia_confianza(db, monkeypatch):
    """Red de seguridad: si otro transitorio llega sin confianza, cuenta 0 y se dice."""
    from app.valuation import financial_snapshot as fs
    from app.valuation.engines.standard_dcf import StandardDCFEngine

    company = _pins_like(db)
    real_build = fs.FinancialSnapshotBuilder.build

    def build_sin_confianza(self, *args, **kwargs):
        snap = real_build(self, *args, **kwargs)
        snap.facts["net_debt"].confidence = None
        return snap

    monkeypatch.setattr(fs.FinancialSnapshotBuilder, "build", build_sin_confianza)
    engine = StandardDCFEngine()
    out = engine.value(engine.build_context(db, company, 20.0, None))
    assert out["trace"]["evidence_confidence_missing"] == ["net_debt"]


def test_un_hecho_sin_confianza_cuenta_cero_y_queda_dicho():
    from app.valuation.fact_reference import (
        fact_confidence,
        mean_fact_confidence,
        missing_confidence_metrics,
    )

    con = SimpleNamespace(metric="revenue", confidence=Decimal("0.9"))
    sin = SimpleNamespace(metric="net_debt", confidence=None)
    raro = SimpleNamespace(metric="shares_diluted", confidence=float("nan"))
    assert fact_confidence(con) == pytest.approx(0.9)
    assert fact_confidence(sin) == 0.0 and fact_confidence(raro) == 0.0
    assert mean_fact_confidence([con, sin]) == pytest.approx(0.45)
    assert mean_fact_confidence([]) == 0.0
    assert missing_confidence_metrics([con, sin, raro]) == ["net_debt", "shares_diluted"]
    assert missing_confidence_metrics([con]) == []


def test_motores_sectoriales_toleran_un_hecho_sin_confianza():
    from app.valuation.engines.sector_specific import _sourced

    fact = FinancialFact(
        company_id=1, metric="book_value", value=Decimal("10"), period="2025-12-31:FY",
        source_type="DERIVED", is_reported=False,
    )
    assert fact.confidence is None
    assert _sourced(fact).confidence == 0.0
