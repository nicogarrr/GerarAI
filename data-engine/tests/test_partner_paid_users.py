from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.valuation.partner_paid_users import PartnerPaidInput, partner_paid_users


def row():
    return PartnerPaidInput("Synthetic carrier", "own retail", Decimal(100000000), date(2026, 6, 30),
                            "https://example.com/pool", "Synthetic eligible lines",
                            Decimal(10000), Decimal(1000000), date(2026, 1, 1), date(2026, 6, 30),
                            "paid_subscription_lines", "https://example.com/paid", "Synthetic paid comparable",
                            "Synthetic comparable scenario, not an ASTS forecast", "https://example.com/rationale",
                            date(2026, 7, 1))


def calc(rows):
    return partner_paid_users(rows, as_of=date(2026, 11, 4), scenario="base", forecast_year=2033,
                              pool_reconciliation_source="Explicit synthetic reconciliation")


def test_explicit_paid_rate_multiplies_only_eligible_lines():
    assert calc([row()])["paid_subscription_lines"] == 1000000


def test_connections_free_activations_beta_and_compatibility_are_not_paid():
    for metric in ("unique_connected_users", "free_activations", "beta_users", "compatible_devices"):
        assert calc([replace(row(), comparable_metric=metric)])["paid_subscription_lines"] is None


def test_overlap_missing_sources_and_future_data_fail_closed():
    for rows in ([row(), row()], [replace(row(), comparable_source="")],
                 [replace(row(), published=date(2027, 1, 1))],
                 [replace(row(), paid_comparable_lines=Decimal(1000001))]):
        assert calc(rows)["paid_subscription_lines"] is None
