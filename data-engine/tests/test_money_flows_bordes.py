"""Bordes de ``app.services.money_flows``: huecos de la union existente.

Lo que cada test demuestra:
- ``aggregate_recipients`` salta filas sin nombre (270) y sin clave
  normalizada (273) y suma por nombre normalizado.
- ``_latest_quarterly_fact`` (354-373) devuelve el trimestre mas reciente por
  ``period``, ignora el marcador anual FY y devuelve None si no hay filas.
- ``period_label`` devuelve el periodo crudo si no parsea (382-383).
- ``_spender_payload`` sin capex pone la nota declarada (427-428); un lease de
  OTRO periodo no se anade (rama 437->443) y uno del MISMO periodo si.
- ``build_sec_spender`` (447-453): compania desconocida -> nota "Sin datos
  SEC"; con capex y lease del mismo periodo -> importe absoluto y extras.
- ``build_usaspending_theme`` camino feliz (512) con fetches doblados y ventana
  fiscal fija: importes exactos en spenders/destinations/suppliers y notas de
  cobertura; y ``build_theme_payload`` delega en energy_flows cuando el tema
  es ``eia_retail_revenue`` (577-579).

La cache del modulo se dobla con monkeypatch (restaura la original). SQLite
real en memoria; fetches HTTP doblados; sin red.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, Document, FinancialFact, Tenant
from app.services import money_flows
from app.services.money_flows import KIND_REPORTADO, SpenderConfig

CFG = SpenderConfig(key="googl", label="Alphabet", kind="sec_capex", ticker="GOOGL", reason="r")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _fact(db, company, doc, metric, value, period, quarter, tenant_id=1):
    fact = FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(value),
        unit="USD",
        period=period,
        fiscal_year=2026,
        fiscal_quarter=quarter,
        source_id=doc.id,
        source_type="SEC",
        is_reported=True,
        tenant_id=tenant_id,
        accession_number="0001652044-26-000048",
    )
    db.add(fact)
    db.commit()
    return fact


def _company_doc(db):
    company = Company(
        ticker="GOOGL",
        name="Alphabet",
        exchange="NASDAQ",
        company_type="operating",
        valuation_model="dcf",
    )
    doc = Document(
        title="10-Q Q1 2026",
        source_type="filing",
        source_url="https://www.sec.gov/Archives/edgar/data/1652044/000165204426000048",
        published_at=datetime(2026, 4, 30, tzinfo=UTC),
        tenant_id=1,
    )
    db.add_all([company, doc])
    db.commit()
    return company, doc


def test_aggregate_recipients_salta_filas_sin_nombre_y_sin_clave():
    filas = [
        {"name": ""},
        {"name": "   "},
        {"name": "INC"},  # solo sufijo societario: clave normalizada vacia
        {"name": None},
        {"name": "LOCKHEED MARTIN CORPORATION", "amount": 1.5},
        {"name": "Lockheed Martin Corp", "amount": 2.25},
    ]
    assert money_flows.aggregate_recipients(filas) == [
        {"name": "LOCKHEED MARTIN CORPORATION", "amount": 3.75}
    ]


def test_latest_quarterly_fact_devuelve_el_mas_reciente(db):
    company, doc = _company_doc(db)
    _fact(db, company, doc, "capital_expenditure", "1000", "2025-12-31:Q4", "Q4")
    esperado = _fact(db, company, doc, "capital_expenditure", "2000", "2026-03-31:Q1", "Q1")
    _fact(db, company, doc, "capital_expenditure", "9000", "2025-12-31:FY", None)
    _fact(db, company, doc, "finance_lease_additions", "300", "2026-03-31:Q1", "Q1")
    encontrado = money_flows._latest_quarterly_fact(db, company.id, "capital_expenditure", 1)
    assert encontrado is not None and encontrado.id == esperado.id
    assert money_flows._latest_quarterly_fact(db, company.id, "revenue", 1) is None


def test_period_label_devuelve_el_periodo_crudo_si_no_parsea():
    assert money_flows.period_label(SimpleNamespace(period="malformato")) == "malformato"
    assert money_flows.period_label(SimpleNamespace(period="2025-12-31:FY")) == "FY 2025"


def test_spender_payload_sin_capex_pone_nota_declarada():
    base = money_flows._spender_payload(CFG, SimpleNamespace(id=1), None, None)
    assert base == {
        "key": "googl",
        "label": "Alphabet",
        "ticker": "GOOGL",
        "amount": None,
        "unit": "USD",
        "period_label": None,
        "source": None,
        "reason": "r",
        "note": "Sin capex trimestral reportado en los datos de la app",
        "extra_amount": None,
        "extra_label": None,
        "extra_source": None,
    }


def _capex_lease(periodo_lease):
    capex = SimpleNamespace(
        period="2026-03-31:Q1",
        value=Decimal("-2000"),
        unit="USD",
        source_type="SEC",
        accession_number=None,
        source=None,
    )
    lease = SimpleNamespace(
        period=periodo_lease,
        value=Decimal("300"),
        unit="USD",
        source_type="SEC",
        accession_number=None,
        source=None,
    )
    return capex, lease


def test_spender_payload_lease_de_otro_periodo_no_se_anade():
    capex, lease = _capex_lease("2025-12-31:Q4")
    base = money_flows._spender_payload(CFG, SimpleNamespace(id=1), capex, lease)
    assert base["amount"] == 2000.0
    assert base["period_label"] == "Q1 2026"
    assert base["extra_amount"] is None
    assert base["extra_label"] is None
    assert base["extra_source"] is None


def test_spender_payload_lease_del_mismo_periodo_se_anade():
    capex, lease = _capex_lease("2026-03-31:Q1")
    base = money_flows._spender_payload(CFG, SimpleNamespace(id=1), capex, lease)
    assert base["extra_amount"] == 300.0
    assert base["extra_label"] == "Leases financieros nuevos (mismo periodo)"
    assert base["extra_source"] == {
        "kind": KIND_REPORTADO,
        "label": "SEC · Q1 2026",
        "url": None,
        "note": "Filing referenciado por accession; sin enlace directo guardado",
    }


def test_build_sec_spender_compania_desconocida(db):
    base = money_flows.build_sec_spender(db, CFG, 1)
    assert base["note"] == "Sin datos SEC en la app todavía"
    assert base["amount"] is None


def test_build_sec_spender_con_capex_y_lease(db):
    company, doc = _company_doc(db)
    _fact(db, company, doc, "capital_expenditure", "-2000", "2026-03-31:Q1", "Q1")
    _fact(db, company, doc, "finance_lease_additions", "300", "2026-03-31:Q1", "Q1")
    base = money_flows.build_sec_spender(db, CFG, 1)
    assert base["amount"] == 2000.0
    assert base["extra_amount"] == 300.0
    assert base["source"]["label"] == "SEC · Q1 2026 · accession 0001652044-26-000048"


def test_usaspending_theme_camino_feliz(monkeypatch):
    monkeypatch.setattr(money_flows, "_cache", {})
    monkeypatch.setattr(money_flows, "_fy_window", lambda: ("2024-10-01", "2025-09-30", "FY 2025"))
    monkeypatch.setattr(money_flows, "fetch_agency_obligations", lambda agency, start, end: 100.0)
    monkeypatch.setattr(
        money_flows,
        "fetch_top_categories",
        lambda agency, start, end: [{"code": "F999", "name": "Other", "amount": 40.0}],
    )
    monkeypatch.setattr(
        money_flows,
        "fetch_top_recipients",
        lambda agency, start, end: [{"name": "ACME CORPORATION", "amount": 25.0}],
    )
    theme = next(t for t in money_flows.FLOW_THEMES.values() if t.agency_name == "Department of Defense")
    spenders, destinations, suppliers, fy_label, notes, d_note, s_note = money_flows.build_usaspending_theme(
        theme
    )
    assert fy_label == "FY 2025"
    assert notes == []
    assert [s["amount"] for s in spenders] == [100.0] + [None] * (len(spenders) - 1)
    assert destinations == [
        {
            "label": "Other",
            "amount": 40.0,
            "unit": "USD",
            "source": {
                "kind": KIND_REPORTADO,
                "label": "USAspending.gov · categoría PSC F999 · FY 2025",
                "url": money_flows._USASPENDING_AGENCY_URL,
                "note": "Etiqueta oficial de la fuente, en inglés",
            },
        }
    ]
    assert suppliers == [
        {
            "ticker": None,
            "name": "ACME CORPORATION",
            "amount": 25.0,
            "unit": "USD",
            "reason": "Sin mapeo a ticker declarado",
            "note": "Obligaciones FY 2025",
            "source": {
                "kind": KIND_REPORTADO,
                "label": "USAspending.gov · FY 2025",
                "url": money_flows._USASPENDING_AGENCY_URL,
                "note": None,
            },
        }
    ]
    assert d_note == "Principales categorías: cubren el 40 % de lo obligado"
    assert s_note == "Principales recipientes: cubren el 25 % de lo obligado"


def test_usaspending_cache_negativa_no_reintenta(monkeypatch):
    monkeypatch.setattr(money_flows, "_cache", {"fail:Department of Defense": (100.0, None)})
    monkeypatch.setattr(money_flows.time, "monotonic", lambda: 150.0)
    monkeypatch.setattr(money_flows, "_fy_window", lambda: ("2024-10-01", "2025-09-30", "FY 2025"))

    def boom(*args):
        raise AssertionError("no debio llamarse: cache negativa vigente")

    monkeypatch.setattr(money_flows, "fetch_agency_obligations", boom)
    monkeypatch.setattr(money_flows, "fetch_top_categories", boom)
    monkeypatch.setattr(money_flows, "fetch_top_recipients", boom)
    theme = next(t for t in money_flows.FLOW_THEMES.values() if t.agency_name == "Department of Defense")
    spenders, destinations, suppliers, fy_label, notes, d_note, s_note = money_flows.build_usaspending_theme(
        theme
    )
    assert notes == [
        "USAspending no disponible ahora mismo (RuntimeError); sin cifras en lugar de inventarlas"
    ]
    assert spenders[0]["note"] == "USAspending no disponible ahora mismo"
    assert spenders[0]["amount"] is None
    assert destinations == []
    assert suppliers == []
    assert d_note is None
    assert s_note is None


def test_build_sec_spender_compania_sin_capex(db):
    _company_doc(db)  # la compania existe, pero no tiene facts de capex
    base = money_flows.build_sec_spender(db, CFG, 1)
    assert base["note"] == "Sin capex trimestral reportado en los datos de la app"
    assert base["amount"] is None


def test_build_theme_payload_delega_en_energy_flows(monkeypatch):
    from app.services import energy_flows

    tema = next(t for t in money_flows.FLOW_THEMES.values() if t.destinations_live == "eia_retail_revenue")
    centinela = {"ok": True}
    monkeypatch.setattr(energy_flows, "build_energy_flow", lambda theme: centinela)
    assert money_flows.build_theme_payload(None, tema, None) is centinela
