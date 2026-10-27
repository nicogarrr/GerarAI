"""El backfill BCE reconoce todas las subunidades que la valoracion divide /100.

Hallado con Hypothesis (tests/property/test_prop_currency_units.py):
``normalize_currency`` trata GBPENCE e ILX como subunidades (/100), pero el
backfill del BCE solo reconocia "GBp". Con esas grafias pedia al BCE la serie
de una "divisa" GBPENCE/ILX, que no existe, y no guardaba tipo: el informe
fiscal dejaba esas operaciones sin importe en euros.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services.connectors import ecb_history
from app.valuation.currency import MINOR_UNITS, normalize_currency


@pytest.mark.parametrize("raw", sorted(MINOR_UNITS))
def test_every_minor_unit_maps_like_the_valuation_layer(raw):
    normalized = ecb_history._normalize(raw)
    major, divisor = ecb_history.MINOR_UNITS.get(normalized, (normalized, Decimal("1")))
    assert (major, int(divisor)) == normalize_currency(raw)


@pytest.mark.parametrize("raw", ["USD", "usd", " EUR ", "GBP", "CHF"])
def test_major_codes_unchanged(raw):
    assert ecb_history._normalize(raw) == raw.strip().upper()


def test_backfill_requests_the_major_series_for_gbpence():
    requested = []

    async def fake_fetch(codes, start, end):
        requested.append(list(codes))
        return "CURRENCY,TIME_PERIOD,OBS_VALUE\nGBP,2025-03-03,0.83\n"

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        summary = asyncio.run(ecb_history.backfill_ecb_rates(
            db, currencies={"GBPENCE"}, start=date(2025, 3, 3), end=date(2025, 3, 3),
            fetcher=fake_fetch,
        ))
    assert requested == [["GBP"]]
    assert summary["not_published"] == []
