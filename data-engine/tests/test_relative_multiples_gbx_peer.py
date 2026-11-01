"""Multiplos relativos: precio de un par con la ficha en «GBX».

Una ficha de Londres creada solo con el ticker queda con divisa «GBX»
(``fill_default_currency``). El cierre en peniques se dejaba en peniques
(misma unidad que la ficha) frente a un EPS en libras: el PER de ese par
salia x100 y entraba en la mediana del grupo.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.valuation.engines.relative_multiples import _latest_price
from tests.test_lse_paris_quote_currency import (  # noqa: F401  (fixture db)
    TODAY,
    _close,
    _company,
    db,
)


@pytest.mark.parametrize("currency", ["GBX", "GBp", "GBP"])
def test_precio_del_par_en_libras(db, currency):
    peer = _company(db, ticker="TSCO.L", currency=currency)
    _close(db, peer, TODAY - timedelta(days=1), "250.5", "GBp")
    db.flush()
    price, _as_of = _latest_price(db, peer)
    assert price == pytest.approx(2.505)
