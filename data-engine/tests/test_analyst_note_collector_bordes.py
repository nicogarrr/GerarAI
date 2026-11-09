"""analyst_note_collector: remate de _fetch_yahoo_sync (316-346) con yfinance falso.

El Ticker falso sirve upgrades/history y fast_info, asi que la llamada a
app.services.analyst_targets_service._fetch_currency_and_type (import local en
la funcion) corre REAL sobre el mismo modulo falso: sin red ni Yahoo.

NO prueba (declarado, razon verificada):
- 227-228 (except ValueError en numbers_in): inalcanzable con _NUMBER_RE
  (digitos y comas con un unico punto decimal opcional) — tras quitar comas
  siempre queda un float parseable; fuzz con '1,,2', '1,2,3,', digitos
  Unicode ('１２３', '١٢٣') y un numero de 300 digitos: todos parsean.
- 392 (continue por fecha None en news_evidence): inalcanzable por la via
  publica — la query filtra NewsEvent.date >= since (NULL no pasa) y SQLite
  devuelve datetime; _as_date(datetime) nunca devuelve None (leido).
- 515-517 (_default_reasoner): factoria de una linea que importa
  app.services.expert_team.service.provider_reasoner — zona de valoracion,
  fuera de territorio (solo tests aqui, y no de esa zona).
"""
from __future__ import annotations

import sys
import types
from datetime import date, datetime

import app.services.analyst_note_collector as col


class _Frame:
    """Superficie minima de un DataFrame: len + iterrows con items .get."""

    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def iterrows(self):
        return iter(self._rows)


def _yfinance_falso(monkeypatch, *, upgrades, history_rows, fast_info):
    llamadas = {"ticker": [], "history": []}

    class _Ticker:
        def __init__(self, symbol):
            llamadas["ticker"].append(symbol)
            self.upgrades_downgrades = upgrades
            self.fast_info = fast_info

        def history(self, period=None, auto_adjust=None):
            llamadas["history"].append((period, auto_adjust))
            return _Frame(history_rows)

    modulo = types.ModuleType("yfinance")
    modulo.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", modulo)
    return llamadas


def test_fetch_yahoo_sync_mapea_registros_cierres_y_declarados(monkeypatch):
    """316-346 con datos: records del frame, closes positivos con fecha y
    divisa/tipo declarados por el _fetch_currency_and_type real."""
    upgrades = _Frame([
        (datetime(2026, 11, 3), {
            "Firm": "Barclays", "ToGrade": "Overweight",
            "FromGrade": "Equal Weight", "Action": "up",
            "priceTargetAction": "raises", "currentPriceTarget": 273.0,
            "priorPriceTarget": 265.0,
        }),
    ])
    llamadas = _yfinance_falso(
        monkeypatch,
        upgrades=upgrades,
        history_rows=[
            (datetime(2026, 11, 4), {"Close": 268.5}),
            (datetime(2026, 11, 3), {"Close": -1.0}),  # no positivo: descartado
            (datetime(2026, 11, 2), {"Close": None}),  # sin cierre: descartado
        ],
        fast_info={"currency": "USD", "quoteType": "EQUITY"},
    )

    out = col._fetch_yahoo_sync("PLTR")

    assert llamadas == {"ticker": ["PLTR", "PLTR"], "history": [("2y", False)]}
    assert out["records"] == [{
        "date": datetime(2026, 11, 3), "firm": "Barclays",
        "to_grade": "Overweight", "from_grade": "Equal Weight",
        "action": "up", "price_target_action": "raises",
        "price_target": 273.0, "prior_target": 265.0,
    }]
    assert out["closes"] == [(date(2026, 11, 4), 268.5)]
    assert out["currency"] == "USD"
    assert out["quote_type"] == "EQUITY"


def test_fetch_yahoo_sync_sin_datos_devuelve_listas_vacias(monkeypatch):
    """316-346 sin datos: frames vacios y fast_info sin claves -> todo vacio/None."""
    llamadas = _yfinance_falso(
        monkeypatch, upgrades=_Frame([]), history_rows=[], fast_info={},
    )

    out = col._fetch_yahoo_sync("PLTR")

    assert llamadas == {"ticker": ["PLTR", "PLTR"], "history": [("2y", False)]}
    assert out == {"records": [], "closes": [], "currency": None, "quote_type": None}
