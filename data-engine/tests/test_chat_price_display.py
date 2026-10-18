from decimal import Decimal

from app.services.chat_service import _price_display


def test_price_display_currency_and_decimal_precision():
    assert _price_display(Decimal("343.460000"), "USD") == "$343.46"
    assert _price_display(Decimal("1343.460000"), "USD") == "$1,343.46"
    assert _price_display(Decimal("343.460000"), "EUR") == "343,46 €"
    assert _price_display(Decimal("343.460000"), "CAD") == "343,46 CAD"


def test_missing_currency_and_small_prices_are_not_misrepresented():
    assert _price_display(Decimal("343.460000"), None) == "343,46 (divisa no declarada)"
    assert _price_display(Decimal("343.460000"), "") == "343,46 (divisa no declarada)"
    assert _price_display(Decimal("0.0042"), "USD") == "$0.004200"
    assert _price_display(Decimal("0.00000042"), "USD") == "$0.0000004200"
    assert _price_display(Decimal("0"), "USD") == "$0.00"


def test_adjusted_close_is_labelled_and_metadata_preserved():
    from datetime import date

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Company, MarketPrice
    from app.models.entities import Base
    from app.services.chat_service import ChatService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = Company(ticker="AAPL", name="Apple", currency="USD", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add(MarketPrice(company_id=company.id, date=date.today(), close=Decimal("345"), adj_close=Decimal("343.460000"), source="Yahoo"))
        db.flush()
        response = ChatService()._deterministic_answer(db, "AAPL", "company", "AAPL")
        source = next(item for item in response.sources if item["type"] == "market_price")
        assert "cierre ajustado" in source["title"]
        assert "cierre ajustado" in response.answer
        assert source["price"] == "343.460000"
        assert source["adjusted"] is True
