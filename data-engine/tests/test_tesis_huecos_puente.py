"""Huecos del puente de valoracion (deuda neta, acciones) con varias fuentes.

Peticion del propietario (Nico, 3-nov-2026): la mayoria de tesis de la
watchlist salian «datos insuficientes» por falta de deuda neta / acciones
(ESEF sin deuda mapeada, SEC sin tag de deuda reciente). Reglas probadas:
- Yahoo en modo huecos rellena SOLO lo que falta y nunca pisa lo oficial.
- Un 0 de una sola fuente no es un dato; dos fuentes que coinciden confirman;
  si discrepan manda el oficial y la discrepancia queda en la traza.
- Lo resuelto por cruce sale etiquetado en la traza, la tesis y el valor justo.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.yahoo_fundamentals_service import refresh_gaps_from_yahoo
from app.valuation import bridge_sources as bs
from app.valuation.financial_snapshot import FinancialSnapshotBuilder


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="AENA", name="Aena S.M.E., S.A.", exchange="BME", currency="EUR"):
    c = Company(
        ticker=ticker, name=name, exchange=exchange, currency=currency, sector="S",
        industry="I", company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


def _fact(db, company, metric, value, period, source="ESEF", unit="EUR", quarter="FY"):
    doc = db.scalars(
        select(Document).where(Document.company_id == company.id, Document.source_type == source)
    ).first()
    if doc is None:
        doc = Document(company_id=company.id, title=f"doc {source}", source_type=source)
        db.add(doc)
        db.flush()
    year = int(period[:4])
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
        period=period if ":" in period else f"{period}:{quarter}", fiscal_year=year,
        fiscal_quarter=quarter, source_id=doc.id, source_type=source,
        is_reported=source in ("SEC", "ESEF"), confidence=Decimal("0.9"),
    ))
    db.commit()


def _yahoo(name="Aena S.M.E., S.A.", currency="EUR", debt=7281.272e6, net=5183.166e6, cash=2047.669e6,
           shares=1.5e9):
    col = pd.Timestamp("2025-12-31")
    rows = {"Total Debt": debt, "Cash And Cash Equivalents": cash}
    if net is not None:
        rows["Net Debt"] = net
    balance = pd.DataFrame({col: list(rows.values())}, index=list(rows))
    income = pd.DataFrame({col: [shares]}, index=["Diluted Average Shares"])
    return lambda symbol: {
        "name": name, "currency": currency, "income": income, "balance": balance,
        "cashflow": pd.DataFrame(), "symbol_seen": symbol,
    }


def _anchor(db, company, source="ESEF", unit="EUR", period="2025-12-31:FY"):
    _fact(db, company, "revenue", 6.3e9, period, source=source, unit=unit)
    _fact(db, company, "free_cash_flow", 1.1e9, period, source=source, unit=unit)


# -- resolutor puro ---------------------------------------------------------

def _cand(source, value, end="2025-12-31"):
    return bs.Candidate(source, value, f"{end}:FY", date.fromisoformat(end), object())


def test_un_cero_de_una_sola_fuente_no_es_un_dato():
    assert bs.resolve("net_debt", [_cand("YAHOO_FUNDAMENTALS", 0.0)]) is None
    assert bs.resolve("total_debt", [_cand("SEC", 0.0)]) is None


def test_dos_fuentes_que_coinciden_confirman_y_citan_ambas():
    out = bs.resolve("total_debt", [_cand("YAHOO_FUNDAMENTALS", 229.3e6), _cand("FMP", 229.3e6)])
    assert out.status == "confirmed"
    assert "Yahoo" in out.note and "Financial Modeling Prep" in out.note
    zero = bs.resolve("total_debt", [_cand("YAHOO_FUNDAMENTALS", 0.0), _cand("FMP", 0.0)])
    assert zero is not None and zero.status == "confirmed"


def test_si_discrepan_manda_el_oficial_y_queda_la_discrepancia():
    out = bs.resolve(
        "net_debt",
        [_cand("YAHOO_FUNDAMENTALS", 900e6, "2026-06-30"), _cand("SEC", 744e6, "2025-12-31")],
    )
    assert out.chosen.source == "SEC" and out.status == "discrepancy"
    assert "oficial" in out.note and "Yahoo" in out.note


def test_una_sola_fuente_no_oficial_se_usa_marcada():
    out = bs.resolve("net_debt", [_cand("YAHOO_FUNDAMENTALS", 5.18e9)])
    assert out.status == "single_source" and "una sola fuente, no oficial" in out.note


# -- Yahoo en modo huecos -----------------------------------------------------

def test_modo_huecos_rellena_solo_lo_que_falta_y_no_pisa_lo_oficial(db):
    company = _company(db)
    _anchor(db, company)
    _fact(db, company, "cash_and_equivalents", 2.05e9, "2025-12-31:FY")
    _fact(db, company, "shares_diluted", 1.5e9, "2025-12-31:FY", unit="shares")
    before = FinancialSnapshotBuilder().build(db, company)
    assert "net_debt" in before.missing_inputs and not before.bridge_provenance

    out = refresh_gaps_from_yahoo(db, company, fetcher=_yahoo())
    assert out["symbol"] == "AENA.MC" and out["official"] is False
    facts = db.scalars(select(FinancialFact).where(FinancialFact.source_type == "YAHOO_FUNDAMENTALS")).all()
    metrics = {f.metric for f in facts}
    # caja y acciones FY2025 ya son oficiales: Yahoo no las toca
    assert metrics == {"total_debt", "net_debt"}
    doc = db.get(Document, facts[0].source_id)
    assert doc.metadata_["single_source"] is True and "fuente no oficial" in doc.title

    snap = FinancialSnapshotBuilder().build(db, company)
    assert "net_debt" not in snap.missing_inputs
    assert float(snap.facts["net_debt"].value) == pytest.approx(5183.166e6)


def test_modo_huecos_no_acepta_una_ficha_sin_nombre_real(db):
    company = _company(db, ticker="BFIT", name="BFIT", exchange="UNKNOWN", currency="USD")
    with pytest.raises(RuntimeError, match="company_mismatch"):
        refresh_gaps_from_yahoo(db, company, fetcher=_yahoo(name="Basic-Fit N.V.", currency="USD"))
    assert db.scalars(select(FinancialFact)).all() == []


def test_modo_huecos_no_tapa_la_deuda_oficial_con_deuda_neta_de_yahoo(db):
    company = _company(db, ticker="IBE", name="Iberdrola, S.A.")
    _anchor(db, company)
    _fact(db, company, "total_debt", 50e9, "2025-12-31:FY")
    _fact(db, company, "cash_and_equivalents", 4e9, "2025-12-31:FY")
    refresh_gaps_from_yahoo(db, company, fetcher=_yahoo(name="Iberdrola, S.A.", net=40e9))
    yahoo = {f.metric for f in db.scalars(
        select(FinancialFact).where(FinancialFact.source_type == "YAHOO_FUNDAMENTALS")).all()}
    assert "net_debt" not in yahoo and "total_debt" not in yahoo


# -- snapshot: cierre cercano y etiqueta --------------------------------------

def test_snapshot_cruza_fuentes_con_cierre_cercano_y_lo_etiqueta(db):
    """PLTR: ancla SEC trimestral 2026, deuda solo en Yahoo FY2025 (arrendamientos)."""
    company = _company(db, ticker="PLTR", name="Palantir Technologies Inc.", exchange="NASDAQ", currency="USD")
    _anchor(db, company, source="SEC", unit="USD", period="2026-06-30:Q2")
    _fact(db, company, "shares_diluted", 2.6e9, "2026-06-30:Q2", source="SEC", unit="shares", quarter="Q2")
    _fact(db, company, "cash_and_equivalents", 1.4238e9, "2025-12-31:FY", source="SEC", unit="USD")
    _fact(db, company, "total_debt", 229.338e6, "2025-12-31:FY", source="YAHOO_FUNDAMENTALS", unit="USD")
    snap = FinancialSnapshotBuilder().build(db, company)
    assert "net_debt" not in snap.missing_inputs
    prov = snap.bridge_provenance["net_debt"]
    assert prov["status"] == "single_source" and prov["estimated"] is True
    assert prov["method"] == "deuda total − caja"
    assert prov["value"] == pytest.approx(229.338e6 - 1.4238e9)


def test_snapshot_no_da_deuda_cero_por_ausencia(db):
    company = _company(db, ticker="HIMS", name="Hims & Hers Health, Inc.", exchange="NYSE", currency="USD")
    _anchor(db, company, source="SEC", unit="USD", period="2026-06-30:Q2")
    _fact(db, company, "shares_diluted", 2.3e8, "2026-06-30:Q2", source="SEC", unit="shares", quarter="Q2")
    _fact(db, company, "cash_and_equivalents", 2.3e8, "2026-06-30:Q2", source="SEC", unit="USD", quarter="Q2")
    snap = FinancialSnapshotBuilder().build(db, company)
    assert "net_debt" in snap.missing_inputs  # sin ninguna fuente de deuda: N/D, nunca 0
    assert "net_debt" not in snap.bridge_provenance


def test_acciones_en_circulacion_como_aproximacion_etiquetada(db):
    company = _company(db, ticker="SAN", name="Banco Santander, S.A.")
    _anchor(db, company)
    _fact(db, company, "net_debt", 1e9, "2025-12-31:FY")
    _fact(db, company, "shares_outstanding", 14.68e9, "2025-12-31:DEI", source="SEC", unit="shares", quarter="DEI")
    snap = FinancialSnapshotBuilder().build(db, company)
    assert "shares_diluted" not in snap.missing_inputs
    prov = snap.bridge_provenance["shares_diluted"]
    assert prov["method"] == "acciones en circulación (sin dilución)"


def test_la_etiqueta_llega_a_la_tesis_y_al_valor_justo():
    from app.services.fair_value_service import Candidate, _estimated_inputs, _reading
    from app.services.thesis_service import estimated_inputs_markdown

    valuation = {"estimated_inputs": [{
        "metric": "net_debt", "value": 5.18e9, "status": "single_source",
        "method": "deuda neta declarada", "period": "2025-12-31:FY",
        "note": "una sola fuente, no oficial (Yahoo Finance (no oficial))",
    }]}
    line = estimated_inputs_markdown(valuation)
    assert "Inputs estimados" in line and "Deuda neta" in line and "una sola fuente, no oficial" in line
    assert estimated_inputs_markdown({}) == ""
    cand = Candidate(value=30.0, as_of=None, publishable=True, estimated_inputs=_estimated_inputs(valuation))
    reading = _reading("motor", cand, stale=False, rule="motor_publicable")
    assert reading["label"].endswith("con inputs estimados")
    assert reading["estimated_inputs"] == ["net_debt"]
    plain = _reading("motor", Candidate(value=30.0, as_of=None), stale=False, rule="motor_publicable")
    assert "estimated_inputs" not in plain and plain["label"] == "Motor de valoración"
