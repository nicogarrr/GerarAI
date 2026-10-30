"""Bandas de PER historicas de la ficha en una base de acciones comun.

El cierre guardado esta en la base del dia en que se descargo (el sync diario
guarda el cierre del dia y reescribe la ultima semana; el backfill de Yahoo
viene ajustado por splits) y el BPA guardado es la ultima cifra presentada
(reexpresada si el 10-K salio tras el split). Antes se dividian tal cual y el
PER de los anos previos a un split salia multiplicado o dividido por el ratio.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, CorporateAction, FinancialFact, MarketPrice
from app.services.historical_valuation_service import HistoricalValuationService

AS_OF = date(2026, 3, 1)
SPLIT = date(2025, 6, 9)


def _seed(db, closes, eps_by_year, *, split=True):
    company = Company(
        ticker="SPL", name="Split Co", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="operating",
        valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    for day, close in closes:
        db.add(MarketPrice(company_id=company.id, date=day, open=close, high=close,
                           low=close, close=Decimal(close), quote_currency="USD",
                           source="yfinance"))
    for year, (value, filed) in eps_by_year.items():
        db.add(FinancialFact(
            company_id=company.id, metric="eps_diluted", value=Decimal(value),
            unit="USD/share", period=f"{year}-12-31:FY", fiscal_year=year,
            fiscal_quarter="FY", source_type="SEC", is_reported=True, filed=filed,
        ))
    if split:
        db.add(CorporateAction(company_id=company.id, action_type="split",
                               ratio=Decimal(4), effective_date=SPLIT,
                               description="4:1"))
    db.commit()
    return company


def _pe(result, year):
    return next(p["pe"] for p in result["series"] if p["year"] == year)


def test_cierres_sin_ajustar_y_bpa_reexpresado_dan_el_mismo_per():
    """Sync diario: cierres antes del split en base antigua (400), la ultima
    semana reescrita ya ajustada (101). BPA FY2024 reexpresado en el 10-K de
    feb-2026 (2,5 por accion actual). Calculo independiente: 2024 = (400/4) /
    2,5 = 40; 2025 = 110 / 2,75 = 40. Antes: 2024 = 400 / 2,5 = 160."""
    db = _db()
    company = _seed(db, [
        (date(2024, 12, 31), "400"), (date(2025, 5, 30), "410"),
        (date(2025, 6, 2), "404"), (date(2025, 6, 3), "101"),
        (date(2025, 6, 10), "102"), (date(2025, 12, 31), "110"),
    ], {2024: ("2.5", date(2026, 2, 20)), 2025: ("2.75", date(2026, 2, 20))})
    result = HistoricalValuationService().build(db, company, years=3, as_of=AS_OF)
    assert _pe(result, 2024) == pytest.approx(Decimal(40))
    assert _pe(result, 2025) == pytest.approx(Decimal(40))


def test_cierres_ajustados_y_bpa_original_dan_el_mismo_per():
    """Backfill de Yahoo tras el split: serie continua (ya ajustada, 100). BPA
    FY2024 original del 10-K de feb-2025 (10, base antigua). Calculo
    independiente: 2024 = 100 / (10/4) = 40. Antes: 100 / 10 = 10."""
    db = _db()
    company = _seed(db, [
        (date(2024, 12, 31), "100"), (date(2025, 6, 6), "101"),
        (date(2025, 6, 9), "101.5"), (date(2025, 12, 31), "110"),
    ], {2024: ("10", date(2025, 2, 20))})
    result = HistoricalValuationService().build(db, company, years=3, as_of=AS_OF)
    assert _pe(result, 2024) == pytest.approx(Decimal(40))


def test_sin_cierres_alrededor_del_split_el_per_previo_es_nd():
    """Sin ningun cierre cerca del split no se sabe en que base esta el de
    2024: N/D (y el ano queda listado) antes que un PER x4 o /4."""
    db = _db()
    company = _seed(db, [(date(2024, 12, 31), "400"), (date(2025, 12, 31), "110")],
                    {2024: ("2.5", date(2026, 2, 20)), 2025: ("2.75", date(2026, 2, 20))})
    result = HistoricalValuationService().build(db, company, years=3, as_of=AS_OF)
    assert _pe(result, 2024) is None
    assert _pe(result, 2025) == pytest.approx(Decimal(40))
    assert result["split_basis"]["price_basis_unknown_years"] == [2024]


def test_sin_splits_nada_cambia():
    db = _db()
    company = _seed(db, [(date(2024, 12, 31), "400")],
                    {2024: ("10", date(2025, 2, 20))}, split=False)
    result = HistoricalValuationService().build(db, company, years=3, as_of=AS_OF)
    assert _pe(result, 2024) == pytest.approx(Decimal(40))


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
