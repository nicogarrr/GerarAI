"""Aviso DCA en un valor poco volatil: el correo lo dice (gerarai-dcavalor1, 7-nov-2026).

En valores con volatilidad anualizada < 25 % los niveles 2X-4X no han rendido mas que 1X a 12 meses
(491 valores del S&P 500, 1996-2012 y 2013-2025). El aviso no cambia de nivel ni deja de enviarse:
anade una linea para que la senal no se lea como «compra mas» cuando no lo ha sido.
"""

from app.services.dca_alert_copy import email_content, low_volatility_note, message_text

_LEVELS = {"4X DCA": 4, "3X DCA": 3, "2X DCA": 2, "1X DCA": 1, "RECORTE LIGERO": -1}


def _dca(level_label="3X DCA", vol=0.18, direction="up"):
    return {
        "symbol": "CPT",
        "level": _LEVELS[level_label],
        "label": level_label,
        "previous_label": "1X DCA",
        "zone": "Zona de compra fuerte",
        "status": "confirmed",
        "direction": direction,
        "signal_date": "2026-10-31",
        "close": 101.5,
        "currency": "USD",
        "color": "#68F60F",
        "fg": "#000000",
        "metrics": {"signal": "combined", "drawdown": 0.27, "vol": vol},
        "level_prices": {},
        "sources": ["watchlist"],
    }


def test_low_volatility_buy_level_adds_the_note_es_and_en():
    es = low_volatility_note(_dca())
    assert es == (
        "Valor poco volátil (vol 18,0 % anual): en valores así, 2X–4X no han rendido más que 1X "
        "a 12 meses (backtest 1996–2025). En el reparto del plan pesa como 1X."
    )
    en = low_volatility_note(_dca(), "en")
    assert en == (
        "Low-volatility stock (vol 18.0% a year): in stocks like this, 2X–4X have not returned more "
        "than 1X over 12 months (backtest 1996–2025). The plan split weights it as 1X."
    )
    assert es in message_text(_dca())
    html = email_content(_dca()).html
    assert "Valor poco volátil (vol 18,0 % anual)" in html
    assert "#68F60F" in html  # mismo badge y color de zona


def test_no_note_for_volatile_1x_trim_drop_or_unknown_vol():
    assert low_volatility_note(_dca(vol=0.42)) is None
    assert low_volatility_note(_dca(vol=0.25)) is None
    assert low_volatility_note(_dca(level_label="1X DCA")) is None
    assert low_volatility_note(_dca(level_label="RECORTE LIGERO")) is None
    assert low_volatility_note(_dca(vol=None)) is None
    assert low_volatility_note(_dca(vol="n/d")) is None
    # Una bajada de nivel es informativa: no se le anade la nota.
    assert low_volatility_note(_dca(direction="down")) is None
    text = message_text(_dca(vol=0.42))
    assert "poco volátil" not in text


def test_threshold_matches_the_plan_split():
    from app.services import dca_alert_copy, plan_contribution_split

    assert dca_alert_copy.LOW_VOLATILITY_THRESHOLD == plan_contribution_split.LOW_VOLATILITY_THRESHOLD
