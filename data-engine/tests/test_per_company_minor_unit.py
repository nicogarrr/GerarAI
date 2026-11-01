"""PER con la ficha guardada en subunidad («GBX» / «GBp») y EPS en libras.

Una ficha creada solo con el ticker (alerta, Propicks) y sin divisa del
proveedor queda con ``Company.currency = "GBX"`` (``fill_default_currency``:
sufijo .L -> GBX). El cierre en peniques se dejaba en peniques (misma unidad
que la ficha) y se comparaba con un EPS ESEF en GBP: con «GBX» el PER salia
N/D («mezclar divisas») y con «GBp» (``.upper()`` -> GBP) salia x100.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import FinancialFact
from app.services.screener_fundamentals import load_screener_ratios
from tests.test_lse_paris_quote_currency import (  # noqa: F401  (fixture db)
    TODAY,
    _close,
    _company,
    db,
)


def _setup(db, currency):
    tsco = _company(db, ticker="TSCO", currency=currency)
    _close(db, tsco, TODAY - timedelta(days=1), "250.5", "GBp")
    db.add(FinancialFact(
        company_id=tsco.id, metric="eps_diluted", value=Decimal("0.20"), unit="GBP/share",
        period=f"{TODAY.year - 1}-12-31:FY", fiscal_year=TODAY.year - 1, fiscal_quarter="FY",
        source_type="ESEF", is_reported=True, tenant_id=1,
    ))
    db.commit()
    return tsco


@pytest.mark.parametrize("currency", ["GBX", "GBp"])
def test_per_de_la_watchlist_con_ficha_en_peniques(db, currency):
    from app.api.routes.watchlist import watchlist_metrics

    _setup(db, currency)
    out = watchlist_metrics("TSCO", db=db)
    # 2,505 GBP / 0,20 GBP = 12,5x (no N/D ni 1.252x).
    assert out["per"] == pytest.approx(2.505 / 0.20, rel=1e-6)


@pytest.mark.parametrize("currency", ["GBX", "GBp"])
def test_per_del_screener_con_ficha_en_peniques(db, currency):
    _setup(db, currency)
    out = load_screener_ratios(db, {"TSCO"}, today=TODAY)
    assert out["TSCO"]["pe"] == pytest.approx(2.505 / 0.20, rel=1e-6)
