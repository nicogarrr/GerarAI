"""Las consultas de request están ACOTADAS: no barre la tabla entera.

Tres sitios leían historia completa sólo para usar las últimas filas:

* `market_refresh_service` — `select(MarketPrice).where(company_id.in_(...))`
  sin `.limit()` ni suelo de fecha: materializaba TODAS las barras diarias
  jamás guardadas de cada compañía en cartera para leer la más reciente.
* `routes/market.py` `GET /api/market/movers` — `row_number() over (partition by
  company_id order by date desc)` sobre la tabla `market_prices` ENTERA antes de
  filtrar `rn <= 2`. El `limit` de salida (1..25) no acota lo que se lee.
* `screener_service.run()` — la tabla `financial_facts` completa (sin filtro de
  métrica, sin filtro de compañía, sin límite) una vez por pantalla guardada en
  cada refresh.

Mismos resultados, menos filas leídas. Las aserciones miran el SQL realmente
emitido y, en paralelo, cuentan las filas que el screener carga en memoria.
"""

import asyncio
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.api.routes.market import market_movers
from app.core.database import Base
from app.models import Company, FinancialFact, MarketPrice, Portfolio, Position, Tenant
from app.services.connectors.ecb import ECBRates
from app.services.market_refresh_service import MarketRefreshService
from app.services.screener_service import ScreenerService

AS_OF = date(2026, 9, 22)


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="NASDAQ",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="bounds", name="Bounds")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


@contextmanager
def _capture_sql(db: Session):
    """Statements actually emitted against this session's engine."""
    statements: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        yield statements
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)


# --- 1. /api/market/movers ---


def _seed_multi_year_prices(
    db: Session, company: Company, days: int, *, end: date = AS_OF
) -> None:
    """A long daily history for one company, ending on `end` (inclusive)."""
    start = end - timedelta(days=days - 1)
    for offset in range(days):
        day = start + timedelta(days=offset)
        db.add(
            MarketPrice(
                company_id=company.id,
                date=day,
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10") + offset,
                adj_close=Decimal("10") + offset,
                volume=1_000 + offset,
                source="yfinance",
            )
        )
    db.flush()


def test_movers_window_is_per_company_and_index_bounded(db: Session):
    company = _company("LONG")
    db.add(company)
    db.flush()
    # Cinco años de barras diarias, con el penúltimo cierre FUERA de
    # cualquier ventana global de dias: el contrato (dos ultimos cierres
    # por compania) exige que la variacion se calcule igual.
    _seed_multi_year_prices(db, company, days=1_800, end=AS_OF - timedelta(days=400))
    db.add(
        MarketPrice(
            company_id=company.id,
            date=AS_OF,
            close=Decimal("2000"),
            adj_close=Decimal("2000"),
            volume=9_000_000,
            source="yfinance",
        )
    )
    db.commit()

    statements = _capture_sql(db)
    with statements as captured:
        out = market_movers(db, 10)

    sql = " ".join(captured).lower()
    # Sin row_number sobre toda la historia: la ventana es por compania via
    # max(date) agregado (acotado por el indice company_id+date).
    assert "row_number()" not in sql, "la ventana vuelve a barrer toda la tabla"
    assert "max(market_prices.date)" in sql
    # El resultado es correcto con cinco anos de historia y hueco >10 dias:
    # la compania sigue en el universo y su variacion usa SUS dos ultimas
    # barras ((2000 - (10+1799)) / (10+1799)).
    assert out["universe"] == 1
    assert out["as_of"] == AS_OF.isoformat()
    gainer = out["gainers"][0]
    assert gainer["ticker"] == "LONG"
    assert gainer["change_pct"] is not None
    assert out["most_active"][0]["ticker"] == "LONG"


# --- 2. market_refresh: ultimo precio por compañía ---


class _FakePriceProvider:
    async def fetch(self, companies, *, as_of):
        return {}, []


class _FakeFXProvider:
    async def fetch(self, *, base_currency, quote_currencies):
        return ECBRates(
            rate_date=AS_OF, rates={currency: Decimal("1.1") for currency in quote_currencies}
        )


def test_refresh_latest_price_query_returns_one_row_per_company(db: Session):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = _company("HELD")
    db.add(company)
    db.flush()
    db.add(
        Position(
            company_id=company.id, quantity=Decimal("10"), currency="USD",
            market_price=Decimal("90"), market_value=Decimal("900"),
        )
    )
    _seed_multi_year_prices(db, company, days=1_800, end=AS_OF - timedelta(days=1))
    db.add(
        MarketPrice(
            company_id=company.id, date=AS_OF, close=Decimal("250"),
            adj_close=Decimal("250"), volume=1, source="yfinance",
        )
    )
    db.commit()

    statements = _capture_sql(db)
    with statements as captured:
        result = asyncio.run(
            MarketRefreshService(
                price_provider=_FakePriceProvider(), fx_provider=_FakeFXProvider()
            ).refresh(db, as_of=AS_OF)
        )

    latest = [
        s
        for s in captured
        if "latest_market_price" in s or ("row_number()" in s and "market_prices" in s)
    ]
    assert latest, "el ultimo precio por compañía debe acotarse con row_number() = 1"
    sql = " ".join(latest).lower()
    assert "row_number() over (partition by market_prices.company_id" in sql
    assert "rn = ?" in sql, "solo se materializa UNA fila por compañía"
    # Sin cambio de resultado: la revaloración usa el cierre más reciente.
    assert result["stages"][2]["updated"] == 1
    position = db.scalar(select(Position))
    assert position.market_price == Decimal("250")


# --- 3. screener: financial_facts filtrado y acotado ---


def _fact(db: Session, company: Company, metric: str, value: str, year: int) -> None:
    db.add(
        FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
            period=f"FY{year}", fiscal_year=year, fiscal_quarter="FY",
            source_type="sec_filing", confidence=Decimal("0.9"),
        )
    )


def test_screener_facts_query_is_filtered_and_capped(db: Session, monkeypatch):
    company = _company("SCR")
    db.add(company)
    db.flush()
    # 10 años de revenue (lo que la pantalla SÍ referencia) y 40 años de un
    # métrico que la pantalla NO referencia en absoluto.
    for year in range(2016, 2026):
        _fact(db, company, "revenue", str(100 + year), year)
    for year in range(1986, 2026):
        _fact(db, company, "unrelated_kpi", str(year), year)
    db.commit()

    loaded: list[int] = []
    original = ScreenerService._observations_from_rows

    def counting(self, calculated, facts):  # noqa: ANN001
        loaded.append(len(facts))
        return original(self, calculated, facts)

    monkeypatch.setattr(ScreenerService, "_observations_from_rows", counting)

    statements = _capture_sql(db)
    with statements as captured:
        response = ScreenerService().run(
            db, criteria=[{"left": "revenue", "operator": ">", "right": "0"}]
        )

    assert loaded == [10], (
        f"el screener cargo {loaded} filas de financial_facts; se esperaban 10 "
        "(solo revenue), no la tabla entera"
    )
    fact_sql = " ".join(s for s in captured if "financial_facts" in s).lower()
    assert "financial_facts.metric in" in fact_sql, (
        "la consulta de financial_facts no filtra por métrica"
    )
    assert "unrelated_kpi" not in fact_sql
    assert "row_number() over (partition by financial_facts.company_id" in fact_sql
    assert "rn <= ?" in fact_sql, "no hay tope de filas por (compañía, métrica)"
    # Mismo resultado con la acotación: el último hecho sigue siendo el valor actual.
    row = response["results"][0]
    assert row["matched"] is True
    assert row["criteria"][0]["left_value"] == "2125.000000"


def test_screener_facts_cap_does_not_change_results(db: Session):
    """Más de MAX_FACTS_PER_METRIC años: se recortan, y el resultado es el mismo.

    El recorte conserva los años recientes, así que la métrica derivada
    `revenue_cagr` (que necesita la métrica base `revenue` como hecho) se sigue
    calculando: el filtro por nombres referenciados no la pierde.
    """
    company = _company("DEEP")
    db.add(company)
    db.flush()
    for year in range(1960, 2026):
        _fact(db, company, "revenue", str(1000 + year * 10), year)
    db.commit()
    deep = ScreenerService.MAX_FACTS_PER_METRIC
    assert deep < 2026 - 1960, "el fixture debe superar el tope para que el recorte aplique"

    response = ScreenerService().run(
        db,
        criteria=[
            {"left": "revenue", "operator": ">", "right": "0"},
            {"left": "revenue_cagr", "operator": ">", "right": "0"},
        ],
    )
    row = response["results"][0]
    assert row["matched"] is True
    # La métrica derivada se evaluó de verdad, no se degradó a "missing".
    cagr = next(c for c in row["criteria"] if c["left"] == "revenue_cagr")
    assert cagr["passed"] is True
    assert float(cagr["left_value"]) > 0
    assert row["coverage_percent"] == 100.0
    assert row["missing_fields"] == []


# --- 4. Qué hecho gana cuando varios documentos autorizan el mismo año ---

# `financial_facts` no tiene restricción única en
# (tenant_id, company_id, metric, fiscal_year): varios documentos autorizan
# legítimamente el mismo año. La regla de deduplicación debe ser LA MISMA en los
# dos caminos que la consumen:
#
#   * el valor puntual (`_observations_from_rows` -> `setdefault` sobre la serie
#     ordenada) se quedaba con la fila de id MÁS ALTO (la más reciente);
#   * `_cagr` construía un dict por comprensión y se quedaba con la última
#     escritura, es decir la de id MÁS BAJO (la más ANTIGUA).
#
# Un emisor reestatado se cribaba con el revenue NUEVO mientras su revenue_cagr
# salía de la base VIEJA: el crecimiento quedaba sistemáticamente mal.
# Aquí la fila antigua se inserta primero y la nueva después (id mayor).


def test_cagr_and_point_value_use_the_same_restatement(db: Session):
    company = _company("RESTATED")
    db.add(company)
    db.flush()
    # Ingesta vieja: revenue 2020 = 100, 2025 = 200 (CAGR = 2^(1/5) - 1 ~ 14.87%).
    _fact(db, company, "revenue", "100", 2020)
    _fact(db, company, "revenue", "200", 2025)
    db.commit()
    # Ingesta nueva (id mayor): el emisor reestata ambos años.
    _fact(db, company, "revenue", "50", 2020)
    _fact(db, company, "revenue", "800", 2025)
    db.commit()

    observations = ScreenerService()._observations_from_rows(
        [],
        ScreenerService()._facts_by_company(db, {"revenue"})[company.id],
    )

    # El valor puntual es el NUEVO: 800 (2025), no 200.
    assert observations["revenue"].value == Decimal("800")
    # Y la CAGR usa la MISMA base nueva: (800/50)^(1/5) - 1, no (200/100)^(1/5) - 1.
    expected = (Decimal("800") / Decimal("50")) ** (Decimal("1") / 5) - 1
    assert observations["revenue_cagr"].value == pytest.approx(
        expected, rel=Decimal("1e-9")
    )
    # La lectura anterior habría dado ~0.1487, un crecimiento totalmente distinto.
    assert observations["revenue_cagr"].value > Decimal("0.7")


def test_duplicate_fiscal_years_agree_with_the_capped_query(db: Session):
    """La misma regla con la consulta acotada: la fila más reciente gana."""
    company = _company("DUPES")
    db.add(company)
    db.flush()
    for year in range(2015, 2026):
        _fact(db, company, "revenue", "100", year)
    db.commit()
    # Segunda pasada de ingesta sobre los mismos años: la serie nueva crece.
    for year in range(2015, 2026):
        _fact(db, company, "revenue", str(100 * (11 ** (year - 2015))), year)
    db.commit()

    service = ScreenerService()
    facts = service._facts_by_company(db, {"revenue"})[company.id]
    observations = service._observations_from_rows([], facts)

    # La consulta acotada trae las dos filas de cada año (no las deduplica); la
    # regla de deduplicación es de las observaciones y es la misma en ambos
    # caminos, así que las dos filas del mismo año se colapsan en la más nueva.
    assert len(facts) == 22
    assert observations["revenue"].value == Decimal(100 * (11**10))
    # La CAGR sale de la serie reestatada (crece x11 al año). Con la base vieja
    # (100 constante) habría dado 0.
    assert observations["revenue_cagr"].value == pytest.approx(
        Decimal(10), rel=Decimal("1e-9")
    )
    assert observations["revenue"].source_ids[0] == max(fact.id for fact in facts)
