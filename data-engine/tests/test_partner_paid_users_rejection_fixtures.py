"""Rejection fixtures from the audited ASTS partner data pack (2026-11-04).

Locks the incompatibilities found in that pack so they can never harden into
model "truth":

1. T-Mobile: 1.8M beta sign-ups (June 2025) cannot be divided by 34.974M
   postpaid accounts (Q3 2026). Numerator and denominator belong to different
   periods, so no attach rate may be computed from them.
2. Vodafone: 96M (Europe controlled mobile) + 161M (Africa controlled mobile)
   + 66M (JV/associates, ALL services) = 323M does NOT reconcile with the
   310M group mobile-customer headline, because the 66M is a different scope.
   Vodafone reconciliation with source: the only group-level mobile figure
   is the 310M headline KPI (FY25 annual report, FCA filing NI-000125619);
   the mobile-only share of the 66M JV/associate customers is N/D.
3. Paid penetration is N/D: every observed D2C uptake figure (KDDI 4M,
   T-Mobile 1.8M) is free/bundled, so no paid comparable exists and the model
   must return no number instead of inventing one.
4. Neither 607M definitive-partner lines nor a 5% attach rate is a fact: any
   computed value stays a labelled scenario ("orientation") with its
   limitations attached.
"""
from datetime import date
from decimal import Decimal
from typing import Any

from app.valuation.partner_paid_users import PartnerPaidInput, partner_paid_users

AS_OF = date(2026, 11, 4)

VODAFONE_FY25_FCA = ("https://data.fca.org.uk/artefacts/NSM/Portal/NI-000125619/"
                     "reports/213800TB53ELEUKM7Q61-2025-03-31-T01.html")
TMUS_Q3_2026_SEC = ("https://www.sec.gov/Archives/edgar/data/1283699/"
                    "000128369926000128/tmus09302026ex991.htm")
ATTS_4Q25 = ("https://investors.att.com/~/media/Files/A/ATT-IR-V2/financial-reports/"
             "quarterly-earnings/2025/4Q-2025/4Q25_ATT_Financial_and_Operational_"
             "Schedules_and_Non_GAAP_Reconciliations.pdf")
VZ_4Q25 = "https://www.verizon.com/about/sites/default/files/2026-02/vz_4q25_foi_013026r.pdf"
STC_Q4_25 = "https://www.stc.com/content/dam/groupsites/en/pdf/EarningsPresentationQ4-2025En.pdf"


def paid_comparable(*, period_start: date = date(2026, 1, 1),
                    period_end: date = date(2026, 6, 30),
                    denominator_as_of: date | None = None) -> dict[str, Any]:
    """A hypothetical but well-formed PAID comparable (1% attach, synthetic)."""
    return dict(paid_comparable_lines=Decimal(10000), comparable_eligible_lines=Decimal(1000000),
                comparable_period_start=period_start, comparable_period_end=period_end,
                comparable_metric="paid_subscription_lines",
                comparable_source="https://example.com/paid", comparable_citation="Synthetic paid comparable",
                transfer_rationale="Synthetic comparable scenario, not an ASTS forecast",
                transfer_source="https://example.com/rationale",
                comparable_eligible_as_of=denominator_as_of)


def partner_row(partner: str, pool: str, lines_m: str, eligibility_date: date,
                source: str, citation: str, declared_total: Decimal | None = None,
                declared_source: str = "", **comparable: Any) -> PartnerPaidInput:
    return PartnerPaidInput(partner, pool, Decimal(lines_m), eligibility_date, source, citation,
                            published=date(2026, 11, 3),
                            declared_pool_total_lines=declared_total,
                            declared_pool_total_source=declared_source,
                            **comparable)


def calc(rows: list[PartnerPaidInput]) -> dict:
    return partner_paid_users(rows, as_of=AS_OF, scenario="base", forecast_year=2033,
                              pool_reconciliation_source="Explicit fixture reconciliation")


def test_tmobile_mixed_numerator_denominator_periods_rejected():
    # 1.8M beta sign-ups measured June 2025; 34.974M postpaid accounts measured
    # 2026-09-30 (Q3 2026). Declaring the denominator's real date must fail closed.
    row = partner_row("T-Mobile US fixture", "own postpaid accounts", "34974000",
                      date(2026, 9, 30), TMUS_Q3_2026_SEC,
                      "Total postpaid accounts Q3 2026, SEC ex-99.1",
                      **paid_comparable(period_start=date(2025, 1, 1), period_end=date(2025, 6, 30),
                                        denominator_as_of=date(2026, 9, 30)))
    out = calc([row])
    assert out["status"] == "invalid"
    assert out["reason"] == "comparable_denominator_period_mismatch"
    assert out["paid_subscription_lines"] is None


def test_declared_denominator_inside_period_is_accepted():
    row = partner_row("Synthetic carrier", "own retail", "100000000", date(2026, 6, 30),
                      "https://example.com/pool", "Synthetic eligible lines",
                      **paid_comparable(denominator_as_of=date(2026, 6, 30)))
    out = calc([row])
    assert out["status"] == "orientation"
    assert out["paid_subscription_lines"] == 1000000


def test_vodafone_components_do_not_sum_to_headline():
    # Scope arithmetic documented by the FY25 report: components must not be summed.
    assert Decimal(96) + Decimal(161) + Decimal(66) != Decimal(310)
    comp: dict[str, Any] = dict(declared_total=Decimal(310000000), declared_source=VODAFONE_FY25_FCA)
    rows = [
        partner_row("Vodafone Europe fixture", "vodafone controlled mobile europe", "96000000",
                    date(2025, 3, 31), VODAFONE_FY25_FCA, "96m mobile customers, Europe incl. Türkiye",
                    **comp, **paid_comparable(denominator_as_of=date(2026, 3, 31))),
        partner_row("Vodafone Africa fixture", "vodafone controlled mobile africa", "161000000",
                    date(2025, 3, 31), VODAFONE_FY25_FCA, "161m mobile customers, Africa",
                    **comp, **paid_comparable(denominator_as_of=date(2026, 3, 31))),
        partner_row("Vodafone JV/associates fixture", "vodafone jv associates all-services", "66000000",
                    date(2025, 3, 31), VODAFONE_FY25_FCA, "66m customers, ALL services, five countries",
                    **comp, **paid_comparable(denominator_as_of=date(2026, 3, 31))),
    ]
    out = calc(rows)
    assert out["status"] == "invalid"
    assert out["reason"] == "pool_components_do_not_reconcile_declared_total"
    assert out["paid_subscription_lines"] is None


def test_vodafone_headline_310m_reconciles_as_single_scoped_figure():
    # The reconciled Vodafone figure is the 310M group mobile headline, alone.
    row = partner_row("Vodafone Group fixture", "vodafone group mobile customers", "310000000",
                      date(2025, 3, 31), VODAFONE_FY25_FCA,
                      "310m mobile customers headline KPI, FY25 annual report (FCA NI-000125619)",
                      declared_total=Decimal(310000000), declared_source=VODAFONE_FY25_FCA,
                      **paid_comparable(denominator_as_of=date(2026, 3, 31)))
    out = calc([row])
    assert out["status"] == "orientation"
    assert out["paid_subscription_lines"] == Decimal(310000000) * Decimal("0.01")


def test_paid_penetration_nd_yields_no_number():
    # Only free/bundled D2C uptake is observed (KDDI 4M free, T-Mobile 1.8M beta):
    # a paid comparable cannot be demonstrated, so the model must return nothing.
    free_only: dict[str, Any] = dict(paid_comparable_lines=Decimal(4000000), comparable_eligible_lines=Decimal(73800000),
                     comparable_period_start=date(2025, 4, 1), comparable_period_end=date(2026, 4, 23),
                     comparable_metric="unique_connected_users",
                     comparable_source="https://spark-journal.kddi.com/tsunagu/article00347/",
                     comparable_citation="au Starlink Direct, 4M connected users, free/bundled",
                     transfer_rationale="Free included service cannot establish a paid attach rate",
                     transfer_source="https://example.com/rationale",
                     comparable_eligible_as_of=None)
    row = partner_row("KDDI fixture", "au mobile subscriptions", "73800000", date(2026, 6, 30),
                      "https://www.kddi.com/english/corporate/ir/finance/mobile-subscription/",
                      "KDDI mobile subscriptions, June 2026", **free_only)
    out = calc([row])
    assert out["status"] == "invalid"
    assert out["paid_subscription_lines"] is None
    # With paid penetration N/D no valid row can even be built: empty pool stays missing.
    out_empty = calc([])
    assert out_empty["status"] == "missing"
    assert out_empty["paid_subscription_lines"] is None


def test_definitive_partner_lines_are_scenario_never_truth():
    # Real sourced lines of the four definitive partners (~607.035M total). Even with a
    # hypothetical 5% PAID comparable, the output is a labelled scenario with limitations,
    # never a fixed fact: status "orientation", limitations attached, inputs preserved.
    comp = paid_comparable()
    comp.update(paid_comparable_lines=Decimal(50000))  # 5% attach, synthetic
    rows = [
        partner_row("AT&T fixture", "at&t us mobility", "120105000", date(2025, 12, 31),
                    ATTS_4Q25, "Total Mobility Subscribers 120,105k, 4Q25 schedules", **comp),
        partner_row("Verizon fixture", "verizon wireless retail", "146930000", date(2025, 12, 31),
                    VZ_4Q25, "Consumer retail 115,903k + Business postpaid 31,027k, 4Q25 FOI", **comp),
        partner_row("Vodafone fixture", "vodafone group mobile customers", "310000000",
                    date(2025, 3, 31), VODAFONE_FY25_FCA, "310m mobile customers headline, FY25",
                    **comp),
        partner_row("stc fixture", "stc mobile subscribers", "30000000", date(2025, 12, 31),
                    STC_Q4_25, "30.0M mobile subscribers, Q4 2025 presentation", **comp),
    ]
    out = calc(rows)
    assert out["status"] == "orientation"
    expected = (Decimal(120105000) + Decimal(146930000) + Decimal(310000000)
                + Decimal(30000000)) * Decimal("0.05")
    assert out["paid_subscription_lines"] == expected
    assert "comparable_transfer_is_an_assumption" in out["limitations"]
    assert "subscription_lines_not_unique_people" in out["limitations"]
    # Nothing in the output pins the scenario as demonstrated demand.
    assert out["scenario"] == "base"
    assert all(c["paid_attach_rate"] == Decimal("0.05") for c in out["components"])
