from decimal import Decimal

from app.services.chat_service import _price_display


def test_price_display_currency_and_decimal_precision():
    assert _price_display(Decimal("343.460000"), "USD") == "$343.46"
    assert _price_display(Decimal("1343.460000"), "USD") == "$1,343.46"
    assert _price_display(Decimal("343.460000"), "EUR") == "343,46 €"
    assert _price_display(Decimal("343.460000"), "CAD") == "343,46 CAD"
