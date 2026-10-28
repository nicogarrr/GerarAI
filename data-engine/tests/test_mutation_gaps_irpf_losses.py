"""IRPF loss carry-forward asserts that mutation testing (mutmut) showed were missing.

The 4-year window boundaries (art. 49 LIRPF), the 25 % cross-compensation
of an intermediate year's own loss and the casillas mapping could change
without any test noticing. See docs/testing/mutation.md.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_irpf_filing import build_loss_compensation

D = Decimal


def _losses(result):
    return {row["year"]: row for row in result["prior_losses"]}


def test_declared_window_includes_year_minus_4_and_excludes_minus_5_and_current():
    result = build_loss_compensation(
        [],
        D("0"),
        D("0"),
        2025,
        declared_pending={2020: D("10"), 2021: D("20"), 2024: D("30"), 2025: D("40"), 2023: D("0")},
    )
    rows = _losses(result)
    assert set(rows) == {2021, 2024}
    assert rows[2021]["remaining_base"] == 20.0
    assert rows[2021]["source"] == "anexo-c3-manual"
    assert result["estimativo"] is False
    assert result["basis"] == "art-49-lirpf+orden-hac-277-2026"


def test_declared_casillas_only_for_renta_2025():
    r2025 = _losses(build_loss_compensation([], D("0"), D("0"), 2025, declared_pending={2024: D("5")}))
    assert r2025[2024]["casilla_integracion"] is not None
    assert r2025[2024]["casilla_resto"] is not None
    r2026 = _losses(build_loss_compensation([], D("0"), D("0"), 2026, declared_pending={2025: D("5")}))
    assert r2026[2025]["casilla_integracion"] is None
    assert r2026[2025]["casilla_resto"] is None


def test_book_window_boundaries():
    nets = [
        {"year": 2020, "net_gyp_base": D("-10")},
        {"year": 2021, "net_gyp_base": D("-20")},
        {"year": 2025, "net_gyp_base": D("-40")},  # current year is not "prior"
    ]
    result = build_loss_compensation(nets, D("0"), D("0"), 2025)
    rows = _losses(result)
    assert set(rows) == {2021}
    assert rows[2021]["remaining_base"] == 20.0
    assert rows[2021]["source"] == "libro-estimativo"
    assert result["estimativo"] is True
    assert result["basis"] == "art-49-lirpf"


def test_book_incomplete_year_is_excluded_not_counted_as_zero():
    nets = [
        {"year": 2022, "net_gyp_base": D("-50"), "incomplete": True},
        {"year": 2023, "net_gyp_base": None},
        {"year": 2024, "net_gyp_base": D("-5")},
    ]
    result = build_loss_compensation(nets, D("0"), D("0"), 2025)
    assert [e["year"] for e in result["excluded_years"]] == [2022, 2023]
    assert set(_losses(result)) == {2024}


def test_intermediate_year_own_loss_uses_its_25pct_first_then_older_losses():
    nets = [
        {"year": 2021, "net_gyp_base": D("-100")},
        # 2022: own loss 40; 25 % of RCM 200 = 50 -> 40 for itself, 10 left for 2021.
        {"year": 2022, "net_gyp_base": D("-40"), "net_rcm_base": D("200")},
    ]
    rows = _losses(build_loss_compensation(nets, D("0"), D("0"), 2025))
    assert rows[2021]["remaining_base"] == 90.0
    assert 2022 not in rows  # fully absorbed by its own 25 %


def test_intermediate_gains_consume_oldest_loss_first_and_zero_net_is_neutral():
    nets = [
        {"year": 2021, "net_gyp_base": D("-30")},
        {"year": 2022, "net_gyp_base": D("-30")},
        {"year": 2023, "net_gyp_base": D("0"), "net_rcm_base": D("0")},
        {"year": 2024, "net_gyp_base": D("40")},
    ]
    rows = _losses(build_loss_compensation(nets, D("0"), D("0"), 2025))
    assert 2021 not in rows  # consumed first
    assert rows[2022]["remaining_base"] == 20.0
    assert 2023 not in rows


def test_intermediate_year_does_not_use_losses_already_expired_for_it():
    nets = [
        {"year": 2019, "net_gyp_base": D("-50")},
        {"year": 2023, "net_gyp_base": D("-10")},
        {"year": 2024, "net_gyp_base": D("5")},
    ]
    # Fiscal 2028: window 2024..2027; nothing from 2019/2023 survives.
    rows = _losses(build_loss_compensation(nets, D("0"), D("0"), 2028))
    assert rows == {}
    # Fiscal 2027: window 2023..2026; the 2024 gain (5) reduces 2023's loss.
    rows = _losses(build_loss_compensation(nets, D("0"), D("0"), 2027))
    assert rows[2023]["remaining_base"] == 5.0


def test_current_year_application_and_joint_25pct_limit():
    result = build_loss_compensation(
        [],
        D("-10"),
        D("100"),
        2025,
        declared_pending={2023: D("50"), 2024: D("50")},
    )
    # 25 % of 100 = 25; the current year's own loss (10) uses it first (0446).
    assert result["current_year_cross"] == {
        "negative_gyp_base": 10.0,
        "applied_to_income_base": 10.0,
        "casilla": "0446",
    }
    assert result["cross_limit_base"] == 25.0
    rows = _losses(result)
    assert rows[2023]["applied_to_income_base"] == 15.0
    assert rows[2023]["pending_start_base"] == 50.0
    assert rows[2023]["remaining_base"] == 35.0
    assert rows[2024]["applied_to_income_base"] == 0.0
    assert result["applied_to_income_total_base"] == 15.0
    assert result["remaining_to_carry_base"] == 85.0
    assert result["incomplete"] is False


def test_gains_capacity_then_rcm_with_pending_start_sum():
    result = build_loss_compensation(
        [],
        D("30"),
        D("40"),
        2026,
        declared_pending={2024: D("50")},
    )
    row = _losses(result)[2024]
    assert row["applied_to_gains_base"] == 30.0
    assert row["applied_to_income_base"] == 10.0
    assert row["pending_start_base"] == 50.0
    assert row["remaining_base"] == 10.0
    assert result["current_year_cross"]["casilla"] is None
    assert result["current_rcm_net_base"] == 40.0
    assert result["current_gyp_net_base"] == 30.0


def test_unknown_current_amounts_flag_incomplete():
    result = build_loss_compensation([], None, D("10"), 2025)
    assert result["incomplete"] is True
    assert result["current_gyp_net_base"] is None
    result = build_loss_compensation([], D("10"), None, 2025)
    assert result["incomplete"] is True
    assert result["current_rcm_net_base"] is None
    assert result["window_years"] == 4
