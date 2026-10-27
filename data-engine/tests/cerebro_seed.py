"""Base sembrada con la cartera y la watchlist reales de Nico (tests del Cerebro).

Cifras de prueba redondas y calculadas a mano en cada test: no son precios
reales. Cartera (tenant 1, base EUR): ASTS, BN, RKLB, UBER, ONDS, BABA, KRKNF.
Watchlist: CGEO.L, CPT, KKR, POOL, CB, UNH, HIMS, RXRX, NAUT, ABCL, IBRX, AAPL.
El tenant 2 guarda una posición «SECRET» que nunca debe aparecer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    AlertRule,
    Base,
    Company,
    DecisionJournalEntry,
    FundamentalModelVersion,
    InvestmentPlan,
    MarketPrice,
    Portfolio,
    Position,
    ResearchAlert,
    Tenant,
    ThesisVersion,
    WatchItem,
)

TODAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
PORTFOLIO = ["ASTS", "BN", "RKLB", "UBER", "ONDS", "BABA", "KRKNF"]
WATCHLIST = ["CGEO.L", "CPT", "KKR", "POOL", "CB", "UNH", "HIMS", "RXRX", "NAUT", "ABCL", "IBRX", "AAPL"]

# ticker: (nombre, bolsa, divisa, sector)
COMPANIES = {
    "ASTS": ("AST SpaceMobile", "NASDAQ", "USD", "Communication Services"),
    "BN": ("Brookfield Corporation", "NYSE", "USD", "Financials"),
    "RKLB": ("Rocket Lab", "NASDAQ", "USD", "Industrials"),
    "UBER": ("Uber Technologies", "NYSE", "USD", "Industrials"),
    "ONDS": ("Ondas Holdings", "NASDAQ", "USD", "Information Technology"),
    "BABA": ("Alibaba Group", "NYSE", "USD", "Consumer Discretionary"),
    "KRKNF": ("Kraken Robotics", "OTC", "USD", "Industrials"),
    "CGEO.L": ("Georgia Capital", "LSE", "GBP", "Financials"),
    "CPT": ("Camden Property Trust", "NYSE", "USD", "Real Estate"),
    "KKR": ("KKR & Co.", "NYSE", "USD", "Financials"),
    "POOL": ("Pool Corporation", "NASDAQ", "USD", "Consumer Discretionary"),
    "CB": ("Chubb", "NYSE", "USD", "Financials"),
    "UNH": ("UnitedHealth Group", "NYSE", "USD", "Health Care"),
    "HIMS": ("Hims & Hers Health", "NYSE", "USD", "Health Care"),
    "RXRX": ("Recursion Pharmaceuticals", "NASDAQ", "USD", "Health Care"),
    "NAUT": ("Nautilus Biotechnology", "NASDAQ", "USD", "Health Care"),
    "ABCL": ("AbCellera Biologics", "NASDAQ", "USD", "Health Care"),
    # IBRX se deja SIN ficha a propósito: «aún sin ficha en GerarAI».
    "AAPL": ("Apple", "NASDAQ", "USD", "Information Technology"),
}

# ticker: (cantidad, valor EUR, coste EUR, precio USD)
POSITIONS = {
    "ASTS": ("100", "4000", "2500", "46.00"),
    "BN": ("50", "2500", "2000", "57.50"),
    "RKLB": ("80", "1500", "1000", "21.50"),
    "UBER": ("20", "1200", "1300", "69.00"),
    "ONDS": ("300", "400", "600", "1.55"),
    "BABA": ("10", "300", "400", "34.50"),
    "KRKNF": ("100", "100", "50", "1.15"),
}
TOTAL_EUR = 10000.0

# Watchlist: último cierre y tesis publicada (valor esperado).
CLOSES = {"KKR": "120", "POOL": "300", "AAPL": "260", "CB": "280", "CGEO.L": "4200", "UNH": "320"}
THESES = {
    # ticker: (valor esperado, criterios de invalidación)
    "KKR": ("160", ["Las comisiones recurrentes caen por debajo del 60 % de los ingresos"]),
    "POOL": ("400", ["El margen bruto baja del 28 % dos trimestres seguidos"]),
    "AAPL": ("200", ["Los servicios dejan de crecer a doble dígito"]),
    # Precio en peniques (GBX) contra valor en GBP: margen NO calculable.
    "CGEO.L": ("42.55", ["El descuento sobre NAV se cierra sin recompras"]),
    "ASTS": ("60", ["Retraso de más de 12 meses en el despliegue de satélites BlueBird"]),
}


@dataclass
class FakeDcaReading:
    symbol: str
    level: int
    label: str
    status: str = "confirmed"
    signal_date: date = date(2026, 10, 1)


DCA_LEVELS = {
    "POOL": FakeDcaReading("POOL", 4, "4X DCA"),
    "UNH": FakeDcaReading("UNH", 3, "3X DCA"),
    "KKR": FakeDcaReading("KKR", 2, "2X DCA"),
    "AAPL": FakeDcaReading("AAPL", -1, "RECORTE LIGERO"),
    "ASTS": FakeDcaReading("ASTS", -2, "RECORTE FUERTE"),
    "UBER": FakeDcaReading("UBER", 1, "1X DCA"),
}


def fake_dca_reader(db, tenant, symbols):  # noqa: ARG001 - firma de DcaReader
    return {s: r for s, r in DCA_LEVELS.items() if s in symbols}


def no_dca_engine(db, tenant, symbols):  # noqa: ARG001 - motor DCA ausente
    return None


def seeded_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add_all([Tenant(id=1, external_id="nico"), Tenant(id=2, external_id="otro")])
    db.flush()
    companies: dict[str, Company] = {}
    for ticker, (name, exchange, currency, sector) in {**COMPANIES, "SECRET": ("Secret Co", "NYSE", "USD", "X")}.items():
        comp = Company(
            ticker=ticker, name=name, exchange=exchange, currency=currency, sector=sector,
            industry="x", company_type="standard", valuation_model="standard_dcf",
            special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(comp)
        companies[ticker] = comp
    db.flush()
    portfolio = Portfolio(tenant_id=1, name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.flush()
    for ticker, (qty, value, cost, price) in POSITIONS.items():
        db.add(Position(
            tenant_id=1, portfolio_id=portfolio.id, company_id=companies[ticker].id,
            quantity=Decimal(qty), average_cost=Decimal(cost) / Decimal(qty), market_price=Decimal(price),
            market_value=Decimal(value), market_value_base=Decimal(value), cost_basis_base=Decimal(cost),
            unrealized_pnl_base=Decimal(value) - Decimal(cost), currency="USD", base_currency="EUR",
            as_of=TODAY,
        ))
    db.add(Position(
        tenant_id=2, company_id=companies["SECRET"].id, quantity=Decimal("9"), average_cost=Decimal("1"),
        market_value=Decimal("99999"), market_value_base=Decimal("99999"), base_currency="EUR", as_of=TODAY,
    ))
    db.add(WatchItem(tenant_id=2, symbol="SECRET"))
    for symbol in WATCHLIST:
        db.add(WatchItem(tenant_id=1, symbol=symbol, company=COMPANIES.get(symbol, (None,))[0]))
    for ticker, close in CLOSES.items():
        db.add(MarketPrice(company_id=companies[ticker].id, date=date(2026, 10, 24), close=Decimal(close)))
        db.add(MarketPrice(company_id=companies[ticker].id, date=date(2026, 9, 1), close=Decimal("1")))
    for ticker, (expected, criteria) in THESES.items():
        db.add(ThesisVersion(
            tenant_id=1, company_id=companies[ticker].id, version=2, status="published",
            thesis_markdown="#", executive_summary="Resumen", rating="buy",
            expected_value=Decimal(expected), hypothesis=f"Tesis de {ticker}",
            invalidation_criteria=criteria, created_at=NOW, updated_at=NOW,
        ))
        # Tesis publicada: su valor justo solo cuenta con un modelo publicable
        # vigente del mismo tenant (puerta de publicación, fail-closed).
        db.add(FundamentalModelVersion(
            tenant_id=1, company_id=companies[ticker].id, version=1, engine_version="test",
            algorithm_version="test", framework_key="dcf", horizon_years=10, status="ok",
            publishable=True, input_fingerprint=f"cerebro-{ticker}", forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
        ))
    db.add(ResearchAlert(
        tenant_id=1, company_id=companies["ONDS"].id, severity="high", status="open",
        alert_type="price", title="ONDS cae un 12 % en una sesión", message="m", fingerprint="f1",
        created_at=NOW, last_triggered_at=NOW,
    ))
    db.add(AlertRule(
        tenant_id=1, company_id=companies["UBER"].id, name="UBER bajo 60", rule_type="price_below",
        condition={"price": 60}, target={},
    ))
    db.add(DecisionJournalEntry(
        tenant_id=1, company_id=companies["BN"].id, decision_date=date(2026, 10, 2), decision="buy",
        rationale="Descuento sobre el valor de los activos de Brookfield", what_must_be_true=["NAV crece"],
        price=Decimal("55"), status="open",
    ))
    db.add(InvestmentPlan(
        tenant_id=1, portfolio_id=portfolio.id, monthly_contribution=Decimal("300"),
        monthly_contribution_currency="EUR", start_date=date(2026, 1, 1), horizon_years=20,
        target_allocations=[{"ticker": "POOL", "weight": 50}, {"ticker": "UBER", "weight": 50}],
    ))
    db.commit()
    db.info["tenant_id"] = 1
    return db
