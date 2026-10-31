"""DCF estandar: el margen FCF se normaliza como mediana de los ultimos 3 FY.

Motivacion KO (hechos SEC reales): margen del ultimo FY 10,1 % vs 21,3 % y
22,2 % de los dos anteriores (flujo operativo caido por un puntual con
beneficio estable); usar el ultimo ano en crudo deprimia la base de forma
severa (la magnitud exacta vista en prod no es reproducible de forma
aislada; depende del resto de supuestos del motor). Con historial >= 2 FY
la mediana resiste el ano puntual y la traza publica la normalizacion;
con un solo FY nada cambia. Guarda de tendencia: si todos los pares
consecutivos caen (tendencia monotona), se usa el ultimo FY porque la
mediana sobrevalora. Limite preexistente: margen negativo sin floor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.engines.standard_dcf import StandardDCFEngine


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db):
    row = Company(
        ticker="KO",
        name="KO test",
        exchange="TEST",
        currency="USD",
        sector="Consumer",
        industry="Beverages",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, company, metric, value, *, year, source_type="dcf_norm_test",
          filed=None, created_at=None):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit="decimal" if abs(float(value)) < 1 else "USD",
            period=f"{year}-12-31:FY",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type=source_type,
            is_reported=True,
            confidence=Decimal("0.90"),
            filed=filed,
            created_at=created_at,
        )
    )


def _base_facts(db, company):
    for year, margin in ((2022, 0.2217), (2023, 0.2130), (2024, 0.1007)):
        _fact(db, company, "fcf_margin", margin, year=year)
        _fact(db, company, "revenue", 47_000_000_000, year=year)
        _fact(db, company, "net_debt", 35_000_000_000, year=year)
        _fact(db, company, "revenue_growth", 0.03, year=year)
        _fact(db, company, "shares_diluted", 4_320_000_000, year=year)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 10, 30),
            close=Decimal("94.08"),
            adj_close=Decimal("94.08"),
            source="dcf_norm_test",
        )
    )
    db.commit()


def test_margin_is_median_of_last_3_fy_and_trace_shows_it(db):
    company = _company(db)
    # Historial NO monotono: el outlier (10,07 %) esta en el ano central, asi
    # la guarda de tendencia no aplica y la mediana resiste el puntual.
    for year, margin in ((2022, 0.2217), (2023, 0.1007), (2024, 0.2130)):
        _fact(db, company, "fcf_margin", margin, year=year)
        _fact(db, company, "revenue", 47_000_000_000, year=year)
        _fact(db, company, "net_debt", 35_000_000_000, year=year)
        _fact(db, company, "revenue_growth", 0.03, year=year)
        _fact(db, company, "shares_diluted", 4_320_000_000, year=year)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 10, 30),
            close=Decimal("94.08"),
            adj_close=Decimal("94.08"),
            source="dcf_norm_test",
        )
    )
    db.commit()
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 94.08))
    normalization = result["trace"]["fcf_margin_normalization"]
    assert normalization is not None
    assert normalization["method"] == "median_last_n_fiscal_years"
    assert normalization["n"] == 3
    assert normalization["latest_value"] == pytest.approx(0.2130)
    assert normalization["median_value"] == pytest.approx(0.2130)
    assert normalization["trend"] == "mixed"
    assert normalization["trend_guard_applied"] is False
    assert normalization["normalized_value"] == pytest.approx(0.2130)
    # Con el margen normalizado la base se mueve al rango del margen
    # historico (~21 %) en lugar de quedar deprimida por el outlier.
    assert result["base_value"] > 20.0


def test_single_fiscal_year_keeps_previous_behaviour(db):
    company = _company(db)
    _fact(db, company, "fcf_margin", 0.1007, year=2024)
    _fact(db, company, "revenue", 47_000_000_000, year=2024)
    _fact(db, company, "net_debt", 35_000_000_000, year=2024)
    _fact(db, company, "revenue_growth", 0.03, year=2024)
    _fact(db, company, "shares_diluted", 4_320_000_000, year=2024)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 10, 30),
            close=Decimal("94.08"),
            adj_close=Decimal("94.08"),
            source="dcf_norm_test",
        )
    )
    db.commit()
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 94.08))
    assert result["trace"]["fcf_margin_normalization"] is None
    assert result["base_value"] < 20.0


def test_trend_guard_uses_latest_fy_on_monotonic_decline(db):
    """MSFT-like (auditoria del piloto): 30,2 / 25,4 / 20,2 % en caida
    monotona. La mediana (25,4) sobrevalora; la guarda usa el ultimo FY."""
    company = _company(db)
    for year, margin in ((2022, 0.302), (2023, 0.254), (2024, 0.202)):
        _fact(db, company, "fcf_margin", margin, year=year)
        _fact(db, company, "revenue", 47_000_000_000, year=year)
        _fact(db, company, "net_debt", 35_000_000_000, year=year)
        _fact(db, company, "revenue_growth", 0.03, year=year)
        _fact(db, company, "shares_diluted", 4_320_000_000, year=year)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 10, 30),
            close=Decimal("94.08"),
            adj_close=Decimal("94.08"),
            source="dcf_norm_test",
        )
    )
    db.commit()
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 94.08))
    normalization = result["trace"]["fcf_margin_normalization"]
    assert normalization is not None
    assert normalization["latest_value"] == pytest.approx(0.202)
    assert normalization["median_value"] == pytest.approx(0.254)
    assert normalization["trend"] == "declining"
    assert normalization["trend_guard_applied"] is True
    assert normalization["normalized_value"] == pytest.approx(0.202)


def _fact_set(db, company, year, margin, *, filed=None):
    _fact(db, company, "fcf_margin", margin, year=year, filed=filed)
    _fact(db, company, "revenue", 47_000_000_000, year=year, filed=filed)
    _fact(db, company, "net_debt", 35_000_000_000, year=year, filed=filed)
    _fact(db, company, "revenue_growth", 0.03, year=year, filed=filed)
    _fact(db, company, "shares_diluted", 4_320_000_000, year=year, filed=filed)


def _price(db, company):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 10, 30),
            close=Decimal("94.08"),
            adj_close=Decimal("94.08"),
            source="dcf_norm_test",
        )
    )


def test_duplicate_sources_same_fy_count_as_one_fact(db):
    """Dos proveedores del mismo FY no ocupan dos plazas: 1 hecho por
    ejercicio, el mas recientemente conocido (mismo orden que el snapshot:
    fiscal_year desc, created_at desc)."""
    from datetime import UTC, datetime

    company = _company(db)
    _fact_set(db, company, 2022, 0.1007)
    _fact_set(db, company, 2023, 0.2217)
    # Duplicado FY2024: el hecho VIEJO vale 0.05, el NUEVO 0.213.
    _fact(db, company, "fcf_margin", 0.05, year=2024,
          source_type="provider_a", created_at=datetime(2025, 3, 1, tzinfo=UTC))
    _fact(db, company, "revenue", 47_000_000_000, year=2024)
    _fact(db, company, "net_debt", 35_000_000_000, year=2024)
    _fact(db, company, "revenue_growth", 0.03, year=2024)
    _fact(db, company, "shares_diluted", 4_320_000_000, year=2024)
    _fact(db, company, "fcf_margin", 0.213, year=2024,
          source_type="provider_b", created_at=datetime(2025, 6, 1, tzinfo=UTC))
    _price(db, company)
    db.commit()
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 94.08))
    normalization = result["trace"]["fcf_margin_normalization"]
    assert normalization is not None
    assert normalization["n"] == 3
    # Un hecho por FY: 2024 aparece una sola vez y con el valor mas reciente.
    assert [p["fiscal_year"] for p in normalization["periods"]] == [2024, 2023, 2022]
    assert normalization["periods"][0]["value"] == pytest.approx(0.213)
    # La mediana se calcula sobre 3 ejercicios, no sobre 4 filas.
    assert normalization["median_value"] == pytest.approx(0.213)
    assert normalization["trend"] == "mixed"
    assert normalization["trend_guard_applied"] is False


def test_old_snapshot_replay_excludes_facts_filed_after_cutoff(db):
    """Replay historico (as_of): un FY publicado despues del corte no puede
    alimentar la mediana de una valoracion de aquella fecha (eje filed,
    misma politica V1 que el snapshot)."""
    company = _company(db)
    _fact_set(db, company, 2022, 0.2217, filed=date(2023, 2, 1))
    _fact_set(db, company, 2023, 0.2130, filed=date(2024, 2, 1))
    _fact_set(db, company, 2024, 0.1007, filed=date(2025, 2, 1))
    _price(db, company)
    db.commit()
    engine = StandardDCFEngine()

    # Corte 2023-06-30: solo el FY2022 era conocible -> sin normalizacion.
    past = engine.value(engine.build_context(db, company, 94.08, as_of=date(2023, 6, 30)))
    assert past["trace"]["fcf_margin_normalization"] is None

    # Corte 2024-06-30: FY2022 y FY2023 conocibles, FY2024 aun no publicado.
    replay = engine.value(engine.build_context(db, company, 94.08, as_of=date(2024, 6, 30)))
    normalization = replay["trace"]["fcf_margin_normalization"]
    assert normalization is not None
    assert normalization["n"] == 2
    assert [p["fiscal_year"] for p in normalization["periods"]] == [2023, 2022]
    assert normalization["median_value"] == pytest.approx((0.2217 + 0.2130) / 2)
