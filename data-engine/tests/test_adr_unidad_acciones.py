"""ADR: la TIR trabaja en la unidad que cotiza (el ADS), sin mezclar ordinarias y ADS.

Antes (main): TSM tenía 25.930 M de acciones ORDINARIAS en sus 20-F (SEC) y 5.186 M de ADS del agregador
para 2025 (1 ADS = 5 ordinarias). La serie caía un 80 % en un año (recompras fantasma) y el precio del
ADS se multiplicaba por ordinarias (capitalización ×5). Regla general: cualquier emisor con ratio ADR.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import shareholder_irr_service as svc
from app.valuation.share_units import count_basis


def _c(v, year, metric, source="SEC", unit="shares"):
    return {"value": v * 1_000_000, "unit": unit, "period": f"{year}-12-31:FY", "metric": metric,
            "source_type": source}


def _run(ticker, sec_shares, yahoo_shares, sec_eps=None, factor_tags=None):
    annual = {"shares_diluted": {2023: _c(sec_shares, 2023, "shares_diluted"),
                                 2024: _c(sec_shares, 2024, "shares_diluted"),
                                 2025: _c(yahoo_shares, 2025, "shares_diluted", "YAHOO_FUNDAMENTALS")}}
    if sec_eps is not None:
        annual["eps_diluted"] = {2024: {"value": sec_eps, "unit": "USD/share", "period": "2024-12-31:FY",
                                        "source_type": "SEC"}}
    point = {"shares_outstanding": _c(sec_shares, 2026, "shares_outstanding")}
    warnings: list[str] = []
    cites: dict = {}
    company = SimpleNamespace(ticker=ticker, factor_tags=factor_tags or [])
    svc._to_listed_share_basis(company, annual, point, warnings, cites)
    shares = {y: c["value"] / 1e6 for y, c in annual["shares_diluted"].items()}
    return shares, annual, point, warnings, cites


@pytest.mark.parametrize("ticker,ratio,sec,yahoo", [
    ("TSM", 5, 25_930.0, 5_186.1),   # 20-F: ordinarias; agregador: ADS
    ("BABA", 8, 19_200.0, 2_400.0),
    ("TM", 10, 13_100.0, 1_310.0),
])
def test_serie_en_ads_sin_saltos(ticker, ratio, sec, yahoo):
    shares, annual, point, warnings, cites = _run(ticker, sec, yahoo, sec_eps=10.0)
    assert shares[2023] == pytest.approx(sec / ratio)
    assert shares[2025] == pytest.approx(yahoo)          # ya estaba en ADS
    assert point["shares_outstanding"]["value"] / 1e6 == pytest.approx(sec / ratio)
    assert annual["eps_diluted"][2024]["value"] == pytest.approx(10.0 * ratio)
    assert cites["adr_share_basis"]["ordinary_per_ads"] == ratio
    assert any("ADS" in w for w in warnings)


def test_etiqueta_adr_manda_sobre_la_tabla():
    shares, *_ = _run("XYZ", 3_000.0, 1_000.0, factor_tags=["adr:3"])
    assert shares[2024] == pytest.approx(1_000.0) and shares[2025] == pytest.approx(1_000.0)


def test_sin_ratio_no_cambia_nada():
    shares, _a, _p, warnings, cites = _run("AAPL", 15_400.0, 15_300.0)
    assert shares == {2023: 15_400.0, 2024: 15_400.0, 2025: 15_300.0}
    assert "adr_share_basis" not in cites and not warnings


def test_cifra_que_no_cuadra_no_se_toca():
    shares, *_rest, cites = _run("TSM", 25_930.0, 12_000.0)
    assert shares[2025] == pytest.approx(12_000.0)
    assert cites["adr_share_basis"]["unresolved"] == ["shares_diluted 2025"]


def test_count_basis():
    assert count_basis(5_186.0, 25_930.0, 5) == "ads"
    assert count_basis(25_000.0, 25_930.0, 5) == "ordinary"
    assert count_basis(12_000.0, 25_930.0, 5) is None
    assert count_basis(100.0, 100.0, None) is None
