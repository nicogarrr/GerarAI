"""Supervivientes de mutmut en ``portfolio_fx_service`` (ronda 2).

Cada test fija un comportamiento que un mutante cambiaba sin que nada fallase:
el filtro de la inversa (sin el, cualquier fila con esa quote valdria), el
lookahead en la tabla en memoria, la clave de upsert y la validacion ISO.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate, Portfolio
from app.services.portfolio_fx_service import PortfolioFXService, currency_key

D1 = date(2026, 9, 1)
D2 = date(2026, 9, 23)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_currency_key_distingue_subunidades():
    assert currency_key("usd") == "USD"
    assert currency_key("GBP") == "GBP"
    assert currency_key("GBp") == "GBP/100"
    assert currency_key("GBX") == "GBP/100"


def test_base_currency_por_defecto_y_en_mayusculas(db):
    service = PortfolioFXService()
    assert service.base_currency(db) == "EUR"
    db.add(Portfolio(name="Main", base_currency="usd", is_default=True))
    db.flush()
    assert service.base_currency(db) == "USD"


def test_set_base_currency_normaliza_y_valida(db):
    service = PortfolioFXService()
    assert service.set_base_currency(db, " usd ").base_currency == "USD"
    assert service.base_currency(db) == "USD"
    for bad in ("EURO", "U$D", "EU", ""):
        with pytest.raises(ValueError, match="three-letter ISO"):
            service.set_base_currency(db, bad)
    assert service.base_currency(db) == "USD"


def test_inversa_no_usa_filas_de_otro_par(db):
    service = PortfolioFXService()
    # Distractor: un par con la misma quote (EUR) pero otra base (GBP).
    service.upsert_rate(db, base_currency="GBP", quote_currency="EUR",
                        rate=Decimal("0.85"), rate_date=D1, source="ecb")
    db.flush()
    # USD->EUR no existe en ninguna direccion: N/D, nunca el tipo de la libra.
    assert service.rate(db, quote_currency="USD", base_currency="EUR", as_of=D2) is None
    service.upsert_rate(db, base_currency="USD", quote_currency="EUR",
                        rate=Decimal("0.80"), rate_date=D1, source="ecb")
    db.flush()
    found = service.rate_with_provenance(db, quote_currency="USD", base_currency="EUR", as_of=D2)
    assert found["rate"] == Decimal("1") / Decimal("0.80")
    assert found["direction"] == "inverse"
    assert found["source"] == "ecb"
    assert found["rate_date"] == D1


def test_misma_divisa_trae_procedencia_vacia(db):
    found = PortfolioFXService().rate_with_provenance(
        db, quote_currency="eur", base_currency="EUR", as_of=D2,
    )
    assert found == {"rate": Decimal("1"), "rate_date": None, "source": None, "direction": "same"}


def test_rate_from_table_inversa_futura_no_se_usa():
    table = {("USD", "EUR"): [(D2, Decimal("0.80"))]}
    # Solo existe una inversa POSTERIOR a as_of: nada (sin lookahead).
    assert PortfolioFXService.rate_from_table(
        table, quote_currency="USD", base_currency="EUR", as_of=D1,
    ) is None
    assert PortfolioFXService.rate_from_table(
        table, quote_currency="USD", base_currency="EUR", as_of=D2,
    ) == Decimal("1") / Decimal("0.80")


def test_rates_for_misma_divisa_no_consulta_la_bd():
    # db=None: con todas las divisas iguales a la base (o su subunidad) no hay query.
    rates = PortfolioFXService().rates_for(
        None, quote_currencies={"GBP", "GBp"}, base_currency="GBP", as_of=D2,
    )
    assert rates == {"GBP": Decimal("1"), "GBP/100": Decimal("0.01")}


def test_upsert_actualiza_solo_su_par(db):
    service = PortfolioFXService()
    service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                        rate=Decimal("1.10"), rate_date=D1, source="ecb")
    service.upsert_rate(db, base_currency="EUR", quote_currency="GBP",
                        rate=Decimal("0.85"), rate_date=D1, source="ecb")
    service.upsert_rate(db, base_currency="GBP", quote_currency="USD",
                        rate=Decimal("1.30"), rate_date=D1, source="ecb")
    db.flush()
    assert db.scalar(select(func.count()).select_from(FXRate)) == 3
    rates = {(r.base_currency, r.quote_currency): r.rate for r in db.scalars(select(FXRate))}
    assert rates == {
        ("EUR", "USD"): Decimal("1.10"),
        ("EUR", "GBP"): Decimal("0.85"),
        ("GBP", "USD"): Decimal("1.30"),
    }
    # Mismo par y fecha: actualiza, no duplica.
    service.upsert_rate(db, base_currency="eur", quote_currency="usd",
                        rate=Decimal("1.12"), rate_date=D1, source="  ")
    db.flush()
    assert db.scalar(select(func.count()).select_from(FXRate)) == 3
    row = db.scalar(select(FXRate).where(FXRate.base_currency == "EUR", FXRate.quote_currency == "USD"))
    assert row.rate == Decimal("1.12")
    assert row.source == "manual"


def test_upsert_recorta_la_fuente_a_80(db):
    row = PortfolioFXService().upsert_rate(
        db, base_currency="EUR", quote_currency="USD", rate=Decimal("1.1"),
        rate_date=D1, source="x" * 100,
    )
    assert row.source == "x" * 80


@pytest.mark.parametrize(
    ("base", "quote", "rate", "message"),
    [
        ("EU1", "USD", "1.1", "three-letter ISO"),
        ("EUR", "U$D", "1.1", "three-letter ISO"),
        ("EURO", "USD", "1.1", "three-letter ISO"),
        ("EUR", "EUR", "1.5", "Same-currency FX rate must equal 1"),
        ("EUR", "USD", "0", "FX rate must be positive"),
        ("EUR", "USD", "-1", "FX rate must be positive"),
    ],
)
def test_upsert_rechaza_entradas_invalidas(db, base, quote, rate, message):
    with pytest.raises(ValueError, match=message):
        PortfolioFXService().upsert_rate(
            db, base_currency=base, quote_currency=quote, rate=Decimal(rate),
            rate_date=D1, source="manual",
        )
