"""Quarantine UK PDMR monetary fields pending checking the FCA document.

Provider price and total can be wrong together, so price * volume is not a
verification. No amount is inferred or repaired here. Existing persisted
rows can use the same read-time policy without updating the database.
"""
from __future__ import annotations

from typing import Any

# Checked against the original FCA notices on 2026-11-14. In these five
# provider rows totalValue was actually the document's unit/average price.
CONFIRMED_INCONSISTENT_FILINGS = frozenset({
    'a25fe9c8-34b0-4c21-8b83-4b8cf9ea717a|1',
    'bdf8e93e-f1da-49ae-8685-6c62c83cd3ef|1',
    'a6e19f1b-9753-4139-995c-f01f100b8a28|1',
    '0dcc6ca0-c013-445e-8cd7-387cdd1259fa|1',
    '8714cd09-c85d-48bb-b4c3-f70ea843728d|1',
})


def pdmr_monetary_quality(filing_id: str) -> dict[str, Any]:
    """An unreviewed row is unverified, not a confirmed provider error."""
    inconsistent = filing_id in CONFIRMED_INCONSISTENT_FILINGS
    return {
        'monetary_verification': 'inconsistent' if inconsistent else 'unverified',
        'provider_monetary_inconsistent': inconsistent,
    }


def monetary_fields(form: str | None, filing_id: str, price: Any, value: Any) -> dict[str, Any]:
    """No UK monetary values are verified by this module.

    Non-PDMR inputs are left unchanged, including known zero amounts.
    """
    if form != 'PDMR':
        return {'price': price, 'value': value}
    return {'price': None, 'value': None, **pdmr_monetary_quality(filing_id)}


def transaction_money(tx: Any, form: str | None = None) -> dict[str, Any]:
    """Read-time policy also covers old stored rows without rewriting evidence."""
    return monetary_fields(form or tx.form, tx.accession_number, tx.price, tx.value)


def transaction_value(tx: Any, form: str | None = None) -> float | None:
    """Never reconstruct quarantined PDMR totals from the correlated price."""
    fields = transaction_money(tx, form)
    if fields['value'] is not None:
        return float(fields['value'])
    if tx.shares is not None and fields['price'] is not None:
        return float(tx.shares) * float(fields['price'])
    return None
