"""Tests dorados de fórmulas técnicas y de scoring (auditoría de fórmulas, fase 2).

Cada test llama a la función real con las entradas de la auditoría
(``GerarAI_formulas.pdf``) y compara con el valor calculado a mano; la fuente
y la cuenta van en el docstring.

Fuera de este fichero: el motor de niveles DCA (``dca_signal_engine``), que
aún no está en main (su PR lo lleva otro trabajo y la fórmula cambió a la
«Fórmula Nico v1»), y la variación diaria de las alertas, ya cubierta en
``test_alert_rule_price_change.py`` (#2270).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Company, FinancialFact
from app.models.entities import Base
from app.services.market_regime_quant import paired_beta
from app.services.propicks_funnel_service import SCORE_WEIGHTS, _percentile_ranks, _revenue_cagr
from app.services.propicks_price_service import momentum_from_series


def _sesiones(n: int, inicio: date = date(2025, 1, 6)) -> list[date]:
    """n días hábiles consecutivos (lunes a viernes)."""
    out: list[date] = []
    day = inicio
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def test_beta_por_covarianza_entre_varianza():
    """β = cov(r_i, r_m)/var(r_m), mismo ddof arriba y abajo (CFA Institute,
    Portfolio Management; Sharpe, 1964).
    A mano: si cada día r_i = 0,001 + 2·r_m, cov(r_i, r_m) = 2·var(r_m) → β = 2."""
    dias = _sesiones(64)
    mercado = [0.01, -0.02, 0.015, -0.005, 0.0, 0.02, -0.01, 0.005] * 8
    px_m, px_a = 100.0, 50.0
    bench: dict[date, float] = {dias[0]: px_m}
    asset: dict[date, float] = {dias[0]: px_a}
    for dia, r in zip(dias[1:], mercado, strict=False):
        px_m *= 1 + r
        px_a *= 1 + 0.001 + 2 * r
        bench[dia] = px_m
        asset[dia] = px_a
    out = paired_beta(asset, bench, 63)
    assert out["status"] == "disponible"
    assert out["beta"] == pytest.approx(2.0, abs=1e-4)
    assert paired_beta(bench, bench, 63)["beta"] == pytest.approx(1.0)


def test_percentiles_con_empates():
    """Percentil por rango con empates en el punto medio, (i + j)/2/(n − 1)
    (Hyndman & Fan, 1996, tipo 7; Investopedia «Percentile Rank»).
    A mano: {10, 20, 20, 30} → 0, 0,5, 0,5, 1."""
    assert _percentile_ranks({1: 10.0, 2: 20.0, 3: 20.0, 4: 30.0}) == {1: 0.0, 2: 0.5, 3: 0.5, 4: 1.0}
    assert _percentile_ranks({7: 3.0}) == {7: 0.5}
    assert _percentile_ranks({}) == {}


def test_pesos_del_score_compuesto_suman_uno():
    """Score = 100·Σ w_k·pct_k/Σ w_k (metodología de índices factoriales de
    MSCI). A mano: 0,25 + 0,15 + 0,20 + 0,10 + 0,10 + 0,05 + 0,10 + 0,05 = 1."""
    assert sum(SCORE_WEIGHTS.values()) == pytest.approx(1.0)
    assert SCORE_WEIGHTS["spread_roic_wacc"] == pytest.approx(0.25)


def test_momentum_a_12_meses():
    """Rentabilidad simple entre el último cierre ajustado y el más cercano a
    `días` atrás, con ±20 días de margen (Jegadeesh & Titman, 1993).
    A mano: 100 → 120 en 365 días → 0,20. Sin punto a ±20 días → N/D."""
    hoy = date(2026, 6, 30)
    serie = [(hoy - timedelta(days=365), Decimal("100")), (hoy, Decimal("120"))]
    assert momentum_from_series(serie, 365) == Decimal("0.2")
    lejos = [(hoy - timedelta(days=400), Decimal("100")), (hoy, Decimal("120"))]
    assert momentum_from_series(lejos, 365) is None


def test_cagr_de_ingresos_del_embudo_propicks():
    """CAGR = (V_fin/V_ini)^(1/años) − 1 sobre ejercicios FY, con al menos 3
    años de datos (Investopedia «CAGR»). A mano: 100 → 200 en 3 años →
    2^(1/3) − 1 = 0,2599."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        company = Company(
            ticker="TGOLDPP",
            name="Golden ProPicks",
            exchange="NYSE",
            currency="USD",
            sector="Technology",
            industry="Software",
            company_type="standard",
            valuation_model="standard_dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        for year, value in ((2022, "100"), (2023, "130"), (2024, "160"), (2025, "200")):
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric="revenue",
                    value=Decimal(value),
                    unit="USD",
                    period=f"FY{year}",
                    fiscal_year=year,
                    fiscal_quarter="FY",
                    source_type="SEC",
                    is_reported=True,
                    confidence=Decimal("0.9"),
                )
            )
        db.commit()
        out = _revenue_cagr(db)
    assert out[company.id] == pytest.approx(2 ** (1 / 3) - 1)
    assert out[company.id] == pytest.approx(0.2599, abs=1e-4)
