"""El DCF parte de las ventas TTM cuando hay >= 2 trimestres tras el FY.

Owner (Nico, 4-nov-2026): el DCF partía de las ventas del último ejercicio
aunque ya hubiera trimestres más recientes presentados (PLTR: FY2025 4.475 M$
frente a 7.288 M$ en los últimos 12 meses, SEC). Regla general: con >= 2
trimestres presentados tras el cierre del FY ancla, base = suma de los 4
últimos trimestres; con menos, o con huecos/unidades distintas, el FY (nunca
se extrapola). La traza dice qué base se usó (``revenue_base``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.engines import standard_dcf
from app.valuation.engines.standard_dcf import StandardDCFEngine

M = 1_000_000
FY_REVENUE = 1_000 * M
# 2025: Q1..Q3 presentados (Q4 = 1000 − 700 = 300 derivado).
PRIOR = {"2025-03-31": 200, "2025-06-30": 240, "2025-09-30": 260}
# 2026: trimestres nuevos tras el FY2025, con su fecha de presentación.
NEW = {
    "2026-03-31": (350, date(2026, 5, 5)),
    "2026-06-30": (400, date(2026, 8, 4)),
    "2026-09-30": (450, date(2026, 11, 3)),
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session) -> Company:
    row = Company(
        ticker="TTMCO",
        name="Empresa sintética con trimestres",
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
    db.add(row)
    db.flush()
    return row


def _fact(company, metric, value, period, *, fy=None, fq="FY", unit="USD", filed=None):
    return FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        fiscal_year=fy,
        fiscal_quarter=fq,
        source_type="SEC",
        is_reported=True,
        confidence=Decimal("0.90"),
        filed=filed,
    )


def _seed(db, *, new=NEW, prior=PRIOR, quarter_unit="USD"):
    company = _company(db)
    for metric, value, unit in (
        ("revenue", FY_REVENUE, "USD"),
        ("fcf_margin", 0.20, "decimal"),
        ("revenue_growth", 0.05, "decimal"),
        ("net_debt", -100 * M, "USD"),
        ("shares_diluted", 100 * M, "shares"),
    ):
        db.add(_fact(company, metric, value, "2025-12-31:FY", fy=2025, unit=unit, filed=date(2026, 2, 17)))
    for end, value in prior.items():
        q = f"Q{(int(end[5:7]) + 2) // 3}"
        db.add(
            _fact(
                company, "revenue", value * M, f"{end}:{q}", fq=q, unit=quarter_unit, filed=date(2025, 11, 4)
            )
        )
    for end, (value, filed) in new.items():
        q = f"Q{(int(end[5:7]) + 2) // 3}"
        db.add(_fact(company, "revenue", value * M, f"{end}:{q}", fq=q, unit=quarter_unit, filed=filed))
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 11, 3),
            close=Decimal("50"),
            adj_close=Decimal("50"),
            source="ttm_test",
        )
    )
    db.commit()
    return company


@pytest.fixture(autouse=True)
def _rates(monkeypatch):
    monkeypatch.setattr(
        standard_dcf,
        "resolve_rates",
        lambda _db, _company, *, as_of=None: (0.09, "calculated_metric", 0.03, "tag_default", []),
    )


def _value(db, company, as_of=None):
    engine = StandardDCFEngine()
    return engine.value(engine.build_context(db, company, 50.0, as_of))


def test_tres_trimestres_tras_el_fy_parte_del_ttm(db):
    company = _seed(db)
    result = _value(db, company)

    assert result["status"] == "ok"
    base = result["trace"]["revenue_base"]
    assert base["basis"] == "ttm"
    # TTM = Q4-2025 derivado (1000 − 700) + 350 + 400 + 450.
    assert base["value"] == pytest.approx(1_500 * M)
    assert base["period_end"] == "2026-09-30"
    assert base["new_quarters_after_fy"] == 3
    assert [q["origin"] for q in base["quarters"]] == ["FY-9M", "10-Q", "10-Q", "10-Q"]


def test_el_ttm_sube_el_valor_frente_al_anual(db):
    ttm_company = _seed(db)
    ttm_value = _value(db, ttm_company)["base_value"]

    # Mismo caso con un solo trimestre nuevo: base anual.
    db2_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(db2_engine)
    with Session(db2_engine) as db2:
        annual_company = _seed(db2, new={"2026-03-31": NEW["2026-03-31"]})
        annual = _value(db2, annual_company)
    assert annual["trace"]["revenue_base"]["basis"] == "annual"
    assert ttm_value > annual["base_value"] * 1.3


def test_un_solo_trimestre_nuevo_mantiene_el_anual(db):
    company = _seed(db, new={"2026-03-31": NEW["2026-03-31"]})
    base = _value(db, company)["trace"]["revenue_base"]
    assert base["basis"] == "annual"
    assert base["value"] == pytest.approx(FY_REVENUE)
    assert base["period_end"] == "2025-12-31"
    assert base["new_quarters_after_fy"] == 1


def test_trimestre_previo_ausente_no_se_extrapola(db):
    # Sin Q2-2025 no se puede derivar el Q4-2025 ni cerrar la cadena.
    prior = {k: v for k, v in PRIOR.items() if k != "2025-06-30"}
    company = _seed(db, prior=prior, new={k: NEW[k] for k in ("2026-03-31", "2026-06-30")})
    base = _value(db, company)["trace"]["revenue_base"]
    assert base["basis"] == "annual"
    assert base["value"] == pytest.approx(FY_REVENUE)
    assert "sin extrapolar" in base["reason"]


def test_unidad_distinta_del_ejercicio_mantiene_el_anual(db):
    company = _seed(db, quarter_unit="EUR")
    base = _value(db, company)["trace"]["revenue_base"]
    assert base["basis"] == "annual"
    assert base["value"] == pytest.approx(FY_REVENUE)


def test_point_in_time_no_usa_trimestres_presentados_despues_del_corte(db):
    company = _seed(db)
    # A 1-sep-2026 solo estaban presentados Q1 y Q2 de 2026: TTM a junio.
    base = _value(db, company, as_of=date(2026, 9, 1))["trace"]["revenue_base"]
    assert base["basis"] == "ttm"
    assert base["period_end"] == "2026-06-30"
    # Q3-2025 260 + Q4-2025 300 + 350 + 400.
    assert base["value"] == pytest.approx(1_310 * M)
    # A 1-jun-2026 solo Q1: se mantiene el FY.
    early = _value(db, company, as_of=date(2026, 6, 1))["trace"]["revenue_base"]
    assert early["basis"] == "annual"
