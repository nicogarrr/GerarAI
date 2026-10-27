"""Tabla de ratios ADR como respaldo de la etiqueta ``adr:N``."""

from __future__ import annotations

import pytest

from app.models import Company
from app.valuation.adr_ratios import ADR_RATIOS, table_adr_ratio
from app.valuation.engines.base import adr_comparable_price, adr_ratio, is_adr_without_ratio


def _company(ticker: str, tags: list[str] | None = None) -> Company:
    return Company(
        ticker=ticker,
        name=ticker,
        exchange="NYSE",
        currency="USD",
        company_type="standard",
        valuation_model="standard_dcf",
        factor_tags=tags or [],
    )


def test_baba_sin_etiqueta_usa_la_tabla() -> None:
    # Ficha creada por el enriquecimiento, sin "adr:8": antes, ratio None y el
    # valor por accion ordinaria se comparaba con el precio del ADR (x8).
    company = _company("BABA")
    assert adr_ratio(company) == 8.0
    assert not is_adr_without_ratio(company)


def test_tm_precio_por_accion_ordinaria() -> None:
    # Toyota: 1 ADS = 10 ordinarias desde el 1-oct-2021. A mano: 170 / 10 = 17.
    comparable, ratio = adr_comparable_price(_company("TM"), 170.0)
    assert ratio == 10.0
    assert comparable == pytest.approx(17.0)


def test_la_etiqueta_manda_sobre_la_tabla() -> None:
    assert adr_ratio(_company("BABA", ["adr:4"])) == 4.0


def test_etiqueta_mal_formada_no_se_tapa_con_la_tabla() -> None:
    company = _company("BABA", ["adr:0"])
    assert adr_ratio(company) is None
    assert is_adr_without_ratio(company)


def test_etiqueta_adr_desnuda_se_completa_con_la_tabla() -> None:
    company = _company("TSM", ["adr"])
    assert adr_ratio(company) == 5.0
    assert not is_adr_without_ratio(company)


def test_no_adr() -> None:
    company = _company("AAPL")
    assert adr_ratio(company) is None
    assert not is_adr_without_ratio(company)
    assert adr_comparable_price(company, 200.0) == (200.0, None)


def test_tabla_con_fuente_y_ratio_positivo() -> None:
    for ticker, row in ADR_RATIOS.items():
        assert row.ordinary_per_adr > 0, ticker
        assert row.source.strip(), ticker
        assert table_adr_ratio(ticker.lower()) is row
