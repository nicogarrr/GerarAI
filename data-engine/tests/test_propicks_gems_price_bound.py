"""find_gems: la lectura de precios acota la ventana (7 dias), no el historico.

Las gemas descartan cualquier precio con mas de 7 dias, pero la consulta
traia TODO el historico de cada empresa (miles de barras) para quedarse
con la ultima. La ventana en SQL lee como mucho 7 dias por empresa y el
resultado es identico: un cierre viejo nunca se usa.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event

from app.models import MarketPrice
from app.services.propicks_funnel_service import run_funnel
from app.services.propicks_gems_service import find_gems
from tests.test_propicks_funnel import _company, _db, _fact, _five_good_years, _full_metrics


def test_gems_price_query_reads_only_the_fresh_window():
    today = date(2026, 10, 19)
    with _db() as db:
        c = _company("GEM")
        db.add(c)
        db.flush()
        _full_metrics(db, c)
        _five_good_years(db, c)
        _fact(db, c, "free_cash_flow", "150000000", 2025)
        _fact(db, c, "shares_diluted", "100000000", 2025)
        # 500 barras viejas (nunca usables: >7 dias) y una fresca.
        for back in range(8, 508):
            db.add(MarketPrice(company_id=c.id, date=today - timedelta(days=back),
                               close=Decimal("9999"), volume=1000))
        db.add(MarketPrice(company_id=c.id, date=today - timedelta(days=1),
                           close=Decimal("10"), volume=1000))
        db.commit()
        results, _stats = run_funnel(db, top_n=100)
        statements = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            if "FROM market_prices" in statement:
                statements.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", _count)
        try:
            gems = find_gems(db, results, today=today)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _count)
        assert gems, "la gema debe seguir saliendo con la barra fresca"
        assert gems[0].price == 10.0  # la barra fresca, nunca la vieja de 9999
        assert statements, "se esperaba la consulta de precios"
        # La cota de 7 dias viaja en SQL: sin ella se leen las 500 barras viejas.
        assert any("date >=" in stmt or "market_prices.date >=" in stmt for stmt in statements), \
            "la consulta de precios no acota la ventana de 7 dias"
