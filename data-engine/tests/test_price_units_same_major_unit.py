"""price_units: cierre en peniques (GBp) de una empresa que reporta en libras (GBP).

Encontrado con mutation testing (mutmut, ronda 2): ``close_in_company_currency``
no tenia ningun test en su lista y, al escribirlos, aparecio esto. Con la
cotizacion en ``GBp`` y ``Company.currency = "GBP"`` (Tesco, Unilever, BP...)
la funcion veia "misma divisa principal" y devolvia los peniques tal cual: el
market cap derivado y el PER salian x100. La conversion de unidad dentro de la
misma divisa es exacta (sin FX), igual que ya hace ``price_in_currency``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import FinancialFact, FXRate
from app.services.derived_market_cap_service import refresh_derived_market_cap
from app.services.price_units import close_in_company_currency, listing_price
from tests.test_lse_paris_quote_currency import (  # noqa: F401  (fixture db)
    TODAY,
    _close,
    _company,
    _shares,
    db,
)

DAY = date(2026, 10, 27)


def _co(ticker: str, currency: str | None):
    return SimpleNamespace(ticker=ticker, currency=currency)


# --- el bug: GBp contra cuentas en GBP --------------------------------------


def test_market_cap_derivado_de_peniques_con_cuentas_en_libras(db):
    tsco = _company(db, ticker="TSCO", currency="GBP")
    day = TODAY - timedelta(days=1)
    _close(db, tsco, day, "250.5", "GBp")
    _shares(db, tsco, "7000000000")
    db.flush()
    result = refresh_derived_market_cap(db, tsco, today=TODAY)
    assert result["status"] == "ok"
    assert result["currency"] == "GBP"
    # 250,5 peniques = 2,505 GBP; x 7.000 M acciones = 17.535 M GBP (no 1,75 B).
    assert result["market_cap"] == pytest.approx(2.505 * 7_000_000_000, rel=1e-9)


def test_per_de_la_watchlist_con_peniques_y_eps_en_libras(db):
    from app.api.routes.watchlist import watchlist_metrics

    tsco = _company(db, ticker="TSCO", currency="GBP")
    day = TODAY - timedelta(days=1)
    _close(db, tsco, day, "250.5", "GBp")
    db.add(FinancialFact(
        company_id=tsco.id, metric="eps_diluted", value=Decimal("0.20"), unit="GBP/share",
        period=f"{TODAY.year - 1}-12-31:FY", fiscal_year=TODAY.year - 1, fiscal_quarter="FY",
        source_type="ESEF", is_reported=True, tenant_id=1,
    ))
    db.commit()
    out = watchlist_metrics("TSCO", db=db)
    # 2,505 GBP / 0,20 GBP = 12,5x (no 1.252x).
    assert out["per"] == pytest.approx(2.505 / 0.20, rel=1e-6)


@pytest.mark.parametrize(
    ("quote", "company", "expected"),
    [
        ("GBp", "GBP", Decimal("2.505")),     # peniques -> libras
        ("GBX", "GBP", Decimal("2.505")),     # alias de peniques
        ("GBP", "GBX", Decimal("25050")),     # libras -> peniques
        ("GBp", "GBX", Decimal("250.5")),     # misma unidad
        ("ZAc", "ZAR", Decimal("2.505")),     # centavos sudafricanos
        ("usd", "USD", Decimal("250.5")),     # mayusculas no importan
    ],
)
def test_misma_divisa_principal_convierte_la_unidad_sin_fx(quote, company, expected):
    # db=None: con la misma divisa principal no hay consulta de FX.
    got = close_in_company_currency(
        None, Decimal("250.5"), quote_currency=quote, company=_co("X.L", company), on=DAY,
    )
    assert got == expected


# --- resto del contrato (supervivientes de mutmut) --------------------------


@pytest.mark.parametrize(
    ("quote", "company"),
    [(None, "USD"), ("", "USD"), ("GBp", None), ("GBp", "")],
)
def test_sin_divisa_conocida_devuelve_el_cierre_tal_cual(quote, company):
    got = close_in_company_currency(
        None, Decimal("250.5"), quote_currency=quote, company=_co("X", company), on=DAY,
    )
    assert got == Decimal("250.5")


def test_divisa_distinta_usa_fx_y_respeta_las_subunidades(db):
    # 1 GBP = 1,30 USD (base USD, quote GBP: importe_quote x rate = importe_base).
    db.add(FXRate(base_currency="USD", quote_currency="GBP", rate=Decimal("1.30"),
                  rate_date=DAY, source="test", tenant_id=1))
    db.flush()
    usd = close_in_company_currency(
        db, Decimal("250.5"), quote_currency="GBp", company=_co("X.L", "USD"), on=DAY,
    )
    assert usd == pytest.approx(Decimal("2.505") * Decimal("1.30"))
    # Cuentas en una subunidad: el resultado va en esa subunidad (x100).
    db.add(FXRate(base_currency="GBP", quote_currency="USD", rate=Decimal("0.80"),
                  rate_date=DAY, source="test", tenant_id=1))
    db.flush()
    pence = close_in_company_currency(
        db, Decimal("10"), quote_currency="USD", company=_co("X", "GBX"), on=DAY,
    )
    assert pence is not None
    assert pence == pytest.approx(Decimal("10") * Decimal("0.80") * 100, rel=Decimal("0.02"))


def test_divisa_distinta_sin_tipo_es_nd(db):
    got = close_in_company_currency(
        db, Decimal("250.5"), quote_currency="GBp", company=_co("X.L", "USD"), on=DAY,
    )
    assert got is None


# --- listing_price -----------------------------------------------------------


def test_listing_price_misma_divisa_que_el_listado():
    # SHEL.L con cuentas en USD: el listado es GBP; GBp -> GBP sin FX.
    assert listing_price(
        Decimal("3927.5"), quote_currency="GBp", company=_co("SHEL.L", "USD"),
    ) == (Decimal("39.275"), "GBP")
    assert listing_price(
        Decimal("12.5"), quote_currency="EUR", company=_co("MC.PA", "EUR"),
    ) == (Decimal("12.5"), "EUR")


def test_listing_price_divisa_de_la_cotizacion_distinta_del_listado():
    # Linea en USD de un listado de Londres: se queda en USD (sin FX).
    assert listing_price(
        Decimal("51.2"), quote_currency="usd", company=_co("SMSN.L", "KRW"),
    ) == (Decimal("51.2"), "USD")
    # Subunidad distinta del listado: a su divisa principal.
    assert listing_price(
        Decimal("250"), quote_currency="ZAc", company=_co("NPN", "USD"),
    ) == (Decimal("2.5"), "ZAR")


def test_listing_price_sin_divisa_de_cotizacion():
    # Legacy en un listado de peniques: no se puede saber la unidad -> None.
    assert listing_price(Decimal("3927.5"), quote_currency=None, company=_co("SHEL.L", "USD")) is None
    assert listing_price(Decimal("3927.5"), quote_currency="", company=_co("SHEL.L", "USD")) is None
    # Legacy en un listado de divisa principal que coincide: vale.
    assert listing_price(
        Decimal("180"), quote_currency=None, company=_co("AAPL", "USD"),
    ) == (Decimal("180"), "USD")
