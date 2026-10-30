"""PER con EPS en acciones actuales: si hubo split tras el cierre del
ejercicio del EPS, precio_hoy / eps_reportado infla el PER por el factor
del split. El EPS se divide por el factor acumulado posterior a SU
periodo (espejo del ajuste de recuentos, que multiplica)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Company,
    CorporateAction,
    FinancialFact,
    MarketPrice,
    Tenant,
)
from app.services.screener_fundamentals import load_screener_ratios
from app.services.split_adjustment import (
    cumulative_split_factor_after,
    period_end_date,
)

TODAY = date(2026, 9, 25)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__, Company.__table__, FinancialFact.__table__,
            MarketPrice.__table__, CorporateAction.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    row = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Hardware", company_type="operating",
        valuation_model="standard_dcf",
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, company, metric, value, unit, *, year=2024, period=None):
    row = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
        period=period or f"{year}-12-31:FY", fiscal_year=year,
        fiscal_quarter="FY", source_type="SEC", is_reported=True,
    )
    db.add(row)
    db.flush()
    return row


def _price(db, company, close):
    db.add(MarketPrice(company_id=company.id, date=TODAY,
                       close=Decimal(close), adj_close=Decimal(close),
                       source="yahoo"))
    db.flush()


def _split(db, company, effective: date, ratio: str):
    db.add(CorporateAction(
        company_id=company.id, action_type="split", ratio=Decimal(ratio),
        effective_date=effective, description="test split",
    ))
    db.flush()


def test_pe_divides_eps_by_post_period_split_factor(db):
    """EPS FY2024 = 6 (base pre-split), split 4:1 en 2025, cierre hoy 60:
    PER = 60 / (6/4) = 40, no 10."""
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(40.0)
    prov = result["ratioProvenance"]["facts"]["pe"]
    assert prov["split_factor"] == "4"
    assert "cumulative_split_factor" in prov["calculation"]


def test_pe_ignores_splits_before_period_end(db):
    """Split ANTES del cierre del ejercicio del EPS: ya esta dentro del EPS
    reportado, no se ajusta."""
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2024, 6, 9), "4")  # antes de 2024-12-31
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(10.0)
    assert "split_factor" not in result["ratioProvenance"]["facts"]["pe"]


def test_pe_stacks_multiple_splits(db):
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2025, 1, 15), "2")
    _split(db, company, date(2025, 7, 15), "2")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(40.0)  # 60 / (6/4)


def test_helpers_never_guess():
    assert cumulative_split_factor_after([(date(2025, 1, 1), Decimal(4))], None) == 1
    assert period_end_date("garbage") is None
    assert period_end_date("2025-09-27:FY") == date(2025, 9, 27)


def test_pb_multiplies_shares_by_post_period_split_factor(db):
    """P/B con acciones en base actual: patrimonio FY2024 = 1200, acciones
    diluidas FY2024 = 100 (pre-split), split 4:1 en 2025, cierre hoy 30.
    BVPS actual = 1200 / (100 * 4) = 3 -> P/B = 30 / 3 = 10, no 2,5
    (30 / (1200/100)), que infravaloraba el multiplo por el factor del split."""
    company = _company(db)
    _price(db, company, "30")
    _fact(db, company, "total_equity", "1200", "USD")
    _fact(db, company, "shares_diluted", "100", "shares")
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pb"] == pytest.approx(10.0)
    prov = result["ratioProvenance"]["facts"]["pb"]
    assert prov["split_factor"] == "4"


def test_pb_ignores_splits_before_period_end(db):
    """Split ANTES del cierre: el recuento reportado ya lo incluye."""
    company = _company(db)
    _price(db, company, "30")
    _fact(db, company, "total_equity", "1200", "USD")
    _fact(db, company, "shares_diluted", "400", "shares")
    _split(db, company, date(2024, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pb"] == pytest.approx(10.0)
    assert "split_factor" not in result["ratioProvenance"]["facts"]["pb"]


# --- Regla unica consciente del `filed` (fact_split_factor) -------------------


def test_pe_no_reajusta_un_10k_publicado_tras_el_split(db):
    """EPS FY2024 publicado el 2025-07-01, DESPUES del split 4:1 del
    2025-06-09: el 10-K ya viene reexpresado (ASC 260), EPS 1,5 en acciones
    actuales. Calculo independiente: PER = 60 / 1,5 = 40. Con la regla solo
    por cierre de ejercicio se dividia otra vez: 60 / (1,5/4) = 160."""
    company = _company(db)
    _price(db, company, "60")
    eps = _fact(db, company, "eps_diluted", "1.5", "USD/share")
    eps.filed = date(2025, 7, 1)
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(40.0)
    assert "split_factor" not in result["ratioProvenance"]["facts"]["pe"]


def test_pe_ajusta_un_10k_publicado_antes_del_split(db):
    """Mismo EPS en base antigua (6) publicado el 2025-02-20, ANTES del
    split: se ajusta, PER = 60 / (6/4) = 40."""
    company = _company(db)
    _price(db, company, "60")
    eps = _fact(db, company, "eps_diluted", "6", "USD/share")
    eps.filed = date(2025, 2, 20)
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(40.0)


def test_pe_ignora_split_posterior_a_la_fecha_del_precio(db):
    """Cierre del 2026-09-25 (pre-split) y split anunciado para despues: ese
    precio aun no refleja el split. PER = 60 / 6 = 10, no 40."""
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2026, 10, 15), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(10.0)


def test_pb_no_reajusta_acciones_de_un_10k_publicado_tras_el_split(db):
    """Patrimonio 1200, acciones FY2024 ya reexpresadas (400) en un 10-K
    publicado tras el split 4:1. BVPS = 1200/400 = 3 -> P/B = 30/3 = 10.
    Con la regla vieja: 1200/(400*4) = 0,75 -> P/B 40."""
    company = _company(db)
    _price(db, company, "30")
    _fact(db, company, "total_equity", "1200", "USD")
    shares = _fact(db, company, "shares_diluted", "400", "shares")
    shares.filed = date(2025, 7, 1)
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pb"] == pytest.approx(10.0)


def test_fact_split_factor_regla_unica():
    from app.services.split_adjustment import fact_split_factor

    events = [(date(2025, 6, 9), Decimal(4))]
    fy = "2024-12-31:FY"
    assert fact_split_factor(events, period=fy, filed=date(2025, 2, 20)) == 4
    assert fact_split_factor(events, period=fy, filed=date(2025, 7, 1)) == 1
    assert fact_split_factor(events, period=fy, filed=None) == 4
    assert fact_split_factor(events, period=fy, filed=None, cutoff=date(2025, 6, 1)) == 1
    # Portada (DEI): recuento a SU fecha; publicarlo despues no lo reexpresa.
    dei = "2025-06-01:DEI"
    assert fact_split_factor(events, period=dei, filed=date(2025, 7, 1)) == 4
    assert fact_split_factor(events, period="basura", filed=date(2025, 7, 1)) == 1


def test_serie_de_acciones_del_modelo_largo_plazo_no_reajusta_reexpresadas():
    """Serie de acciones (long_term_model_service): el FY2016 se publico en
    2017 en base antigua (5,5B) y el FY2019 se guardo de un 10-K de 2021, ya
    reexpresado tras el split 4:1 de 2020 (17,5B). Calculo independiente en
    acciones actuales: FY2016 = 5,5B x 4 = 22B; FY2019 = 17,5B (sin tocar).
    La regla vieja daba FY2019 = 70B y fingia una dilucion enorme."""
    from app.models import CorporateAction, FinancialFact
    from app.services.long_term_model_service import _adjust_share_facts

    old = FinancialFact(metric="shares_diluted", value=Decimal("5.5e9"),
                        period="2016-09-24:FY", filed=date(2017, 11, 3))
    restated = FinancialFact(metric="shares_diluted", value=Decimal("17.5e9"),
                             period="2019-09-28:FY", filed=date(2021, 10, 29))
    split = CorporateAction(action_type="split", ratio=Decimal(4),
                            effective_date=date(2020, 8, 31))
    out = _adjust_share_facts([old, restated], [split])
    assert Decimal(out[0].value) == Decimal("22e9")
    assert Decimal(out[1].value) == Decimal("17.5e9")
