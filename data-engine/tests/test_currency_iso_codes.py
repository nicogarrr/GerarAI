"""Solo códigos de divisa reales: «NaN», «XYZ» o «ABC» ya no entran.

Bastaba con tres letras: una operación en «NaN», una cartera con divisa base
«XYZ», un tipo de cambio «ABC/EUR» o una aportación del plan en «QQQ» se
guardaban y esa posición/plan quedaba «sin tipo de cambio» para siempre (no
existe ninguno). Ahora vale la lista ISO 4217 (más CNH, el yuan offshore que
usa IBKR) y, donde ya se aceptaban, las subunidades de cotización (GBp, GBX,
ZAc, ILA...).
"""

import pytest
from pydantic import ValidationError

from app.api.routes.plan import ContributionInput, PlanUpsertInput
from app.api.routes.portfolio import (
    CreatePortfolioInput,
    FXRateInput,
    PortfolioConfigurationInput,
    PortfolioTransactionInput,
)
from app.valuation.currency import is_currency_code

FAKE = ["NaN", "XYZ", "ABC", "QQQ", "XXX"]


def _trade(currency: str) -> dict:
    return {"ticker": "AAPL", "action": "buy", "quantity": "1", "price": "10",
            "trade_date": "2026-01-02", "currency": currency}


@pytest.mark.parametrize("code", FAKE)
def test_invented_codes_are_rejected_everywhere(code):
    with pytest.raises(ValidationError):
        PortfolioTransactionInput(**_trade(code))
    with pytest.raises(ValidationError):
        CreatePortfolioInput(name="x", base_currency=code)
    with pytest.raises(ValidationError):
        PortfolioConfigurationInput(base_currency=code)
    with pytest.raises(ValidationError):
        FXRateInput(base_currency=code, quote_currency="EUR", rate="1.1", rate_date="2026-01-02")
    with pytest.raises(ValidationError):
        FXRateInput(base_currency="EUR", quote_currency=code, rate="1.1", rate_date="2026-01-02")
    with pytest.raises(ValidationError):
        ContributionInput(date="2026-01-02", amount=100, currency=code)
    with pytest.raises(ValidationError):
        PlanUpsertInput(monthly_contribution=100, start_date="2026-01-02",
                        monthly_contribution_currency=code)


@pytest.mark.parametrize("code", ["EUR", "usd", "GBP", "CHF", "JPY", "CNH", "HKD", "XAU"])
def test_real_codes_still_pass(code):
    assert PortfolioTransactionInput(**_trade(code)).currency == code
    assert CreatePortfolioInput(name="x", base_currency=code).base_currency == code
    PortfolioConfigurationInput(base_currency=code)
    FXRateInput(base_currency=code, quote_currency="EUR", rate="1.1", rate_date="2026-01-02")
    ContributionInput(date="2026-01-02", amount=100, currency=code)
    PlanUpsertInput(monthly_contribution=100, start_date="2026-01-02",
                    monthly_contribution_currency=code)


@pytest.mark.parametrize("code", ["GBp", "GBX", "ZAc", "ZAC", "ILA", "GBPENCE"])
def test_quote_subunits_still_pass_on_trades(code):
    assert PortfolioTransactionInput(**_trade(code)).currency == code


def test_a_subunit_is_not_a_base_currency():
    """Peniques como divisa base de la cartera: toda la valoración x100."""
    for code in ("GBp", "GBX", "ZAc"):
        with pytest.raises(ValidationError):
            CreatePortfolioInput(name="x", base_currency=code)


def test_helper():
    assert is_currency_code("eur") and is_currency_code("GBp")
    assert not is_currency_code("GBp", allow_subunits=False)
    assert not is_currency_code("NaN") and not is_currency_code("") and not is_currency_code(None)
