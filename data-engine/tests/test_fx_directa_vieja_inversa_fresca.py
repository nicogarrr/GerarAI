"""Tipo de cambio: entre la fila directa y la inversa gana la MAS RECIENTE.

Con el par guardado en los dos sentidos (p. ej. una cartera que fue en USD y
paso a EUR: quedan filas USD->EUR viejas y el BCE sigue escribiendo EUR->USD
cada dia, o un tipo manual metido una vez en el sentido contrario), la busqueda
preferia SIEMPRE la directa aunque tuviera meses. La conversion usaba un tipo
viejo y ``resolve_fx`` (valoracion) devolvia «sin tipo» porque la directa
estaba caducada, aunque hubiera una inversa de ayer. Ahora se elige la fila con
fecha mas reciente; en empate de fecha, la directa (como antes). Las cinco
implementaciones (BD, tabla en memoria, rates_for, la de inteligencia y la
fiscal con caducidad) eligen lo mismo.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_intelligence_service import _fx_rate_with_date
from app.services.tax_report_service import _rate_not_older_than
from app.valuation.currency import resolve_fx

SVC = PortfolioFXService()
VIEJA = date(2026, 3, 2)
AYER = date(2026, 11, 3)
HOY = date(2026, 11, 4)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _add(db, base, quote, rate, on, source):
    db.add(FXRate(base_currency=base, quote_currency=quote,
                  rate=Decimal(rate), rate_date=on, source=source))
    db.commit()


def _cartera_que_paso_de_usd_a_eur(db):
    # Fila USD->EUR de cuando la cartera iba en USD (USD por 1 EUR), ya vieja.
    _add(db, "USD", "EUR", "1.05", VIEJA, "ECB-antiguo")
    # El BCE sigue escribiendo EUR->USD (EUR por 1 USD) cada dia.
    _add(db, "EUR", "USD", "0.90", AYER, "ECB")


def test_rate_with_provenance_usa_la_inversa_fresca_no_la_directa_vieja(db):
    _cartera_que_paso_de_usd_a_eur(db)
    found = SVC.rate_with_provenance(db, quote_currency="EUR", base_currency="USD", as_of=HOY)
    assert found["rate"] == Decimal("1") / Decimal("0.90")
    assert (found["rate_date"], found["source"], found["direction"]) == (AYER, "ECB", "inverse")
    assert SVC.rate(db, quote_currency="EUR", base_currency="USD", as_of=HOY) == found["rate"]


def test_tabla_en_memoria_y_rates_for_eligen_lo_mismo(db):
    _cartera_que_paso_de_usd_a_eur(db)
    table = SVC.fx_table(db, currencies={"EUR"}, base_currency="USD", as_of_max=HOY)
    esperado = Decimal("1") / Decimal("0.90")
    assert SVC.rate_from_table(table, quote_currency="EUR", base_currency="USD", as_of=HOY) == esperado
    assert SVC.rates_for(db, quote_currencies={"EUR"}, base_currency="USD", as_of=HOY) == {"EUR": esperado}
    assert _fx_rate_with_date(table, quote_currency="EUR", base_currency="USD", as_of=HOY) == (AYER, esperado)


def test_resolve_fx_no_da_sin_tipo_con_una_inversa_de_ayer(db):
    # Valoracion: cuentas en EUR de un valor que cotiza en USD.
    _cartera_que_paso_de_usd_a_eur(db)
    quote = resolve_fx(db, "EUR", "USD", HOY)
    assert quote is not None
    assert quote.rate == pytest.approx(float(Decimal("1") / Decimal("0.90")))
    assert (quote.rate_date, quote.source, quote.path) == (AYER, "ECB", ("EUR", "USD"))


def test_fiscal_con_caducidad_tambien_coge_la_mas_reciente():
    # Las dos dentro de los 7 dias: antes ganaba la directa (mas vieja).
    table = {
        ("EUR", "USD"): [(date(2025, 3, 3), Decimal("0.95"))],
        ("USD", "EUR"): [(date(2025, 3, 7), Decimal("1.25"))],
    }
    assert _rate_not_older_than(table, quote_currency="USD", base_currency="EUR",
                                as_of=date(2025, 3, 7), max_age_days=7) == Decimal("1") / Decimal("1.25")


def test_empate_de_fecha_sigue_ganando_la_directa(db):
    _add(db, "EUR", "USD", "0.90", AYER, "directa")
    _add(db, "USD", "EUR", "1.20", AYER, "inversa")
    found = SVC.rate_with_provenance(db, quote_currency="USD", base_currency="EUR", as_of=HOY)
    assert (found["rate"], found["direction"]) == (Decimal("0.90"), "direct")
    table = SVC.fx_table(db, currencies={"USD"}, base_currency="EUR", as_of_max=HOY)
    assert SVC.rate_from_table(table, quote_currency="USD", base_currency="EUR", as_of=HOY) == Decimal("0.90")
    assert _fx_rate_with_date(table, quote_currency="USD", base_currency="EUR", as_of=HOY) == (AYER, Decimal("0.90"))
    assert _rate_not_older_than(table, quote_currency="USD", base_currency="EUR",
                                as_of=HOY, max_age_days=7) == Decimal("0.90")


def test_nunca_un_tipo_futuro_aunque_sea_el_mas_reciente(db):
    _add(db, "EUR", "USD", "0.90", VIEJA, "directa")
    _add(db, "USD", "EUR", "2", date(2026, 12, 1), "futura")
    found = SVC.rate_with_provenance(db, quote_currency="USD", base_currency="EUR", as_of=HOY)
    assert (found["rate"], found["direction"]) == (Decimal("0.90"), "direct")
    table = SVC.fx_table(db, currencies={"USD"}, base_currency="EUR", as_of_max=date(2026, 12, 31))
    assert SVC.rate_from_table(table, quote_currency="USD", base_currency="EUR", as_of=HOY) == Decimal("0.90")


def test_subunidad_aplica_el_divisor_tambien_con_la_inversa_fresca(db):
    _add(db, "EUR", "GBP", "1.10", VIEJA, "vieja")
    _add(db, "GBP", "EUR", "0.85", AYER, "ECB")
    esperado = Decimal("1") / Decimal("0.85") / 100
    found = SVC.rate_with_provenance(db, quote_currency="GBp", base_currency="EUR", as_of=HOY)
    assert found["rate"] == esperado and found["rate_date"] == AYER
    table = SVC.fx_table(db, currencies={"GBp"}, base_currency="EUR", as_of_max=HOY)
    assert SVC.rate_from_table(table, quote_currency="GBp", base_currency="EUR", as_of=HOY) == esperado
