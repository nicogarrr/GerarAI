"""Presentación en español natural de fechas y fuentes para prosa visible.

La prosa (chat, descripciones) no enseña ISO crudo ni slugs internos
(visto en prod con AAPL, 19-oct-2026: «(2026-10-18, Finnhub)» y «fuente
yahoo_finance_intraday»). Espejo de lib/research/source-display.ts del
front; ampliar las etiquetas solo con evidencia.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

_MADRID = ZoneInfo("Europe/Madrid")

MESES_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic")


def fecha_es(value) -> str:
    """«18 oct 2026», la misma forma corta que usa el front (23 sept 2026).
    Acepta date/datetime o texto ISO («2026-10-18»), que es como guardan
    algunos modelos la fecha (p. ej. InsiderTransaction.tx_date). None → «N/D»."""
    if value is None:
        return "N/D"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            # Texto no ISO (p. ej. una fecha ya redactada por la fuente): se
            # devuelve tal cual, nunca se rompe la respuesta por formato.
            return value
    if isinstance(value, datetime):
        # Un instante se muestra en el día de Madrid: entre 00:00 y 01:00/02:00
        # (CET/CEST) la fecha UTC aún es «ayer». Naive = UTC (convención de BD).
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(_MADRID).date()
    return f"{value.day} {MESES_ES[value.month - 1]} {value.year}"


SOURCE_LABELS = {
    "finnhub": "Finnhub",
    "fmp": "FMP",
    "yahoo": "Yahoo Finance",
    "yahoo_finance": "Yahoo Finance",
    "yahoo_finance_intraday": "Yahoo Finance · intradía",
    "yahoo_fundamentals": "Yahoo Finance (fuente no oficial)",
    "google_news": "Google News",
    "sec": "SEC EDGAR",
    "gdelt": "GDELT",
}


def source_label(source: str | None) -> str:
    """Nombre legible de la fuente; nunca el slug crudo en prosa."""
    if not source:
        return "fuente no registrada"
    return SOURCE_LABELS.get(source, source.replace("_", " "))
