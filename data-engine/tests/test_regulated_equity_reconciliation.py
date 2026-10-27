"""La porcion de equity se aplica una vez, no dos, al dividendo."""

import pytest

from app.valuation.regulated_asset import reconcile_regulated_asset_model


@pytest.mark.parametrize("equity_ratio", [0.25, 0.4, 0.65])
@pytest.mark.parametrize("growth", [0.0, 0.02])
def test_equity_slice_reconciles_at_gordon_payout(equity_ratio, growth):
    roe = 0.10
    payout = (roe - growth) / roe
    out = reconcile_regulated_asset_model(
        rate_base=1000,
        allowed_roe=roe,
        equity_ratio=equity_ratio,
        cost_of_equity=0.08,
        payout_ratio=payout,
        growth=growth,
        convention="equity_slice",
    )
    assert out["dividend_next_year"] == pytest.approx(1000 * equity_ratio * roe * payout)
    assert out["dividend_leg_value"] == pytest.approx(out["excess_return_leg"]["equity_value"])
    assert out["residual"] == pytest.approx(0, abs=1e-9)
    assert out["reconciles"] is True


def test_whole_rate_base_unchanged():
    out = reconcile_regulated_asset_model(
        rate_base=1000,
        allowed_roe=0.10,
        equity_ratio=0.4,
        cost_of_equity=0.08,
        payout_ratio=1,
        growth=0,
        convention="whole_rate_base",
    )
    assert out["dividend_next_year"] == pytest.approx(100)
    assert out["dividend_leg_value"] == pytest.approx(1250)
    assert out["reconciles"] is True


def test_consistent_utility_has_zero_residual_hand_computed():
    """Caso de la auditoria de formulas (regulated_dividend_reconciliation).

    A mano: B = 100, ROE permitido 10 %, ke 8 %, g 3 %.
      Pata de exceso de rentabilidad: V = 100 + (0,10 - 0,08) * 100 / (0,08 - 0,03)
        = 100 + 2 / 0,05 = 140.
      Payout sostenible: 1 - g/ROE = 1 - 0,03/0,10 = 0,70.
      Pata de dividendo: D1 = B * ROE * payout = 100 * 0,10 * 0,70 = 7 (beneficio
        del año 1 sobre el book INICIAL; Penman, RI_t = E_t - ke * B_{t-1}).
        V = 7 / 0,05 = 140 -> residuo 0.
    Con el (1 + g) de mas, D1 = 7,21 y V = 144,2: residuo -4,2 en una utility
    perfectamente modelada.
    """
    out = reconcile_regulated_asset_model(
        rate_base=100,
        allowed_roe=0.10,
        equity_ratio=1.0,
        cost_of_equity=0.08,
        payout_ratio=0.70,
        growth=0.03,
    )
    assert out["excess_return_leg"]["equity_value"] == pytest.approx(140.0)
    assert out["dividend_next_year"] == pytest.approx(7.0)
    assert out["dividend_leg_value"] == pytest.approx(140.0)
    assert out["residual"] == pytest.approx(0.0, abs=1e-9)
    assert out["reconciling_payout"] == pytest.approx(0.70)
    assert out["reconciles"] is True
