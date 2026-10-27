"""Tickers que el usuario nombra y GerarAI no tiene: decirlo, no inventar.

Prueba real (2026-10-27): «¿qué opinas de TSLAA?» llegaba al generador libre,
que contestaba «TSLAA es un ticker que suele asociarse con Tesla en su versión
de acciones preferentes…»: una afirmación inventada sobre un ticker que no
existe. Si la pregunta nombra en MAYÚSCULAS algo con forma de ticker que no
está en el maestro de empresas, el Cerebro lo dice y no opina sin datos.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

# Siglas habituales en una pregunta de inversión que NO son tickers.
_ACRONYMS = frozenset(
    ["IA", "AI", "PER", "PEG", "EPS", "BPA", "ROE", "ROA", "ROIC", "ROCE", "FCF", "DCF", "EV", "EBIT", "EBITDA", "ETF", "ETFS", "IPO", "OPA", "OPV", "CEO", "CFO", "CTO", "ADR", "ADRS", "ADS", "IRPF", "IVA", "PIB", "IPC", "BCE", "FED", "SEC", "FMP", "IBKR", "USD", "EUR", "GBP", "GBX", "JPY", "CNY", "HKD", "CHF", "CAD", "AUD", "EEUU", "EE", "UU", "UE", "USA", "UK", "TIR", "VAN", "WACC", "CAPEX", "OPEX", "SBC", "TTM", "YTD", "FY", "LTM", "DCA", "NAV", "PE", "PB", "PS", "MOS", "NYSE", "NASDAQ", "LSE", "BME", "IBEX", "MSCI", "LLM", "API", "PDF", "URL", "XIRR", "TWR", "CAGR", "OK", "SA", "SL", "AG", "NV", "PLC", "INC", "LTD", "CORP", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "GAAP", "IFRS", "KPI", "KPIS", "ARPU", "SAAS", "IT", "TAM", "SAM", "SOM", "MOAT", "FCFF", "FCFE", "DDM", "SOTP", "RSI", "MACD", "SMA", "EMA", "VIX", "ESG"]
)

# Algo con forma de ticker escrito en mayúsculas: 2-6 caracteres (letra
# inicial), con sufijo de mercado opcional («CGEO.L», «SAN.MC»).
_TICKER_TOKEN_RE = re.compile(r"(?<![\w.])([A-Z][A-Z0-9]{1,5}(?:\.[A-Z]{1,3})?)(?![\w])")


def unknown_ticker_mentions(
    question: str, known_tickers: Iterable[str], *, ignore_spans: Iterable[tuple[int, int]] = ()
) -> list[str]:
    """Tickers en mayúsculas de la pregunta que no están en el maestro.

    Una pregunta escrita entera en mayúsculas no cuenta (no hay forma de
    distinguir un ticker de una palabra). Se respeta el orden de aparición.
    ``ignore_spans`` son tramos ocupados por el nombre de una empresa
    conocida: su primera palabra en mayúsculas no es un ticker.
    """
    text = question or ""
    if not any(ch.islower() for ch in text):
        return []
    known = {t.upper() for t in known_tickers}
    spans = list(ignore_spans)
    out: list[str] = []
    for match in _TICKER_TOKEN_RE.finditer(text):
        token = match.group(1)
        if any(s <= match.start(1) and match.end(1) <= e for s, e in spans):
            continue  # parte del nombre de una empresa conocida («AST SpaceMobile»)
        base = token.split(".")[0]
        if token in known or base in _ACRONYMS or token in _ACRONYMS:
            continue
        if token not in out:
            out.append(token)
    return out


def unknown_ticker_answer(tickers: list[str], known_tickers: Iterable[str]) -> str:
    """Respuesta honesta en español, con sugerencia si hay uno parecido."""
    known = sorted({t.upper() for t in known_tickers})
    names = ", ".join(f"«{t}»" for t in tickers)
    plural = len(tickers) > 1
    head = (
        f"No tengo {names} entre las empresas de GerarAI, así que no "
        f"{'puedo opinar sobre ellos' if plural else 'puedo opinar sobre él'} sin inventar."
    )
    hints = []
    for ticker in tickers:
        close = difflib.get_close_matches(ticker, known, n=1, cutoff=0.75)
        if close:
            hints.append(f"¿quizá {close[0]} en vez de {ticker}?")
    hint = f" Revisa cómo está escrito ({' '.join(hints)})." if hints else " Revisa cómo está escrito."
    first = tickers[0]
    tail = (
        f" Si es un ticker real, ábrelo en la ficha (/research/{first}) para cargar sus datos "
        "y vuelve a preguntarme."
    )
    return head + hint + tail
