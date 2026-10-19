"""Flujos de dinero por tema: config declarada, agregación y veracidad."""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, Document, FinancialFact, Tenant
from app.services import money_flows
from app.services.money_flows import (
    FLOW_THEMES,
    KIND_ESTIMACION_TERCEROS,
    KIND_REPORTADO,
    _fy_window,
    aggregate_recipients,
    build_theme_payload,
    map_recipient_to_ticker,
    period_label,
)


@pytest.fixture(autouse=True)
def _clear_flow_cache():
    money_flows._cache.clear()
    yield
    money_flows._cache.clear()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _seed_capex(db, ticker="GOOGL", tenant_id=None):
    company = Company(ticker=ticker, name="Alphabet", exchange="NASDAQ", company_type="operating", valuation_model="dcf")
    doc = Document(
        title="10-Q Q1 2026",
        source_type="filing",
        source_url="https://www.sec.gov/Archives/edgar/data/1652044/000165204426000048",
        published_at=datetime(2026, 4, 30, tzinfo=UTC),
        tenant_id=tenant_id,
    )
    db.add_all([company, doc])
    db.flush()
    older = FinancialFact(
        company_id=company.id, metric="capital_expenditure", value=Decimal("17200000000"),
        unit="USD", period="2025-03-31:Q1", fiscal_year=2025, fiscal_quarter="Q1",
        source_id=doc.id, source_type="SEC", is_reported=True, tenant_id=tenant_id,
        accession_number="0001652044-25-000043",
    )
    latest = FinancialFact(
        company_id=company.id, metric="capital_expenditure", value=Decimal("35700000000"),
        unit="USD", period="2026-03-31:Q1", fiscal_year=2026, fiscal_quarter="Q1",
        source_id=doc.id, source_type="SEC", is_reported=True, tenant_id=tenant_id,
        accession_number="0001652044-26-000048",
    )
    annual = FinancialFact(
        company_id=company.id, metric="capital_expenditure", value=Decimal("90000000000"),
        unit="USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter=None,
        source_id=doc.id, source_type="SEC", is_reported=True, tenant_id=tenant_id,
    )
    lease = FinancialFact(
        company_id=company.id, metric="finance_lease_additions", value=Decimal("1200000000"),
        unit="USD", period="2026-03-31:Q1", fiscal_year=2026, fiscal_quarter="Q1",
        source_id=doc.id, source_type="SEC", is_reported=True, tenant_id=tenant_id,
    )
    db.add_all([older, latest, annual, lease])
    db.commit()
    return company


def test_config_declarada_con_razon_por_empresa():
    for theme in FLOW_THEMES.values():
        assert theme.method and theme.limitation
        for spender in theme.spenders:
            assert spender.reason, f"{theme.id}: gastador sin razón declarada"
        for supplier in theme.suppliers:
            assert supplier.reason, f"{theme.id}: proveedor sin razón declarada"


def test_estimaciones_siempre_atribuidas():
    theme = FLOW_THEMES["centros-de-datos"]
    assert theme.destinations, "el reparto MS tiene que estar declarado"
    for item in theme.destinations:
        assert "Morgan Stanley" in item.source_label
    # La limitación declara la inconsistencia interna del gráfico (+151 B$).
    assert "151" in theme.limitation


def test_capex_ultimo_trimestre_reportado(db):
    _seed_capex(db, tenant_id=1)
    payload = build_theme_payload(db, FLOW_THEMES["centros-de-datos"], tenant=1)
    googl = next(s for s in payload["spenders"] if s["ticker"] == "GOOGL")
    assert googl["amount"] == 35_700_000_000  # gana el trimestre más reciente, no el anual ni el viejo
    assert googl["period_label"] == "Q1 2026"
    assert googl["source"]["kind"] == KIND_REPORTADO
    assert googl["source"]["url"].startswith("https://www.sec.gov/")
    assert "0001652044-26-000048" in googl["source"]["label"]
    # Leases del mismo periodo como dato complementario reportado.
    assert googl["extra_amount"] == 1_200_000_000
    assert googl["extra_source"]["kind"] == KIND_REPORTADO
    # Empresas sin datos: N/D honesto, no cero inventado.
    msft = next(s for s in payload["spenders"] if s["ticker"] == "MSFT")
    assert msft["amount"] is None and "Sin datos" in msft["note"]
    # Total = suma de lo disponible, con la advertencia de periodos no coincidentes.
    assert payload["spenders_total"]["amount"] == 35_700_000_000
    assert "1 de 7 gastadores incluidos" in payload["spenders_total"]["note"]
    assert "no coinciden" in payload["spenders_total"]["note"]


def test_capex_compartido_entre_tenants(db):
    # Fact público SEC compartido (tenant NULL, ADR-001): visible desde tenant 1.
    _seed_capex(db, ticker="MSFT", tenant_id=None)
    payload = build_theme_payload(db, FLOW_THEMES["centros-de-datos"], tenant=1)
    msft = next(s for s in payload["spenders"] if s["ticker"] == "MSFT")
    assert msft["amount"] == 35_700_000_000


def test_proveedores_ia_sin_importe_inventado(db):
    payload = build_theme_payload(db, FLOW_THEMES["centros-de-datos"], tenant=1)
    nvda = next(s for s in payload["suppliers"] if s["ticker"] == "NVDA")
    assert nvda["amount"] is None
    assert "Sin reparto público verificable" in nvda["note"]
    ms = payload["destinations"][0]
    assert ms["source"]["kind"] == KIND_ESTIMACION_TERCEROS
    assert "Morgan Stanley" in ms["source"]["label"]


def test_agregacion_recipientes_deduplica_entidades():
    results = [
        {"name": "LOCKHEED MARTIN CORPORATION", "amount": 34.09e9},
        {"name": "LOCKHEED MARTIN CORPORATION", "amount": 10.43e9},
        {"name": "LOCKHEED MARTIN CORPORATION", "amount": 6.05e9},
        {"name": "RAYTHEON COMPANY", "amount": 10.75e9},
    ]
    aggregated = aggregate_recipients(results)
    assert len(aggregated) == 2
    assert aggregated[0]["name"] == "LOCKHEED MARTIN CORPORATION"
    assert aggregated[0]["amount"] == pytest.approx(50.57e9)


def test_mapeo_recipiente_a_ticker():
    assert map_recipient_to_ticker("SIKORSKY AIRCRAFT CORPORATION")[0] == "LMT"
    assert map_recipient_to_ticker("ELECTRIC BOAT CORPORATION")[0] == "GD"
    assert map_recipient_to_ticker("RAYTHEON COMPANY")[0] == "RTX"
    assert map_recipient_to_ticker("TRIWEST HEALTHCARE ALLIANCE CORP")[0] is None
    assert map_recipient_to_ticker("EMPRESA DESCONOCIDA SA") == (None, None)


def test_fy_window_respeta_el_retraso_de_90_dias():
    # 20 días después del cierre del FY2026: todavía bajo el retraso DoD → FY2025.
    _, _, label = _fy_window(date(2026, 10, 20))
    assert label.startswith("FY2025")
    # Un año después: FY2026 ya publicado con margen.
    _, _, label = _fy_window(date(2027, 2, 1))
    assert label.startswith("FY2026")


def test_defensa_degrada_sin_inventar_si_usaspending_falla(db, monkeypatch):
    def _boom(path, payload):
        raise RuntimeError("caído")
    monkeypatch.setattr(money_flows, "_usaspending_post", _boom)
    monkeypatch.setattr(money_flows, "_fy_window", lambda today=None: ("2024-10-01", "2025-09-30", "FY2025 federal (oct 2024–sep 2025)"))
    payload = build_theme_payload(db, FLOW_THEMES["defensa"], tenant=1)
    assert payload["spenders"][0]["amount"] is None
    assert payload["destinations"] == []
    assert payload["suppliers"] == []
    assert any("sin cifras" in note for note in payload["notes"])


def test_defensa_payload_con_datos(db, monkeypatch):
    monkeypatch.setattr(money_flows, "fetch_agency_obligations", lambda *a: 501.7e9)
    monkeypatch.setattr(money_flows, "fetch_top_categories", lambda *a, **k: [
        {"code": "1510", "name": "AIRCRAFT, FIXED WING", "amount": 42.0e9},
        {"code": "9999", "name": "OTHER STUFF", "amount": 1.0e9},
    ])
    monkeypatch.setattr(money_flows, "fetch_top_recipients", lambda *a, **k: [
        {"name": "LOCKHEED MARTIN CORPORATION", "amount": 34.09e9},
        {"name": "EMPRESA PRIVADA SIN MAPEAR", "amount": 2.0e9},
    ])
    monkeypatch.setattr(money_flows, "_fy_window", lambda today=None: ("2024-10-01", "2025-09-30", "FY2025 federal (oct 2024–sep 2025)"))
    payload = build_theme_payload(db, FLOW_THEMES["defensa"], tenant=1)
    assert payload["spenders"][0]["amount"] == 501.7e9
    assert payload["spenders"][0]["source"]["kind"] == KIND_REPORTADO
    assert payload["destinations"][0]["label"] == "Aviones de ala fija"
    assert payload["destinations"][1]["label"] == "OTHER STUFF"  # etiqueta oficial, sin traducir
    assert payload["suppliers"][0]["ticker"] == "LMT"
    assert payload["suppliers"][1]["ticker"] is None
    assert payload["suppliers"][1]["reason"] == "Sin mapeo a ticker declarado"
    # (5) cobertura declarada de los "principales"
    assert payload["destinations_note"].startswith("Principales categorías")
    assert payload["suppliers_note"].startswith("Principales recipientes")


def test_period_label_legible():
    class F:
        period = "2026-03-31:Q1"
    assert period_label(F) == "Q1 2026"
    F.period = "2025-12-31:FY"
    assert period_label(F) == "FY 2025"
