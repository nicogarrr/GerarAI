"""Aviso DCA de zona de recorte: nota informativa, sin verbo de accion (gerarai-dcavalor3, 7-nov-2026).

Backtest (491 valores del S&P 500, nivel confirmado nico-v2, 12 meses frente al SPY): los valores
que entraron en recorte rindieron de media MAS que 1X en 1996-2012 (+46/+47 frente a +6,7 puntos) y
2013-2025 (+59/+60 frente a +2,0). El aviso no dice «recorta»: informa y recuerda que el plan no les
da dinero nuevo. Las compras y las bajadas de nivel no cambian.
"""

from app.services.dca_alert_copy import email_content, message_text, title, trim_note


def _dca(level=-1, label="RECORTE LIGERO", direction="up", zone="Zona de recorte ligero"):
    return {
        "symbol": "NVDA",
        "level": level,
        "label": label,
        "previous_label": "1X DCA",
        "zone": zone,
        "status": "confirmed",
        "direction": direction,
        "signal_date": "2026-10-31",
        "close": 201.5,
        "currency": "USD",
        "color": "#FF9F0A",
        "fg": "#000000",
        "metrics": {"signal": "trim", "rsi": 81.0},
        "level_prices": {},
        "sources": ["watchlist"],
    }


def test_trim_alert_is_an_informative_note_es_and_en():
    assert title(_dca()) == "NVDA: zona RECORTE LIGERO (aviso informativo)"
    assert title(_dca(), "en") == "NVDA: LIGHT TRIM zone (for information)"
    es = trim_note(_dca(level=-2, label="RECORTE FUERTE"))
    assert es is not None and es.startswith("Aviso informativo, no una orden")
    assert "batieron de media al S&P 500" in es
    en = trim_note(_dca(), "en")
    assert en is not None and en.startswith("For information, not an instruction")


def test_trim_note_reaches_text_and_email():
    content = email_content(_dca())
    assert content.subject.startswith("NVDA: zona RECORTE LIGERO (aviso informativo)")
    assert "Aviso informativo, no una orden" in content.text
    assert "Aviso informativo, no una orden" in content.html
    assert "For information, not an instruction" in message_text(_dca(), "en")


def test_buy_levels_and_drops_unchanged():
    buy = _dca(level=3, label="3X DCA", zone="Zona de compra fuerte")
    assert trim_note(buy) is None
    assert title(buy) == "NVDA entró en 3X DCA"
    drop = _dca(direction="down")
    assert trim_note(drop) is None
    assert title(drop) == "NVDA baja a RECORTE LIGERO (desde 1X DCA)"
