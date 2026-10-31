"""X-ray rules (idea from Ghostfolio's X-ray report): plain ok/aviso per concentration check."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Portfolio, Position
from app.schemas.api import PortfolioIntelligenceOut
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.portfolio_xray import portfolio_xray


def _by_id(rules):
    return {rule["id"]: rule for rule in rules}


def test_empty_portfolio_has_no_data_instead_of_ok():
    rules = _by_id(portfolio_xray({"weights": {}}, {}, "EUR"))
    assert set(rules) == {"posicion_unica", "divisa_unica", "sector_unico", "pais_unico"}
    assert {rule["status"] for rule in rules.values()} == {"sin_datos"}


def test_single_large_position_warns():
    rules = _by_id(portfolio_xray({"weights": {"AAPL": 0.35, "MSFT": 0.30, "KO": 0.25}}, {}, "EUR"))
    rule = rules["posicion_unica"]
    assert rule["status"] == "aviso" and rule["subject"] == "AAPL"
    assert rule["value"] == 0.35 and rule["threshold"] == 0.20


def test_foreign_currency_cluster_warns_but_base_currency_does_not():
    weights = {"AAPL": 0.1, "SAN": 0.1}
    foreign = _by_id(portfolio_xray({"weights": weights}, {"currencies": {"USD": 0.7, "EUR": 0.3}}, "EUR"))
    assert foreign["divisa_unica"]["status"] == "aviso" and foreign["divisa_unica"]["subject"] == "USD"
    home = _by_id(portfolio_xray({"weights": weights}, {"currencies": {"EUR": 0.9, "USD": 0.1}}, "eur"))
    assert home["divisa_unica"]["status"] == "ok" and home["divisa_unica"]["subject"] == "USD"


def test_sector_and_country_clusters_ignore_unknown_buckets():
    exposures = {"sectors": {"Unknown": 0.9, "Technology": 0.1}, "countries": {"US": 0.55, "ES": 0.45}}
    rules = _by_id(portfolio_xray({"weights": {"A": 0.1}}, exposures, "EUR"))
    assert rules["sector_unico"]["status"] == "ok" and rules["sector_unico"]["subject"] == "Technology"
    assert rules["pais_unico"]["status"] == "aviso" and rules["pais_unico"]["subject"] == "US"


def test_only_unknown_sector_is_no_data():
    rules = _by_id(portfolio_xray({"weights": {"A": 0.1}}, {"sectors": {"Unknown": 1.0}}, "EUR"))
    assert rules["sector_unico"]["status"] == "sin_datos"


def test_schema_field_is_additive():
    field = PortfolioIntelligenceOut.model_fields["xray"]
    assert field.is_required() is False


def test_intelligence_build_returns_xray():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t"
        db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
                          sector="Technology", industry="T", company_type="holding",
                          valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
        db.add(company)
        db.commit()
        db.add(Position(company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
                        market_price=Decimal("102"), market_value=Decimal("1020"),
                        unrealized_pnl=Decimal("20"), realized_pnl=Decimal("0"), currency="USD",
                        base_currency="USD", market_value_native=Decimal("1020"),
                        cost_basis_native=Decimal("1000"), market_value_base=Decimal("1020"),
                        cost_basis_base=Decimal("1000"), as_of=date.today(), source="probe"))
        db.commit()
        result = PortfolioIntelligenceService().build(db, years=5)
    rules = _by_id(result["xray"])
    assert rules["posicion_unica"]["status"] == "aviso" and rules["posicion_unica"]["subject"] == "AAPL"
    # Everything is in the base currency: no FX cluster to flag.
    assert rules["divisa_unica"]["status"] == "ok" and rules["divisa_unica"]["subject"] is None
    assert rules["sector_unico"]["status"] == "aviso"
    PortfolioIntelligenceOut.model_validate(result)
