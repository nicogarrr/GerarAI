"""PortfolioIntelligenceService honesty contracts.

A position without a base-currency value (missing FX) must never be silently
counted as zero in totals, weights or exposures - it is excluded and reported
in missing_fx. A zero would understate concentration and distort exposures
without any visible signal.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, currency: str = "USD") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency=currency,
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(db, company, *, currency, market_value_base, market_value="1000"):
    position = Position(
        company_id=company.id,
        quantity=Decimal("10"),
        currency=currency,
        market_value=Decimal(market_value),
        market_value_base=(
            None if market_value_base is None else Decimal(str(market_value_base))
        ),
        as_of=date(2026, 9, 20),
    )
    db.add(position)
    db.commit()
    return position


def _eur_portfolio(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()


def test_position_without_base_value_is_reported_not_zeroed(db):
    _eur_portfolio(db)
    usd = _company(db, "AAA", currency="USD")
    eur = _company(db, "BBB", currency="EUR")
    # No EUR value available for AAA (missing FX upstream).
    _position(db, usd, currency="USD", market_value_base=None)
    _position(db, eur, currency="EUR", market_value_base="500")

    result = PortfolioIntelligenceService().build(db)

    missing = result["missing_fx"]
    assert [item["ticker"] for item in missing] == ["AAA"]
    assert missing[0]["quote_currency"] == "USD"
    assert missing[0]["base_currency"] == "EUR"
    # AAA is excluded, not zero-weighted: BBB carries 100% of the valued book.
    assert result["concentration"]["weights"] == {"BBB": 1.0}
    assert result["concentration"]["top_1"] == 1.0
    assert result["exposures"]["currencies"] == {"EUR": 1.0}
    assert any("missing FX" in note for note in result["coverage"]["limitations"])


def test_base_currency_fallback_uses_native_value(db):
    _eur_portfolio(db)
    eur = _company(db, "CCC", currency="EUR")
    # market_value_base missing but the position is already in base currency:
    # the native value is an honest fallback, no missing_fx entry.
    _position(db, eur, currency="EUR", market_value_base=None, market_value="750")

    result = PortfolioIntelligenceService().build(db)

    assert result["missing_fx"] == []
    assert result["concentration"]["weights"] == {"CCC": 1.0}
    assert result["exposures"]["currencies"] == {"EUR": 1.0}


def test_attribution_with_spot_null_adj_close_at_end_uses_close_and_declares_it(db):
    """Historica ajustada al inicio + fila spot (adj_close NULL) al final.

    El ratio de extremos exige AMBOS ajustados: sin la guarda, dividir por el
    None final lanzaba TypeError al abrir /portfolio/intelligence. Con ella el
    retorno queda honestamente desconocido.
    """
    _eur_portfolio(db)
    eur = _company(db, "DDD", currency="EUR")
    _position(db, eur, currency="EUR", market_value_base="1000")
    db.add(MarketPrice(
        company_id=eur.id, date=date(2026, 9, 24),
        open=Decimal("10"), high=Decimal("10"), low=Decimal("10"),
        close=Decimal("10"), adj_close=Decimal("9.5"), source="yfinance",
    ))
    db.add(MarketPrice(
        company_id=eur.id, date=date(2026, 9, 25),
        open=Decimal("11"), high=Decimal("11"), low=Decimal("11"),
        close=Decimal("11"), adj_close=None, source="Finnhub",
    ))
    db.commit()

    result = PortfolioIntelligenceService().build(db)

    positions = result["attribution"]["positions"]
    assert len(positions) == 1
    # La cola spot usa `close` (aproximacion declarada en coverage): 11 / 9.5 - 1.
    assert positions[0]["total_return"] == pytest.approx(11 / 9.5 - 1)
    assert result["coverage"]["spot_tail_positions"] == ["DDD"]


def _snapshots(db, portfolio, days, *, daily_return="0.001"):
    from app.models.entities import PortfolioDailySnapshot

    for i, day in enumerate(days):
        db.add(
            PortfolioDailySnapshot(
                portfolio_id=portfolio.id,
                snapshot_date=day,
                base_currency="USD",
                positions_value_base=Decimal("1000"),
                cash_value_base=Decimal("0"),
                total_value_base=Decimal("1000"),
                net_external_flow_base=Decimal("0"),
                daily_return=Decimal(daily_return),
                pricing_coverage=Decimal("1"),
            )
        )
    db.commit()


def test_history_full_window_is_not_truncated_to_first_page(db):
    """La rentabilidad de cartera usa TODA la ventana, no la primera pagina.

    La paginacion del endpoint (aea13ccd3) convirtio history() en una consulta
    de 20 filas: con una ventana de 5 anos (default) el resumen usaba solo las
    20 sesiones MAS ANTIGUAS y, al ser consecutivas y completas, pasaba el
    chequeo de exactitud: el TWR publicado cubria un mes, no la ventana.
    """
    from datetime import timedelta

    from app.models.entities import Portfolio
    from app.services.portfolio_snapshot_service import PortfolioSnapshotService

    db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
    db.commit()
    portfolio = db.query(Portfolio).one()
    start = date.today() - timedelta(days=40)
    days = [start + timedelta(days=i) for i in range(30)]
    _snapshots(db, portfolio, days)

    service = PortfolioSnapshotService()
    assert len(service.history(db, start=start)) == 20  # contrato del endpoint
    assert len(service.history(db, start=start, page_size=None)) == 30


def test_performance_summary_uses_the_whole_snapshot_window(db):
    """30 sesiones exactas: el TWR publicado compone las 30, no 20."""
    from datetime import timedelta

    from app.models.entities import Portfolio

    db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
    db.commit()
    portfolio = db.query(Portfolio).one()
    company = _company(db, "FULLW")
    _position(db, company, currency="USD", market_value_base="1000")
    start = date.today() - timedelta(days=40)
    days = [start + timedelta(days=i) for i in range(30)]
    _snapshots(db, portfolio, days)

    result = PortfolioIntelligenceService().build(db, years=1)
    expected = (1 + 0.001) ** 30 - 1  # 30 retornos diarios exactos
    assert result["performance"]["twr"] == pytest.approx(expected, rel=1e-9)
    assert result["performance"]["twr_is_exact"] is True


def test_build_no_hidrata_entidades_completas_de_snapshots_ni_benchmark(db):
    """Perf: build() solo lee 4 columnas de cada snapshot (snapshot_date,
    daily_return, pricing_coverage, metadata_) y 2 del benchmark (date,
    adj_close), asi que no debe materializar entidades ORM completas de
    esas tablas. Medido 2026-10-31 (19 pos x 1250 dias): la hidratacion de
    snapshots + benchmark eran ~40 de ~190 ms del build."""
    from datetime import timedelta

    from app.models.entities import Portfolio

    db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
    db.commit()
    portfolio = db.query(Portfolio).one()
    company = _company(db, "LIGHT")
    _position(db, company, currency="USD", market_value_base="1000")
    start = date.today() - timedelta(days=1300)
    days = [start + timedelta(days=i) for i in range(1250)]
    _snapshots(db, portfolio, days)
    spy = _company(db, "SPY")
    for day in days:
        db.add(
            MarketPrice(
                company_id=spy.id, date=day, open=Decimal("500"), high=Decimal("500"),
                low=Decimal("500"), close=Decimal("500"), adj_close=Decimal("500"),
                volume=100, source="test",
            )
        )
    db.commit()

    from sqlalchemy import event
    from sqlalchemy.orm import Session as _Session

    from app.models.entities import PortfolioDailySnapshot

    hidratadas = {"snapshots": 0, "benchmark": 0}

    @event.listens_for(_Session, "loaded_as_persistent")
    def _cuenta(session, instance):  # identity map es debil: hay que contar en caliente
        if isinstance(instance, PortfolioDailySnapshot):
            hidratadas["snapshots"] += 1
        elif isinstance(instance, MarketPrice):
            hidratadas["benchmark"] += 1

    result = PortfolioIntelligenceService().build(db, years=5)
    event.remove(_Session, "loaded_as_persistent", _cuenta)
    assert result["performance"]["twr_is_exact"] is True  # mismo calculo
    # Sin el arreglo: 1250 snapshots + 1250 filas de benchmark hidratadas.
    assert hidratadas == {"snapshots": 0, "benchmark": 0}, (
        f"build() hidrato {hidratadas}; debia leer solo columnas"
    )
