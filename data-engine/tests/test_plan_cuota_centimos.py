"""La cuota mensual del plan se guarda con céntimos: una que redondea a 0 se rechaza.

``monthly_contribution`` exige > 0, pero la columna es Numeric(14, 2): 0,001 € (o
1e-320) pasaba la validación y el plan quedaba guardado con una cuota de 0,00 €,
justo lo que el «> 0» quería impedir. Las aportaciones ya lo rechazan
(«positivo con precisión de céntimos»).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.plan import PlanUpsertInput


def _payload(amount):
    return {"monthly_contribution": amount, "start_date": "2026-01-31"}


@pytest.mark.parametrize("amount", [0.001, 0.004, 1e-320])
def test_monthly_contribution_that_rounds_to_zero_cents_is_rejected(amount):
    with pytest.raises(ValidationError, match="céntimos"):
        PlanUpsertInput.model_validate(_payload(amount))


@pytest.mark.parametrize("amount", [0.005, 0.01, 1, 300, 299.999, 1_000_000])
def test_monthly_contribution_of_at_least_one_cent_is_accepted(amount):
    assert PlanUpsertInput.model_validate(_payload(amount)).monthly_contribution == amount
