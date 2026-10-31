from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from app.services.data_source_health import get_data_source_registry

# Clave de este proveedor en el registry de salud de fuentes: sin registrar
# aqui los outcomes, un cambio de formato del XML o un bloqueo dejaria la
# fuente caida con el panel de salud en "healthy".
REGISTRY_KEY = "ecb"


@dataclass(frozen=True)
class ECBRates:
    rate_date: date
    # Multipliers convert an amount in the key currency into base_currency.
    rates: dict[str, Decimal]


class ECBClient:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    async def conversion_rates(self, *, base_currency: str, quote_currencies: set[str]) -> ECBRates:
        registry = get_data_source_registry()
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(self.url)
                response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except httpx.HTTPStatusError as exc:
            registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
            raise
        except httpx.TransportError as exc:
            registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            raise
        except ElementTree.ParseError as exc:
            # El BCE devolviendo HTML de error o un XML distinto es la senal de
            # cambio de formato de la fuente.
            registry.record_failure(REGISTRY_KEY, "XML invalido (posible cambio de formato o HTML de error)")
            raise RuntimeError("ECB no devolvio el XML esperado (posible cambio de formato)") from exc
        registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
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
