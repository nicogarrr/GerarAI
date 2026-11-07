"""Experimental size bands remain diagnostic; CAPM drives the DCF."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact
from app.models.entities import Base
from app.valuation import wacc_band
from app.valuation.currency import FxQuote
from app.valuation.engines import standard_dcf
from app.valuation.engines.base import WACC_ABOVE_TERMINAL_GROWTH
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.wacc_band import (
    WACC_MARKET_CAP_BANDS_USD_M,
    band_wacc_for_market_cap,
)

M = 1_000_000
CAPM = 0.09


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session, *, shares: float, unit: str = "USD") -> Company:
    company = Company(
        ticker="BANDCO",
        name="Empresa sintética para la banda de WACC",
        exchange="TEST",
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
    for metric, value, metric_unit in (
        ("revenue", 10_000 * M, unit),
        ("fcf_margin", 0.20, "decimal"),
        ("revenue_growth", 0.05, "decimal"),
        ("net_debt", -100 * M, unit),
        ("shares_diluted", shares, "shares"),
    ):
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit=metric_unit,
                period="2025-12-31:FY",
                fiscal_year=2025,
                fiscal_quarter="FY",
                source_type="SEC",
                is_reported=True,
                confidence=Decimal("0.90"),
                filed=date(2026, 2, 17),
            )
        )
    db.commit()
    return company


def _rates(monkeypatch, *, wacc=CAPM, source="calculated_metric", terminal=0.03, terminal_source="tag_default"):
    monkeypatch.setattr(
        standard_dcf,
        "resolve_rates",
        lambda _db, _company, *, as_of=None: (wacc, source, terminal, terminal_source, []),
    )


def _value(db, company, price: float | None = 50.0):
    engine = StandardDCFEngine()
    context = engine.build_context(db, company, price, price_as_of=date(2026, 11, 3))
    return engine.value(context)


# --- La banda, con sus cortes exactos -------------------------------------


@pytest.mark.parametrize(
    ("cap_m", "expected"),
    [
        (3_000_000, 0.085),
        (200_000, 0.085),
        (199_999.99, 0.095),
        (50_000, 0.095),
        (49_999.99, 0.105),
        (10_000, 0.105),
        (9_999.99, 0.115),
        (1, 0.115),
    ],
)
def test_cortes_exactos_de_la_banda(cap_m, expected):
    rate, _label = band_wacc_for_market_cap(cap_m * M)
    assert rate == pytest.approx(expected)


def test_banda_experimental_no_cambia_sus_constantes():
    assert WACC_MARKET_CAP_BANDS_USD_M == (
        (200_000.0, 0.085),
        (50_000.0, 0.095),
        (10_000.0, 0.105),
        (0.0, 0.115),
    )


# --- El motor -------------------------------------------------------------


def test_gran_capitalizacion_descuenta_con_capm_y_banda_solo_diagnostica(db, monkeypatch):
    _rates(monkeypatch)
    company = _seed(db, shares=5_000 * M)  # 50 $ × 5.000 M = 250.000 M$

    result = _value(db, company)

    trace = result["trace"]
    assert result["status"] == "ok"
    assert trace["wacc"] == pytest.approx(CAPM)
    assert trace["wacc_source"] == "calculated_metric"
    assert trace["wacc_policy"] == "capm_traceable"
    assert trace["wacc_band"]["band"] == ">= 200,000 M$"
    assert trace["wacc_band"]["market_cap_usd"] == pytest.approx(250_000 * M)
    assert trace["wacc_capm"] == pytest.approx(CAPM)
    assert trace["wacc_capm_source"] == "calculated_metric"
    assert trace["scenarios"]["base"]["definition"]["assumptions"]["wacc"] == pytest.approx(CAPM)


def test_sin_capm_trazable_sigue_no_publicable_aunque_haya_banda(db, monkeypatch):
    # A market cap does not make an untraced fallback rate publishable.
    _rates(monkeypatch, wacc=0.10, source="tag_default")
    company = _seed(db, shares=100 * M)  # 5.000 M$

    result = _value(db, company)

    assert result["trace"]["wacc"] == pytest.approx(0.10)
    assert result["trace"]["wacc_capm"] is None
    assert result["trace"]["wacc_capm_source"] == "tag_default"
    assert "traceable_wacc" in result["publication_blockers"]
    assert result["publishable"] is False


def test_divisa_no_usd_convierte_la_capitalizacion_con_el_tipo_de_cambio(db, monkeypatch):
    _rates(monkeypatch)
    company = _seed(db, shares=100 * M, unit="EUR")  # 50 × 100 M = 5.000 M EUR
    seen = {}

    def fake_fx(_db, src, dst, on, **_kwargs):
        seen["args"] = (src, dst, on)
        return FxQuote(src, dst, 2.5, on, "ECB", (src, dst))

    monkeypatch.setattr(wacc_band, "resolve_fx", fake_fx)

    trace = _value(db, company)["trace"]

    # FX still describes the diagnostic band, not the applied discount rate.
    assert seen["args"] == ("EUR", "USD", date(2026, 11, 3))
    assert trace["wacc"] == pytest.approx(CAPM)
    assert trace["wacc_band"]["market_cap_usd"] == pytest.approx(12_500 * M)
    assert trace["wacc_band"]["reporting_currency"] == "EUR"
    assert trace["wacc_band"]["fx"]["rate"] == pytest.approx(2.5)


def test_sin_tipo_de_cambio_sigue_el_capm_con_el_motivo(db, monkeypatch):
    _rates(monkeypatch)
    company = _seed(db, shares=100 * M, unit="EUR")
    monkeypatch.setattr(wacc_band, "resolve_fx", lambda *_a, **_k: None)

    trace = _value(db, company)["trace"]

    assert trace["wacc"] == pytest.approx(CAPM)
    assert trace["wacc_source"] == "calculated_metric"
    assert trace["wacc_policy"] == "capm_traceable"
    assert "tipo de cambio EUR/USD" in trace["wacc_band"]["fallback_reason"]


def test_sin_precio_sigue_el_wacc_de_siempre(db, monkeypatch):
    _rates(monkeypatch)
    company = _seed(db, shares=5_000 * M)

    trace = _value(db, company, price=None)["trace"]

    assert trace["wacc"] == pytest.approx(CAPM)
    assert trace["wacc_policy"] == "capm_traceable"
    assert "sin precio" in trace["wacc_band"]["fallback_reason"]


def test_la_guarda_wacc_mayor_que_g_sigue_activa_con_capm(db, monkeypatch):
    # CAPM equals g: the DCF remains invalid even if a size band is available.
    _rates(monkeypatch, terminal=0.09, terminal_source="tag_default")
    company = _seed(db, shares=5_000 * M)

    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert WACC_ABOVE_TERMINAL_GROWTH in result["missing_inputs"]
    assert result["trace"]["wacc"] == pytest.approx(CAPM)


def test_g_inferida_resuelta_no_la_reescribe_la_banda(db, monkeypatch):
    # resolve_rates already selected this pair. The diagnostic band must
    # not run a second rate selection or replace its terminal growth.
    _rates(monkeypatch, terminal=0.08, terminal_source="inferred_input")
    company = _seed(db, shares=5_000 * M)

    trace = _value(db, company)["trace"]

    assert trace["wacc"] == pytest.approx(CAPM)
    assert trace["terminal_source"] == "inferred_input"
    assert "terminal_growth" not in trace["inferred_inputs_ignored"]


def test_solo_el_dcf_estandar_recoge_diagnostico_de_banda():
    # Bancos, aseguradoras, REIT, holdings, materias primas y pre-ingresos
    # conservan su propia tasa: ningún otro motor llama a la banda.
    engines = Path(standard_dcf.__file__).parent
    users = sorted(
        path.name
        for path in engines.glob("*.py")
        if re.search(r"\bresolve_band_wacc\b", path.read_text(encoding="utf-8"))
    )
    assert users == ["standard_dcf.py"]
