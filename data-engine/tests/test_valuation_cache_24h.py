"""Cache de valoraciones 24h: una reejecucion dentro de la ventana no
recomputa (ni refetchea) empresas con metricas frescas del periodo.

Medido: reejecucion sobre universo ya hecho = N llamadas a yfinance +
N a Finnhub antes; 0 despues (solo trabaja lo obsoleto o nuevo).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import update

from app.models import CalculatedMetric
from app.services.valuation_metrics_service import refresh_valuation_metrics
from tests.test_propicks_prices import _db
from tests.test_valuation_metrics import _seed_pb

AS_OF = date(2026, 10, 27)
EVENTS = [{"date": (AS_OF - timedelta(days=100)).isoformat(), "amount": "0.8"}]


def _fetchers(llamadas):
    def div(symbol):
        llamadas["div"] += 1
        return EVENTS

    def finn(ticker):
        llamadas["finn"] += 1
        return None

    return div, finn


def test_reejecucion_en_24h_no_llama_a_fuentes_ni_recomputa():
    db = _db()
    _seed_pb(db, "AAA")
    db.commit()
    llamadas = {"div": 0, "finn": 0}
    div, finn = _fetchers(llamadas)

    primera = refresh_valuation_metrics(
        db, as_of=AS_OF, dividend_fetcher=div, finnhub_yield_fetcher=finn
    )
    assert primera["companies"] == 1
    assert primera["companies_skipped_fresh_24h"] == 0
    assert llamadas == {"div": 1, "finn": 1}

    segunda = refresh_valuation_metrics(
        db, as_of=AS_OF, dividend_fetcher=div, finnhub_yield_fetcher=finn
    )
    # Reejecucion dentro de 24h: la empresa fresca se salta ENTERA.
    assert segunda["companies"] == 1
    assert segunda["companies_skipped_fresh_24h"] == 1
    assert llamadas == {"div": 1, "finn": 1}, "la reejecucion gasto llamadas externas"


def test_empresa_obsoleta_si_se_recomputa():
    db = _db()
    _seed_pb(db, "AAA")
    db.commit()
    llamadas = {"div": 0, "finn": 0}
    div, finn = _fetchers(llamadas)
    refresh_valuation_metrics(db, as_of=AS_OF, dividend_fetcher=div, finnhub_yield_fetcher=finn)

    # Envejece las filas por encima de la ventana: la empresa vuelve a trabajar.
    db.execute(
        update(CalculatedMetric).values(updated_at=datetime.now(UTC) - timedelta(hours=25))
    )
    db.commit()

    tercera = refresh_valuation_metrics(
        db, as_of=AS_OF, dividend_fetcher=div, finnhub_yield_fetcher=finn
    )
    assert tercera["companies_skipped_fresh_24h"] == 0
    assert llamadas == {"div": 2, "finn": 2}


def test_parcial_fresco_sin_yield_se_recomputa():
    """Bug del piloto: frescura exigia CUALQUIER metrica reciente; un ticker
    con P/B fresco pero yield ausente (la fuente de dividendos fallo) se
    saltaba 24h entero. Ahora la frescura exige el conjunto completo."""
    db = _db()
    _seed_pb(db, "AAA")
    db.commit()
    llamadas = {"div": 0, "finn": 0}

    def div_falla(symbol):
        llamadas["div"] += 1
        return None  # fuente de dividendos caida: no se escribe fila de yield

    def finn(ticker):
        llamadas["finn"] += 1
        return None

    primera = refresh_valuation_metrics(
        db, as_of=AS_OF, dividend_fetcher=div_falla, finnhub_yield_fetcher=finn
    )
    assert primera["companies_skipped_fresh_24h"] == 0
    # P/B quedo escrito y fresco; yield NO (fuente fallo).
    segunda = refresh_valuation_metrics(
        db, as_of=AS_OF, dividend_fetcher=div_falla, finnhub_yield_fetcher=finn
    )
    # Parcial != fresca: se recomputa y se reintenta la fuente de dividendos
    # (con la fuente en None el flujo sale antes del contraste Finnhub).
    assert segunda["companies_skipped_fresh_24h"] == 0
    assert llamadas == {"div": 2, "finn": 0}
