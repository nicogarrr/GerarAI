from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree

import httpx


@dataclass(frozen=True)
class ECBRates:
    rate_date: date
    # Multipliers convert an amount in the key currency into base_currency.
    rates: dict[str, Decimal]


class ECBClient:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    async def conversion_rates(
        self, *, base_currency: str, quote_currencies: set[str]
    ) -> ECBRates:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.url)
            response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        rate_date: date | None = None
        per_eur: dict[str, Decimal] = {"EUR": Decimal("1")}
        for element in root.iter():
            if element.attrib.get("time"):
                rate_date = date.fromisoformat(element.attrib["time"])
            currency = element.attrib.get("currency")
            rate = element.attrib.get("rate")
            if currency and rate:
                per_eur[currency.upper()] = Decimal(rate)
        base = base_currency.upper()
        if rate_date is None or base not in per_eur:
            raise RuntimeError(f"ECB does not provide the base currency {base}")
        rates = {}
        for quote in quote_currencies:
            normalized = quote.upper()
            if normalized not in per_eur:
                continue
            # ECB publishes units of each currency for one EUR. Therefore an
            # amount in quote converts to base by base_per_eur / quote_per_eur.
            rates[normalized] = per_eur[base] / per_eur[normalized]
        rates[base] = Decimal("1")
        return ECBRates(rate_date=rate_date, rates=rates)
