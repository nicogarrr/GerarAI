"""El timeline no convierte operaciones no SEC en dolares ni en filings SEC."""
from datetime import date
from uuid import uuid4

import pytest

from app.models.entities import InsiderFiling, InsiderTransaction
from app.services.company_events_service import stored_timeline_events
from tests.test_company_timeline_events import _company, _memory_db


@pytest.mark.parametrize("form,currency,value,source,detail", [
    ("PDMR", "GBP", 250000, "tracefour", "250.000 GBP"),
    ("PDMR", "EUR", 50, "tracefour", "50 EUR"),
    ("CA-INSIDER", None, 250000, "Yahoo Finance (no oficial)", "Importe no comparable"),
    ("PDMR", None, None, "tracefour", "Importe no comparable"),
    ("4", None, 250000, "SEC", "250.000 $"),
])
def test_timeline_respeta_fuente_moneda_y_umbral(form, currency, value, source, detail):
    with _memory_db() as db:
        db.info["tenant_id"] = "timeline-test"
        company = _company(db, "ABC")
        filing = InsiderFiling(accession_number=uuid4().hex, form=form, issuer_cik="1", issuer_ticker="ABC", parser_version="1")
        db.add(filing)
        db.flush()
        db.add(InsiderTransaction(
            fingerprint=uuid4().hex, filing_id=filing.id, accession_number=filing.accession_number,
            form=form, issuer_ticker="ABC", code="P", is_derivative=False,
            value=value, tx_date="2026-11-13", data_quality={"currency": currency},
        ))
        db.commit()
        events = stored_timeline_events(db, company, date(2026, 11, 1), date(2026, 11, 30))
        assert len(events) == 1
        assert events[0]["source"] == source
        assert detail in events[0]["detail"]
