"""CSV annual journal must not silently discard the JSON journal entries."""
import asyncio
import csv
import io
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.export import export_year
from app.core.database import Base
from app.models import Company, DecisionJournalEntry, TaxReport


def body(response):
    async def collect():
        return b"".join([chunk if isinstance(chunk, bytes) else chunk.encode() async for chunk in response.body_iterator])
    return asyncio.run(collect()).decode("utf-8-sig")


@pytest.mark.parametrize("rationale", ["plain reasoning, with comma\nand newline", "=HYPERLINK(\"https://example.invalid\")", "  +1", "\tformula"])
def test_csv_retains_journal_entries_with_formula_protection(rationale):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker="CSVTEST", name="Synthetic", exchange="NYSE", currency="USD", sector="Test", industry="Test", company_type="standard", valuation_model="standard_dcf")
        db.add(company)
        db.flush()
        entry = DecisionJournalEntry(company_id=company.id, decision="watch", rationale=rationale, created_at=datetime(2026, 12, 31, 15, tzinfo=UTC))
        db.add(entry)
        db.add(TaxReport(fiscal_year=2026, summary={}, dividends=[], realized=[], misc={}))
        db.commit()
        json_rows = json.loads(body(export_year(2026, format="json", db=db)))["journal_entries"]
        rows = list(csv.reader(io.StringIO(body(export_year(2026, format="csv", db=db)))))
        journal = [r for r in rows[1:] if r[0] == "journal"]
        assert len(journal) == len(json_rows) == 1
        assert len(journal[0]) == len(rows[0]) == 8
        assert journal[0][1] == entry.decision_date.isoformat()
        assert journal[0][2] == str(company.id)
        assert journal[0][3] == "watch"
        expected = "'" + rationale if rationale[:1] == "\t" or rationale.lstrip().startswith(("=", "+")) else rationale
        assert journal[0][4] == expected
        assert journal[0][7] == str(entry.id)
